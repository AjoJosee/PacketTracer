"""
Network Planner: VLSM subnetting, IP assignment, port allocation, and routing configuration.
Uses only Python standard library ('ipaddress', 'collections', etc.).
"""

import ipaddress
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Optional


class InterfaceBinding:
    def __init__(self, device: str, port: str, ip: Optional[str] = None, mask: Optional[str] = None, gateway: Optional[str] = None):
        self.device = device
        self.port = port
        self.ip = ip
        self.mask = mask
        self.gateway = gateway


class BroadcastDomain:
    def __init__(self, domain_id: int):
        self.domain_id = domain_id
        self.switches: Set[str] = set()
        self.pcs: Set[str] = set()
        self.router_connections: List[Tuple[str, str]] = []  # (router_name, connected_switch_or_pc)
        self.subnet: Optional[ipaddress.IPv4Network] = None
        self.allocated_ips: Dict[str, str] = {}  # device_name -> ip_str
        self.gateway_ip: Optional[str] = None

    @property
    def required_hosts(self) -> int:
        # Routers in this domain + PCs in this domain
        return len(self.router_connections) + len(self.pcs)


class PlannedNetwork:
    def __init__(self, routing_protocol: str = "ospf"):
        self.routing_protocol = routing_protocol
        self.devices: Dict[str, str] = {}  # name -> type
        self.domains: List[BroadcastDomain] = []
        self.device_ports: Dict[str, List[str]] = defaultdict(list)  # dev -> [used_ports]
        self.connections: List[Dict[str, str]] = []  # [{from_dev, from_port, to_dev, to_port, link_type}]
        self.router_interfaces: Dict[str, List[InterfaceBinding]] = defaultdict(list)
        self.pc_interfaces: Dict[str, InterfaceBinding] = {}
        self.static_routes: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)  # router -> [(net, mask, next_hop)]


class NetworkPlanner:
    def __init__(self, base_network: str = "192.168.0.0/16", routing_protocol: str = "ospf", vlsm: bool = True):
        self.base_network = ipaddress.IPv4Network(base_network, strict=False)
        self.routing_protocol = routing_protocol.lower()
        self.vlsm = vlsm

    def plan(self, devices: Dict[str, str], raw_connections: Set[Tuple[str, str]]) -> PlannedNetwork:
        planned = PlannedNetwork(routing_protocol=self.routing_protocol)
        planned.devices = dict(devices)

        # 1. Build adjacency graph
        adj: Dict[str, Set[str]] = defaultdict(set)
        for u, v in raw_connections:
            adj[u].add(v)
            adj[v].add(u)

        # 2. Partition into Broadcast Domains
        # Find all Layer-2 connected components (Switches and PCs, not traversing Routers)
        visited_l2: Set[str] = set()
        domain_list: List[BroadcastDomain] = []
        domain_counter = 1

        # Direct router-to-router connections are dedicated domains
        handled_r2r: Set[Tuple[str, str]] = set()
        for u, v in raw_connections:
            if devices.get(u) == 'router' and devices.get(v) == 'router':
                r2r_key = tuple(sorted([u, v]))
                if r2r_key not in handled_r2r:
                    handled_r2r.add(r2r_key)
                    bd = BroadcastDomain(domain_counter)
                    domain_counter += 1
                    bd.router_connections.append((u, v))
                    bd.router_connections.append((v, u))
                    domain_list.append(bd)

        # Find L2 components (Switches and PCs)
        for dev, dev_type in devices.items():
            if dev_type in ['switch', 'pc'] and dev not in visited_l2:
                comp_nodes: Set[str] = set()
                queue = deque([dev])
                visited_l2.add(dev)
                while queue:
                    curr = queue.popleft()
                    comp_nodes.add(curr)
                    for neighbor in adj[curr]:
                        if devices.get(neighbor) in ['switch', 'pc'] and neighbor not in visited_l2:
                            visited_l2.add(neighbor)
                            queue.append(neighbor)

                # Create domain for this L2 component
                bd = BroadcastDomain(domain_counter)
                domain_counter += 1
                for node in comp_nodes:
                    if devices.get(node) == 'switch':
                        bd.switches.add(node)
                    elif devices.get(node) == 'pc':
                        bd.pcs.add(node)

                # Find routers connected to any node in this L2 component
                for node in comp_nodes:
                    for neighbor in adj[node]:
                        if devices.get(neighbor) == 'router':
                            bd.router_connections.append((neighbor, node))

                domain_list.append(bd)

        # 3. VLSM Subnet Allocation
        # Sort domains by required host count descending
        sorted_domains = sorted(domain_list, key=lambda d: d.required_hosts, reverse=True)

        current_ip = int(self.base_network.network_address)
        max_ip = int(self.base_network.broadcast_address)

        for bd in sorted_domains:
            needed = max(bd.required_hosts, 2)
            if self.vlsm:
                # Find smallest subnet (largest prefix) that fits needed hosts
                prefix = 24
                for p in range(30, 20, -1):
                    if (2 ** (32 - p)) - 2 >= needed:
                        prefix = p
                        break
            else:
                prefix = 24 if needed > 2 else 30

            step = 2 ** (32 - prefix)
            # Align current_ip to subnet boundary
            if current_ip % step != 0:
                current_ip += step - (current_ip % step)

            if current_ip + step > max_ip:
                raise ValueError(f"Exhausted IP address space in {self.base_network}!")

            sub = ipaddress.IPv4Network((current_ip, prefix))
            bd.subnet = sub
            current_ip += step

            # Assign IP addresses within this subnet
            usable_hosts = list(sub.hosts())
            host_idx = 0

            # First IPs to routers
            for r_name, _ in bd.router_connections:
                r_ip = str(usable_hosts[host_idx])
                host_idx += 1
                bd.allocated_ips[r_name] = r_ip
                if bd.gateway_ip is None:
                    bd.gateway_ip = r_ip

            # Next IPs to PCs
            for pc_name in sorted(bd.pcs):
                pc_ip = str(usable_hosts[host_idx])
                host_idx += 1
                bd.allocated_ips[pc_name] = pc_ip

        planned.domains = sorted_domains

        # 4. Port Assignment and Cabling
        # Track available ports per device
        router_port_idx: Dict[str, int] = defaultdict(int)
        switch_port_idx: Dict[str, int] = defaultdict(int)

        def get_next_router_port(r: str) -> str:
            idx = router_port_idx[r]
            router_port_idx[r] += 1
            # 2911 router has GigabitEthernet0/0, 0/1, 0/2
            if idx < 3:
                return f"GigabitEthernet0/{idx}"
            return f"FastEthernet{idx-3}/0"

        def get_next_switch_port(sw: str) -> str:
            idx = switch_port_idx[sw]
            switch_port_idx[sw] += 1
            return f"FastEthernet0/{idx + 1}"

        # Assign ports for each connection
        for u, v in raw_connections:
            type_u = devices[u]
            type_v = devices[v]

            if type_u == 'router' and type_v == 'router':
                p_u = get_next_router_port(u)
                p_v = get_next_router_port(v)
                link_type = "eCrossOver"
            elif type_u == 'router' and type_v == 'switch':
                p_u = get_next_router_port(u)
                p_v = get_next_switch_port(v)
                link_type = "eStraightThrough"
            elif type_u == 'switch' and type_v == 'router':
                p_u = get_next_switch_port(u)
                p_v = get_next_router_port(v)
                link_type = "eStraightThrough"
            elif type_u == 'switch' and type_v == 'pc':
                p_u = get_next_switch_port(u)
                p_v = "FastEthernet0"
                link_type = "eStraightThrough"
            elif type_u == 'pc' and type_v == 'switch':
                p_u = "FastEthernet0"
                p_v = get_next_switch_port(v)
                link_type = "eStraightThrough"
            elif type_u == 'router' and type_v == 'pc':
                p_u = get_next_router_port(u)
                p_v = "FastEthernet0"
                link_type = "eCrossOver"
            elif type_u == 'pc' and type_v == 'router':
                p_u = "FastEthernet0"
                p_v = get_next_router_port(v)
                link_type = "eCrossOver"
            else:  # switch to switch
                p_u = get_next_switch_port(u)
                p_v = get_next_switch_port(v)
                link_type = "eCrossOver"

            conn_entry = {
                "from_dev": u,
                "from_port": p_u,
                "to_dev": v,
                "to_port": p_v,
                "link_type": link_type
            }
            planned.connections.append(conn_entry)

        # 5. Populate Interface Bindings
        # Match router and PC ports to domain IP allocations
        for bd in planned.domains:
            # Routers in this domain
            for r_name, target in bd.router_connections:
                # Find which connection connects r_name to target
                r_port = None
                for conn in planned.connections:
                    if conn["from_dev"] == r_name and conn["to_dev"] == target:
                        r_port = conn["from_port"]
                        break
                    elif conn["to_dev"] == r_name and conn["from_dev"] == target:
                        r_port = conn["to_port"]
                        break
                if r_port:
                    ip = bd.allocated_ips[r_name]
                    mask = str(bd.subnet.netmask)
                    planned.router_interfaces[r_name].append(
                        InterfaceBinding(r_name, r_port, ip, mask)
                    )

            # PCs in this domain
            for pc_name in bd.pcs:
                ip = bd.allocated_ips[pc_name]
                mask = str(bd.subnet.netmask)
                gw = bd.gateway_ip
                planned.pc_interfaces[pc_name] = InterfaceBinding(pc_name, "FastEthernet0", ip, mask, gw)

        # 6. Static Routing Calculation (if static protocol selected)
        if self.routing_protocol == "static":
            self._calculate_static_routes(planned)

        return planned

    def _calculate_static_routes(self, planned: PlannedNetwork):
        # Build router adjacency graph: RouterA <-> RouterB with next-hop IP
        # Two routers are adjacent if they share a broadcast domain
        router_adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list) # R1 -> [(R2, next_hop_ip_of_R2)]
        router_subnets: Dict[str, Set[ipaddress.IPv4Network]] = defaultdict(set)

        for bd in planned.domains:
            routers_in_bd = [r_name for r_name, _ in bd.router_connections]
            # Record directly connected subnets
            for r in routers_in_bd:
                router_subnets[r].add(bd.subnet)

            # Link pairs of routers in this domain
            for i in range(len(routers_in_bd)):
                for j in range(len(routers_in_bd)):
                    if i != j:
                        r_a = routers_in_bd[i]
                        r_b = routers_in_bd[j]
                        next_hop = bd.allocated_ips[r_b]
                        router_adj[r_a].append((r_b, next_hop))

        all_subnets = [bd.subnet for bd in planned.domains]
        routers = [dev for dev, t in planned.devices.items() if t == 'router']

        for r_src in routers:
            connected_subs = router_subnets[r_src]
            # Find routes to all subnets not directly connected
            for target_sub in all_subnets:
                if target_sub in connected_subs:
                    continue

                # Find which router connects to target_sub
                dest_routers = [r for r, subs in router_subnets.items() if target_sub in subs]
                if not dest_routers:
                    continue

                # BFS to find shortest path from r_src to any dest_router
                queue = deque([(r_src, [])])
                visited = {r_src}
                found_path = None

                while queue:
                    curr, path = queue.popleft()
                    if curr in dest_routers:
                        found_path = path
                        break
                    for nxt, nh in router_adj[curr]:
                        if nxt not in visited:
                            visited.add(nxt)
                            queue.append((nxt, path + [(nxt, nh)]))

                if found_path:
                    # First hop on the path gives the next-hop IP
                    _, next_hop_ip = found_path[0]
                    planned.static_routes[r_src].append(
                        (str(target_sub.network_address), str(target_sub.netmask), next_hop_ip)
                    )
