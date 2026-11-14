"""
Cisco IOS Configuration Generator.
Generates valid Cisco IOS running-config command sequences for Routers and Switches.
Supports OSPFv2, RIPv2, and Static Routing.
"""

import ipaddress
import re
from typing import List, Tuple
from core.network_planner import PlannedNetwork, InterfaceBinding


def calculate_wildcard_mask(netmask_str: str) -> str:
    """Calculates wildcard mask from subnet mask, e.g. 255.255.255.248 -> 0.0.0.7"""
    mask_int = int(ipaddress.IPv4Address(netmask_str))
    wildcard_int = 0xFFFFFFFF ^ mask_int
    return str(ipaddress.IPv4Address(wildcard_int))


def generate_router_ios_config(router_name: str, planned: PlannedNetwork) -> List[str]:
    """Generates sequential Cisco IOS commands for a router."""
    lines: List[str] = [
        "!",
        "version 15.1",
        "no service timestamps log datetime msec",
        "no service timestamps debug datetime msec",
        "no service password-encryption",
        "!",
        f"hostname {router_name}",
        "!",
        "ip cef",
        "no ipv6 cef",
        "!",
        "spanning-tree mode pvst",
        "!"
    ]

    # Interface configurations
    interfaces = planned.router_interfaces.get(router_name, [])
    for iface in interfaces:
        lines.append(f"interface {iface.port}")
        lines.append(f" ip address {iface.ip} {iface.mask}")
        lines.append(" duplex auto")
        lines.append(" speed auto")
        lines.append(" no shutdown")
        lines.append("!")

    # Routing Configuration
    proto = planned.routing_protocol

    if proto == "ospf":
        # Derive router-id from router name, e.g. R1 -> 1.1.1.1, R2 -> 2.2.2.2
        m = re.search(r'\d+', router_name)
        rid_num = m.group(0) if m else "1"
        router_id = f"{rid_num}.{rid_num}.{rid_num}.{rid_num}"

        lines.append("router ospf 1")
        lines.append(f" router-id {router_id}")
        lines.append(" log-adjacency-changes")

        # Add network statements for all directly connected interfaces
        for iface in interfaces:
            net = ipaddress.IPv4Network(f"{iface.ip}/{iface.mask}", strict=False)
            wildcard = calculate_wildcard_mask(iface.mask)
            lines.append(f" network {net.network_address} {wildcard} area 0")
        lines.append("!")

    elif proto == "rip":
        lines.append("router rip")
        lines.append(" version 2")
        lines.append(" no auto-summary")

        # Add network statements
        networks_added = set()
        for iface in interfaces:
            net = ipaddress.IPv4Network(f"{iface.ip}/{iface.mask}", strict=False)
            net_str = str(net.network_address)
            if net_str not in networks_added:
                networks_added.add(net_str)
                lines.append(f" network {net_str}")
        lines.append("!")

    elif proto == "static":
        routes = planned.static_routes.get(router_name, [])
        for dest_net, mask, next_hop in routes:
            lines.append(f"ip route {dest_net} {mask} {next_hop}")
        if routes:
            lines.append("!")

    # Standard tail configuration
    lines.extend([
        "ip classless",
        "!",
        "line con 0",
        "!",
        "line aux 0",
        "!",
        "line vty 0 4",
        " login",
        "!",
        "end"
    ])

    return lines


def generate_switch_ios_config(switch_name: str) -> List[str]:
    """Generates baseline Cisco IOS running-config for a 2960 switch."""
    return [
        "!",
        "version 15.0",
        "no service timestamps log datetime msec",
        "no service timestamps debug datetime msec",
        "no service password-encryption",
        "!",
        f"hostname {switch_name}",
        "!",
        "spanning-tree mode pvst",
        "spanning-tree extend system-id",
        "!",
        "interface Vlan1",
        " no ip address",
        " shutdown",
        "!",
        "line con 0",
        "!",
        "line vty 0 4",
        " login",
        "line vty 5 15",
        " login",
        "!",
        "end"
    ]
