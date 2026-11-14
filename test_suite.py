"""
Automated Test Suite for Text-to-PacketTracer Generator.
Verifies parsing, VLSM planning, IOS config generation, XML compilation, and cryptographic roundtrip.
"""

import os
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ptgen import generate_pkt
from core.crypto.pipeline import Pkt_Pipeline


def test_ospf_lab():
    print("[TEST 1] Testing Multi-Router OSPF Lab...")
    input_file = os.path.join(BASE_DIR, "examples", "ospf_lab.txt")
    with open(input_file, "r") as f:
        content = f.read()

    out_file = "/tmp/test_ospf.pkt"
    generate_pkt(content, out_file, verbose=False)
    assert os.path.exists(out_file) and os.path.getsize(out_file) > 1000

    # Verify decompilation & XML content
    pipe = Pkt_Pipeline()
    with open(out_file, "rb") as f:
        xml_bytes = pipe.decompile(f.read())
    root = ET.fromstring(xml_bytes)

    # Check devices
    dev_names = {d.find(".//NAME").text for d in root.findall(".//NETWORK/DEVICES/DEVICE")}
    expected_devs = {"R1", "R2", "SW1", "PC1", "PC2", "PC3", "PC4", "PC5"}
    assert expected_devs.issubset(dev_names), f"Missing devices: {expected_devs - dev_names}"

    # Check OSPF config on R1
    r1_elem = [d for d in root.findall(".//NETWORK/DEVICES/DEVICE") if d.find(".//NAME").text == "R1"][0]
    r1_lines = [line.text for line in r1_elem.findall(".//RUNNINGCONFIG/LINE")]
    assert any("router ospf 1" in l for l in r1_lines), "R1 missing 'router ospf 1'"
    assert any("router-id 1.1.1.1" in l for l in r1_lines), "R1 missing router-id"
    assert any("network " in l for l in r1_lines), "R1 missing network statements"

    # Check PC1 IP & Gateway
    pc1_elem = [d for d in root.findall(".//NETWORK/DEVICES/DEVICE") if d.find(".//NAME").text == "PC1"][0]
    pc1_ip = pc1_elem.find(".//IP").text
    pc1_gw = pc1_elem.find(".//PORT_GATEWAY").text
    assert pc1_ip and pc1_gw, "PC1 missing IP or Gateway"
    print("  [✓] OSPF Lab passed successfully!")


def test_rip_lab():
    print("[TEST 2] Testing Multi-Router RIPv2 Lab...")
    input_file = os.path.join(BASE_DIR, "examples", "rip_lab.txt")
    with open(input_file, "r") as f:
        content = f.read()

    out_file = "/tmp/test_rip.pkt"
    generate_pkt(content, out_file, verbose=False)
    assert os.path.exists(out_file) and os.path.getsize(out_file) > 1000

    pipe = Pkt_Pipeline()
    with open(out_file, "rb") as f:
        xml_bytes = pipe.decompile(f.read())
    root = ET.fromstring(xml_bytes)

    r1_elem = [d for d in root.findall(".//NETWORK/DEVICES/DEVICE") if d.find(".//NAME").text == "R1"][0]
    r1_lines = [line.text for line in r1_elem.findall(".//RUNNINGCONFIG/LINE")]
    assert any("router rip" in l for l in r1_lines), "R1 missing 'router rip'"
    assert any("version 2" in l for l in r1_lines), "R1 missing 'version 2'"
    assert any("no auto-summary" in l for l in r1_lines), "R1 missing 'no auto-summary'"
    print("  [✓] RIPv2 Lab passed successfully!")


def test_static_lab():
    print("[TEST 3] Testing Static Routing Lab...")
    input_file = os.path.join(BASE_DIR, "examples", "static_lab.txt")
    with open(input_file, "r") as f:
        content = f.read()

    out_file = "/tmp/test_static.pkt"
    generate_pkt(content, out_file, verbose=False)
    assert os.path.exists(out_file) and os.path.getsize(out_file) > 1000

    pipe = Pkt_Pipeline()
    with open(out_file, "rb") as f:
        xml_bytes = pipe.decompile(f.read())
    root = ET.fromstring(xml_bytes)

    r1_elem = [d for d in root.findall(".//NETWORK/DEVICES/DEVICE") if d.find(".//NAME").text == "R1"][0]
    r1_lines = [line.text for line in r1_elem.findall(".//RUNNINGCONFIG/LINE")]
    assert any("ip route " in l for l in r1_lines), "R1 missing static route"
    print("  [✓] Static Routing Lab passed successfully!")


def test_shorthand_chain():
    print("[TEST 4] Testing Shorthand Dash Chain Syntax...")
    content = """
    routing: ospf
    PC1 - SW1 - R1 - R2 - SW2 - PC2
    """
    out_file = "/tmp/test_chain.pkt"
    generate_pkt(content, out_file, verbose=False)
    assert os.path.exists(out_file)

    pipe = Pkt_Pipeline()
    with open(out_file, "rb") as f:
        xml_bytes = pipe.decompile(f.read())
    root = ET.fromstring(xml_bytes)

    dev_names = {d.find(".//NAME").text for d in root.findall(".//NETWORK/DEVICES/DEVICE")}
    expected_devs = {"PC1", "SW1", "R1", "R2", "SW2", "PC2"}
    assert expected_devs.issubset(dev_names), f"Missing devices: {expected_devs - dev_names}"
    print("  [✓] Shorthand chain syntax passed successfully!")


def main():
    print("=" * 60)
    print("  Running Test-to-PacketTracer Test Suite")
    print("=" * 60)
    test_ospf_lab()
    test_rip_lab()
    test_static_lab()
    test_shorthand_chain()
    print("=" * 60)
    print("  ALL TESTS PASSED SUCCESSFULLY! (100% Verified)")
    print("=" * 60)


if __name__ == "__main__":
    main()
