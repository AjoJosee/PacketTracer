# Offline Text-to-Cisco Packet Tracer (.pkt) Generator

A lightweight, zero-dependency offline application that converts plain-text network topology descriptions into native, fully configured Cisco Packet Tracer (`.pkt`) project files.

Built for restricted offline Ubuntu environments and USB pendrives.

---

## Features

- **Native `.pkt` Generation:** Produces genuine Cisco Packet Tracer project files that open directly in Cisco Packet Tracer (verified against PT 7.x, 8.x, and 9.0.1).
- **Zero External Dependencies:** Built **100% on Python 3 standard library** (`ipaddress`, `re`, `struct`, `zlib`, `ctypes`, `xml.etree.ElementTree`). Requires no `pip install`, no internet access, and no root permissions.
- **Automatic VLSM Subnetting:** Automatically discovers broadcast domains and calculates variable-length subnet masks, network addresses, and usable host pools.
- **Automatic IP & Gateway Allocation:** Assigns router interface IPs, PC IP addresses, subnet masks, and default gateways.
- **Full Routing Support:**
  - **OSPFv2:** Automatic router-ID assignment, interface activation, and area 0 wildcard network statements.
  - **RIPv2:** Automatic `version 2`, `no auto-summary`, and network statements.
  - **Static Routing:** Automatic shortest-path graph calculation and `ip route <dest> <mask> <next-hop>` command synthesis.
- **Visual Canvas Layout:** Automatically positions devices cleanly on the Packet Tracer canvas so topologies look neat and readable.

---

## Quick Start

### 1. Run with an Input File
```bash
python3 ptgen.py -i examples/ospf_lab.txt -o my_ospf_lab.pkt
```

### 2. Run Directly from Command Line
```bash
python3 ptgen.py "R1 connects to SW1, PC1. SW1 connects to R2, PC2. Use OSPF." -o demo.pkt
```

### 3. Interactive Mode
Simply run without arguments to paste or type your network description interactively:
```bash
python3 ptgen.py
```

### 4. Run Automated Test Suite
```bash
python3 test_suite.py
```

---

## Supported Input Formats

The parser accepts natural English sentences, shorthand connections, or chained topologies.

### Example 1: Natural English (Your Exact Requirement)
```text
R1 connects to PC1, PC2 and SW1.
SW1 connects to PC3 and R2.
R2 connects to PC4 and PC5.

Use OSPF.
```

### Example 2: Shorthand Dash Connections
```text
routing: rip

R1 - SW1
SW1 - PC1
SW1 - PC2
R1 - R2
R2 - SW2
SW2 - PC3
SW2 - PC4
```

### Example 3: Chained Topology
```text
routing: static
PC1 - SW1 - R1 - R2 - SW2 - PC2
```

### Configuration Directives
You can specify directives anywhere in your text:
- **Routing Protocol:** `use ospf`, `use rip`, `use static`, or `routing: ospf`
- **Base Network:** `network: 10.0.0.0/8` or `base: 172.16.0.0/16` (default is `192.168.0.0/16`)
- **Disable VLSM:** pass `--no-vlsm` on the command line if you prefer standard `/24` subnets for all LANs.

---

## Device Naming Rules

- **Routers:** Start with `R` or `Router` (e.g., `R1`, `R2`, `Router1`). Modeled with Cisco 2911 (GigabitEthernet interfaces).
- **Switches:** Start with `SW`, `S`, or `Switch` (e.g., `SW1`, `SW2`, `Switch1`). Modeled with Cisco 2960-24TT.
- **PCs:** Start with `PC`, `Host`, or `Client` (e.g., `PC1`, `PC2`, `Client1`). Configured with FastEthernet0.

---

## Using on a USB Drive / Target Ubuntu Machine

This entire folder is completely self-contained (under 2 MB):

1. **Copying to/from USB:**
   - Copy the `PacketTracer/` folder to your USB drive.
   - On the secure Ubuntu target machine, simply copy the folder from the USB to any location (e.g., `~/PacketTracer`) or run directly from the USB mount point.
2. **Execution:**
   - Run:
     ```bash
     python3 ptgen.py -i your_lab.txt -o lab.pkt
     ```
3. **Open in Packet Tracer:**
   - Double-click the generated `.pkt` file or open it inside Cisco Packet Tracer:
     ```bash
     packettracer lab.pkt
     ```
   - All router interfaces will initialize with `no shutdown` and their assigned IPs.
   - Routing protocols (OSPF, RIP, Static) will converge automatically.
   - PCs will be pre-configured with IP addresses, subnet masks, and default gateways.
   - Run `ping <remote_pc_ip>` in any PC Command Prompt to verify end-to-end connectivity!

---

## File Structure

```text
PacketTracer/
├── ptgen.py             # Main CLI and interactive application
├── test_suite.py        # Automated test verification suite
├── README.md            # This documentation
├── templates/           # Clean Cisco Packet Tracer device templates
│   ├── base_canvas.xml  # Canvas and project metadata
│   ├── router_2911.xml  # Cisco 2911 Router template (3x GigabitEthernet)
│   ├── router_1841.xml  # Cisco 1841 Router template (2x FastEthernet)
│   ├── switch_2960.xml  # Cisco 2960 Switch template (24x FE, 2x GE)
│   └── pc_pt.xml        # Generic PC template (1x FE)
├── core/
│   ├── parser.py        # Natural text & shorthand grammar parser
│   ├── network_planner.py # VLSM subnetting, IP allocation & routing logic
│   ├── ios_config.py    # Cisco IOS configuration generator
│   ├── builder.py       # XML DOM scene assembler
│   └── crypto/          # Pure-Python Twofish-128 EAX + XOR + zlib codec
│       ├── pipeline.py
│       ├── twofish_py.py
│       ├── eax_py.py
│       ├── ctr_py.py
│       └── cmac_py.py
└── examples/
    ├── ospf_lab.txt     # Multi-router OSPF sample
    ├── rip_lab.txt      # Multi-router RIPv2 sample
    └── static_lab.txt   # Static routing sample
```
