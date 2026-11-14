"""
Topology and Directive Parser for Text-to-PacketTracer.
Parses natural language and shorthand network descriptions into a structured graph.
"""

import re
from typing import Dict, List, Set, Tuple, Optional


class ParsedNetwork:
    def __init__(self):
        self.routing_protocol: str = "ospf"  # 'static', 'rip', 'ospf'
        self.base_network: str = "192.168.0.0/16"
        self.vlsm: bool = True
        self.devices: Dict[str, str] = {}  # name -> type ('router', 'switch', 'pc')
        self.connections: Set[Tuple[str, str]] = set()  # set of (dev_a, dev_b) sorted tuples

    def add_device(self, name: str, dev_type: Optional[str] = None) -> str:
        name = name.strip()
        canonical_name = self._canonical_device_name(name)
        if dev_type is None:
            dev_type = self._infer_device_type(canonical_name)
        self.devices[canonical_name] = dev_type
        return canonical_name

    def add_connection(self, dev_a: str, dev_b: str):
        dev_a = self.add_device(dev_a)
        dev_b = self.add_device(dev_b)
        if dev_a != dev_b:
            conn = tuple(sorted([dev_a, dev_b]))
            self.connections.add(conn)

    @staticmethod
    def _canonical_device_name(name: str) -> str:
        clean = re.sub(r'[^a-zA-Z0-9_-]', '', name)
        upper = clean.upper()
        # Normalize common names: R1 -> R1, ROUTER1 -> R1, PC1 -> PC1, SW1 -> SW1, SWITCH1 -> SW1
        m_r = re.match(r'^(?:ROUTER|R)(\d+)$', upper)
        if m_r:
            return f"R{m_r.group(1)}"
        m_sw = re.match(r'^(?:SWITCH|SW|S)(\d+)$', upper)
        if m_sw:
            return f"SW{m_sw.group(1)}"
        m_pc = re.match(r'^(?:PC|HOST|CLIENT)(\d+)$', upper)
        if m_pc:
            return f"PC{m_pc.group(1)}"
        return clean

    @staticmethod
    def _infer_device_type(name: str) -> str:
        upper = name.upper()
        if upper.startswith('R') or 'ROUTER' in upper:
            return 'router'
        elif upper.startswith('SW') or upper.startswith('S') or 'SWITCH' in upper:
            return 'switch'
        elif upper.startswith('PC') or 'HOST' in upper or 'CLIENT' in upper:
            return 'pc'
        return 'pc'


def parse_network_text(text: str) -> ParsedNetwork:
    net = ParsedNetwork()
    lines = text.strip().splitlines()

    for raw_line in lines:
        line = raw_line.strip()
        # Remove comments
        if '#' in line:
            line = line.split('#', 1)[0].strip()
        if not line:
            continue

        lower = line.lower()

        # Check routing protocol directive
        if any(kw in lower for kw in ['ospf', 'rip', 'static']):
            if 'ospf' in lower:
                net.routing_protocol = 'ospf'
            elif 'rip' in lower:
                net.routing_protocol = 'rip'
            elif 'static' in lower:
                net.routing_protocol = 'static'

        # Check base network directive: network: 10.0.0.0/8 or base: 192.168.0.0/16
        m_net = re.search(r'(?:network|base|ip|subnet)\s*[:=]\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+)', lower)
        if m_net:
            net.base_network = m_net.group(1)

        # Pattern 1: Shorthand dash/arrow chain: A - B - C or A -> B -> C or A -- B
        if any(sep in line for sep in [' - ', ' -- ', ' -> ', ' <-> ', '-', '->']):
            # Split by dash or arrow tokens
            tokens = re.split(r'\s*(?:<->|->|--|-)\s*', line)
            # Filter tokens that look like devices
            dev_tokens = [t.strip() for t in tokens if t.strip()]
            if len(dev_tokens) >= 2 and not any(kw in dev_tokens[0].lower() for kw in ['routing', 'protocol', 'network', 'use']):
                for i in range(len(dev_tokens) - 1):
                    net.add_connection(dev_tokens[i], dev_tokens[i + 1])
                continue

        # Pattern 2: Natural language: "X connects to Y, Z and W" or "X is connected to Y and Z"
        m_conn = re.search(r'([a-zA-Z0-9_-]+)\s+(?:connects to|is connected to|links to|connect to)\s+(.+)', line, re.IGNORECASE)
        if m_conn:
            src = m_conn.group(1).strip()
            dest_part = m_conn.group(2).strip().rstrip('.')
            # Split dest_part by comma, 'and', 'with', spaces
            dest_tokens = re.split(r'[,;]|\s+and\s+|\s+with\s+', dest_part, flags=re.IGNORECASE)
            for dt in dest_tokens:
                target = dt.strip()
                if target:
                    # Ignore trailing instruction words
                    if target.lower() in ['ospf', 'rip', 'static', 'vlsm']:
                        continue
                    net.add_connection(src, target)
            continue

        # Pattern 3: Simple pairing: "X to Y" or "connect X to Y"
        m_pair = re.search(r'(?:connect\s+)?([a-zA-Z0-9_-]+)\s+to\s+([a-zA-Z0-9_-]+)', line, re.IGNORECASE)
        if m_pair:
            net.add_connection(m_pair.group(1), m_pair.group(2))
            continue

    return net
