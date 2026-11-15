#!/usr/bin/env python3
"""
Text-to-PacketTracer (.pkt) Generator
====================================
An offline tool that converts plain-text network topology descriptions into
functional Cisco Packet Tracer (.pkt) project files.

Features:
- Pure Python 3 standard library (zero external pip packages).
- Automatic VLSM subnetting and IP allocation.
- Automatic router interface & PC gateway assignment.
- Automatic routing configuration: OSPFv2, RIPv2, and Static routes.
- Generates native, encrypted .pkt files compatible with Cisco Packet Tracer.

Usage:
  python3 ptgen.py -i topology.txt -o output.pkt
  python3 ptgen.py "R1 connects to SW1, PC1. SW1 connects to R2. Use OSPF." -o lab.pkt
  python3 ptgen.py   # Interactive mode
"""

import argparse
import os
import sys

# Ensure local core package is importable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.parser import parse_network_text, ParsedNetwork
from core.network_planner import NetworkPlanner, PlannedNetwork
from core.builder import PacketTracerBuilder
from core.ios_config import get_classful_network


def print_banner():
    banner = """
========================================================================
       Offline Text-to-Cisco Packet Tracer (.pkt) Generator
========================================================================
"""
    print(banner.strip())


def generate_pkt(text: str, output_path: str, base_net: str = "192.168.0.0/16", vlsm: bool = False, verbose: bool = True) -> str:
    # 1. Parse network description
    parsed: ParsedNetwork = parse_network_text(text)
    if not parsed.devices:
        raise ValueError("No devices or connections were found in the provided text.")

    # Override base network if specified in text
    effective_base = parsed.base_network if parsed.base_network != "192.168.0.0/16" else base_net

    # 2. Plan network (VLSM, IP, routing)
    planner = NetworkPlanner(
        base_network=effective_base,
        routing_protocol=parsed.routing_protocol,
        vlsm=vlsm
    )
    planned: PlannedNetwork = planner.plan(parsed.devices, parsed.connections)

    # 3. Assemble XML and compile .pkt
    builder = PacketTracerBuilder(templates_dir=os.path.join(BASE_DIR, "templates"))
    builder.build_pkt(planned, output_path)

    # 4. Generate comprehensive info text file alongside .pkt
    info_path = os.path.splitext(output_path)[0] + "_info.txt"
    info_content = generate_info_text(planned, output_path)
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(info_content)

    if verbose:
        print_summary(planned, output_path, info_path)

    return output_path


def generate_info_text(planned: PlannedNetwork, pkt_path: str) -> str:
    lines = []
    lines.append("=" * 78)
    lines.append("        CISCO PACKET TRACER TOPOLOGY & ADDRESSING SPECIFICATION")
    lines.append("=" * 78)
    lines.append(f"Project File     : {os.path.basename(pkt_path)}")
    lines.append(f"Routing Protocol : {planned.routing_protocol.upper()}")
    lines.append(f"Total Devices    : {len(planned.devices)}")
    lines.append(f"Total Cables     : {len(planned.connections)}")
    lines.append(f"Broadcast Domains: {len(planned.domains)}")
    lines.append("=" * 78)
    lines.append("")

    # 1. Device Addressing Table
    lines.append("1. COMPLETE DEVICE ADDRESSING TABLE")
    lines.append("-" * 78)
    lines.append(f"{'Device':<10} {'Interface':<22} {'IP Address':<18} {'Subnet Mask':<18} {'Gateway':<18}")
    lines.append("-" * 78)

    routers = [d for d, t in planned.devices.items() if t == "router"]
    switches = [d for d, t in planned.devices.items() if t == "switch"]
    pcs = [d for d, t in planned.devices.items() if t == "pc"]

    for r in sorted(routers):
        ifaces = planned.router_interfaces.get(r, [])
        for iface in ifaces:
            lines.append(f"{r:<10} {iface.port:<22} {iface.ip:<18} {iface.mask:<18} {'N/A (Router)':<18}")

    for sw in sorted(switches):
        lines.append(f"{sw:<10} {'Vlan1 (Unmanaged)':<22} {'Unassigned':<18} {'Unassigned':<18} {'N/A (Layer 2)':<18}")

    for pc in sorted(pcs):
        iface = planned.pc_interfaces.get(pc)
        if iface:
            lines.append(f"{pc:<10} {'FastEthernet0':<22} {iface.ip:<18} {iface.mask:<18} {iface.gateway:<18}")

    lines.append("-" * 78)
    lines.append("")

    # 2. Physical Cabling Table
    lines.append("2. PHYSICAL CABLING & PORT CONNECTIONS")
    lines.append("-" * 78)
    lines.append(f"{'From Device':<14} {'From Port':<22} {'To Device':<14} {'To Port':<22} {'Cable Type':<12}")
    lines.append("-" * 78)
    for conn in planned.connections:
        c_type = "Straight-Through" if "Straight" in conn["link_type"] else "Cross-Over"
        lines.append(f"{conn['from_dev']:<14} {conn['from_port']:<22} {conn['to_dev']:<14} {conn['to_port']:<22} {c_type:<16}")
    lines.append("-" * 78)
    lines.append("")

    # 3. VLSM Subnet Allocations
    lines.append("3. VLSM SUBNET ALLOCATION TABLE")
    lines.append("-" * 78)
    lines.append(f"{'Subnet (CIDR)':<20} {'Netmask':<18} {'Connected Routers':<20} {'Connected PCs':<20}")
    lines.append("-" * 78)
    for bd in planned.domains:
        r_str = ", ".join([r for r, _ in bd.router_connections]) or "None"
        pc_str = ", ".join(sorted(bd.pcs)) or "None"
        lines.append(f"{str(bd.subnet):<20} {str(bd.subnet.netmask):<18} {r_str:<20} {pc_str:<20}")
    lines.append("-" * 78)
    lines.append("")

    # 4. Routing Configuration Details
    lines.append("4. ROUTING CONFIGURATION")
    lines.append("-" * 78)
    if planned.routing_protocol == "ospf":
        lines.append("Protocol: OSPFv2 (Process ID: 1, Area: 0)")
        for r in sorted(routers):
            lines.append(f"\n[Router {r}]")
            for bd in planned.domains:
                for cr, _ in bd.router_connections:
                    if cr == r:
                        lines.append(f"  network {bd.subnet.network_address} {bd.subnet.hostmask} area 0")
    elif planned.routing_protocol == "rip":
        lines.append("Protocol: RIPv2 (version 2, no auto-summary)")
        for r in sorted(routers):
            lines.append(f"\n[Router {r}]")
            seen_nets = set()
            for iface in planned.router_interfaces.get(r, []):
                c_net = get_classful_network(iface.ip)
                if c_net not in seen_nets:
                    seen_nets.add(c_net)
                    lines.append(f"  network {c_net}")
    elif planned.routing_protocol == "static":
        lines.append("Protocol: Static Routing")
        for r, routes in planned.static_routes.items():
            lines.append(f"\n[Router {r}]")
            for dest_net, mask, nh in routes:
                lines.append(f"  ip route {dest_net} {mask} {nh}")
    lines.append("-" * 78)
    lines.append("")

    # 5. Testing & Verification Guide
    lines.append("5. STEP-BY-STEP TESTING & VERIFICATION GUIDE IN PACKET TRACER")
    lines.append("-" * 78)
    lines.append("1. Open the .pkt file in Cisco Packet Tracer.")
    lines.append("2. CRITICAL - BYPASS INITIAL CONVERGENCE:")
    lines.append("   - When Packet Tracer first opens, switch ports take 30-50s to transition from STP listening")
    lines.append("     to forwarding (amber dots turn green), and OSPF routers take ~40s to elect DR/BDR.")
    lines.append("   - Click the 'Fast Forward Time' button (>>) in the bottom toolbar 2 to 3 times (or press Alt+D).")
    lines.append("   - Verify all link lights turn solid green.")
    lines.append("3. TESTING CONNECTIVITY:")
    lines.append("   - Click on any PC (e.g. PC1) -> 'Desktop' tab -> 'Command Prompt'.")
    if len(pcs) >= 2:
        pc_sample = sorted(pcs)[0]
        target_sample = sorted(pcs)[-1]
        pc_target_ip = planned.pc_interfaces[target_sample].ip
        lines.append(f"   - To test end-to-end ping from {pc_sample} to {target_sample}:")
        lines.append(f"       ping {pc_target_ip}")
        lines.append("   - Note: The first ping packet may timeout due to ARP discovery; packets 2-4 will reply 100%.")
    lines.append("=" * 78)
    return "\n".join(lines)


def print_summary(planned: PlannedNetwork, output_path: str, info_path: Optional[str] = None):
    print("\n[+] Network Plan Summary:")
    print(f"    Routing Protocol : {planned.routing_protocol.upper()}")
    print(f"    Total Devices    : {len(planned.devices)}")
    print(f"    Total Cables     : {len(planned.connections)}")
    print(f"    Broadcast Domains: {len(planned.domains)}")

    print("\n[+] Subnet Allocations (VLSM):")
    for bd in planned.domains:
        r_str = ", ".join([r for r, _ in bd.router_connections]) or "None"
        pc_str = ", ".join(sorted(bd.pcs)) or "None"
        print(f"    Subnet: {str(bd.subnet):<18} | Netmask: {str(bd.subnet.netmask):<15} | Routers: [{r_str}] | PCs: [{pc_str}]")

    print("\n[+] Device IP Assignments:")
    routers = [d for d, t in planned.devices.items() if t == "router"]
    pcs = [d for d, t in planned.devices.items() if t == "pc"]

    for r in sorted(routers):
        print(f"    Router '{r}':")
        for iface in planned.router_interfaces.get(r, []):
            print(f"       {iface.port:<20} -> IP: {iface.ip} (Mask: {iface.mask})")

    for pc in sorted(pcs):
        iface = planned.pc_interfaces.get(pc)
        if iface:
            print(f"    PC '{pc:<6}'             -> IP: {iface.ip:<15} Mask: {iface.mask:<15} Gateway: {iface.gateway}")

    if planned.routing_protocol == "static":
        print("\n[+] Generated Static Routes:")
        for r, routes in planned.static_routes.items():
            print(f"    Router '{r}':")
            for dest_net, mask, nh in routes:
                print(f"       ip route {dest_net} {mask} {nh}")

    file_size = os.path.getsize(output_path)
    print(f"\n[+] Success! Native Packet Tracer project written to:")
    print(f"    -> {os.path.abspath(output_path)} ({file_size:,} bytes)")
    if info_path:
        print(f"    -> Full Details Reference: {os.path.abspath(info_path)}\n")


def interactive_mode():
    print_banner()
    print("Enter your network topology description below.")
    print("When finished, enter an empty line (or type 'DONE' on a new line):\n")

    input_lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().upper() == "DONE":
            break
        if not line and input_lines and not input_lines[-1]:
            break  # Two consecutive empty lines ends input
        input_lines.append(line)

    text = "\n".join(input_lines).strip()
    if not text:
        print("[-] Error: No input provided.")
        sys.exit(1)

    out_file = input("\nEnter output file name [default: network_lab.pkt]: ").strip()
    if not out_file:
        out_file = "network_lab.pkt"
    if not out_file.endswith(".pkt"):
        out_file += ".pkt"

    generate_pkt(text, out_file)


def main():
    parser = argparse.ArgumentParser(
        description="Offline Text-to-Cisco Packet Tracer (.pkt) Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 ptgen.py -i examples/ospf_lab.txt -o ospf_lab.pkt
  python3 ptgen.py -i examples/rip_lab.txt -o rip_lab.pkt
  python3 ptgen.py "R1 connects to SW1, PC1. SW1 connects to R2, PC2. Use OSPF." -o out.pkt
  python3 ptgen.py   (launches interactive mode)
"""
    )
    parser.add_argument("text", nargs="?", help="Direct text description of the network")
    parser.add_argument("-i", "--input", help="Path to input text file containing network description")
    parser.add_argument("-o", "--output", default="output.pkt", help="Path to output .pkt file (default: output.pkt)")
    parser.add_argument("--base", default="192.168.0.0/16", help="Base IP network for allocation (default: 192.168.0.0/16)")
    parser.add_argument("--vlsm", action="store_true", help="Enable VLSM (default is simple consecutive /24 subnets)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode (suppress summary output)")

    args = parser.parse_args()

    # If no arguments given and stdin is a TTY, launch interactive mode
    if not args.text and not args.input:
        if sys.stdin.isatty():
            interactive_mode()
            return
        else:
            # Read from piped stdin
            content = sys.stdin.read().strip()
            if not content:
                parser.print_help()
                return
            generate_pkt(content, args.output, base_net=args.base, vlsm=args.vlsm, verbose=not args.quiet)
            return

    # Determine text source
    if args.input:
        if not os.path.isfile(args.input):
            print(f"[-] Error: Input file '{args.input}' not found.", file=sys.stderr)
            sys.exit(1)
        with open(args.input, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = args.text

    generate_pkt(content, args.output, base_net=args.base, vlsm=args.vlsm, verbose=not args.quiet)


if __name__ == "__main__":
    main()
