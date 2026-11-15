"""
Packet Tracer (.pkt) File Builder.
Assembles the complete Packet Tracer XML project and compiles it into a native .pkt file.
Synchronizes both Logical Canvas and Physical Workspace (Rack / Closet hierarchy)
to prevent 'Corrupted Physical Workspace' errors in Packet Tracer 8.x and 9.x.
"""

import copy
import os
import random
import uuid
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
from core.crypto.pipeline import Pkt_Pipeline
from core.network_planner import PlannedNetwork, InterfaceBinding
from core.ios_config import generate_router_ios_config, generate_switch_ios_config

# Fixed Physical Workspace Container GUIDs (from authentic Packet Tracer 8.2 / 9.0 projects)
GUID_INTERCITY = "{9e75f0b8-8845-418a-bc52-48a72c3551bf}"
GUID_CITY      = "{2efdd4e8-9d5d-4f94-8925-fe0347196b4d}"
GUID_OFFICE    = "{2a7b7dd1-4400-42a6-8d7f-4bc8146d63b3}"
GUID_CLOSET    = "{0ed77a98-ad46-4782-8daa-737b9f5fbb64}"
GUID_RACK      = "{c76ed4bd-583e-4c6c-957c-697ea608981a}"


class PacketTracerBuilder:
    def __init__(self, templates_dir: Optional[str] = None):
        if templates_dir is None:
            templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        self.templates_dir = templates_dir

        self.base_canvas_path = os.path.join(self.templates_dir, "base_canvas.xml")
        self.router_template_path = os.path.join(self.templates_dir, "router_2911.xml")
        self.switch_template_path = os.path.join(self.templates_dir, "switch_2960.xml")
        self.pc_template_path = os.path.join(self.templates_dir, "pc_pt.xml")

        self._pipeline = Pkt_Pipeline()

    def build_pkt(self, planned: PlannedNetwork, output_pkt_path: str):
        """Assembles the XML document and writes the compiled .pkt file."""
        xml_bytes = self.build_xml_bytes(planned)
        pkt_bytes = self._pipeline.compile(xml_bytes)
        os.makedirs(os.path.dirname(os.path.abspath(output_pkt_path)), exist_ok=True)
        with open(output_pkt_path, "wb") as f:
            f.write(pkt_bytes)
        return output_pkt_path

    def build_xml_bytes(self, planned: PlannedNetwork) -> bytes:
        """Assembles the XML tree for the planned network and returns UTF-8 XML bytes."""
        base_tree = ET.parse(self.base_canvas_path)
        root = base_tree.getroot()

        devices_node = root.find("NETWORK/DEVICES")
        links_node = root.find("NETWORK/LINKS")

        if devices_node is None:
            net = root.find("NETWORK")
            if net is None:
                net = ET.SubElement(root, "NETWORK")
            devices_node = ET.SubElement(net, "DEVICES")
        if links_node is None:
            net = root.find("NETWORK")
            links_node = ET.SubElement(net, "LINKS")

        pdd_dev = None
        for d in devices_node:
            name = d.find(".//ENGINE/NAME")
            if name is not None and "Power Distribution" in (name.text or ""):
                pdd_dev = d
                break

        devices_node.clear()
        links_node.clear()

        if pdd_dev is not None:
            devices_node.append(pdd_dev)

        # Physical Workspace containers
        pw = root.find("PHYSICALWORKSPACE")
        rack_children = pw.find('.//NODE[NAME="Rack"]/CHILDREN') if pw is not None else None
        office_children = pw.find('.//NODE[NAME="Corporate Office"]/CHILDREN') if pw is not None else None

        # Clear existing non-permanent devices from physical workspace
        if rack_children is not None:
            pdd = [c for c in rack_children if c.find("NAME") is not None and "Power Distribution" in (c.find("NAME").text or "")]
            rack_children.clear()
            if pdd:
                rack_children.append(pdd[0])

        if office_children is not None:
            closet = [c for c in office_children if c.find("NAME") is not None and c.find("NAME").text == "Main Wiring Closet"]
            office_children.clear()
            if closet:
                office_children.append(closet[0])

        # 1. Calculate visual coordinates
        coords = self._calculate_layout(planned)

        # 2. Track device unique IDs and GUIDs
        save_ids: Dict[str, str] = {}
        device_guids: Dict[str, str] = {}

        for dev_name in planned.devices:
            rand_id = random.randint(1000000000000000000, 18000000000000000000)
            save_ids[dev_name] = f"save-ref-id:{rand_id}"
            device_guids[dev_name] = f"{{{uuid.uuid4()}}}"

        # 3. Instantiate each device
        router_tmpl = ET.parse(self.router_template_path).getroot()
        switch_tmpl = ET.parse(self.switch_template_path).getroot()
        pc_tmpl = ET.parse(self.pc_template_path).getroot()

        rack_slot_idx = 1
        pc_idx = 0

        for dev_idx, (dev_name, dev_type) in enumerate(planned.devices.items(), start=1):
            x, y = coords[dev_name]
            save_id = save_ids[dev_name]
            dev_guid = device_guids[dev_name]

            if dev_type == "router":
                dev_elem = copy.deepcopy(router_tmpl)
                slot_x = 4 * rack_slot_idx
                rack_slot_idx += 1
                self._configure_router_element(dev_elem, dev_name, save_id, dev_guid, x, y, slot_x, dev_idx, planned)
                if rack_children is not None:
                    rack_children.append(self._create_physical_node(dev_name, dev_guid, slot_x, 0))

            elif dev_type == "switch":
                dev_elem = copy.deepcopy(switch_tmpl)
                slot_x = 4 * rack_slot_idx
                rack_slot_idx += 1
                self._configure_switch_element(dev_elem, dev_name, save_id, dev_guid, x, y, slot_x, dev_idx)
                if rack_children is not None:
                    rack_children.append(self._create_physical_node(dev_name, dev_guid, slot_x, 0))

            else:  # pc
                dev_elem = copy.deepcopy(pc_tmpl)
                pc_phys_x = 86 + 40 * pc_idx
                pc_idx += 1
                self._configure_pc_element(dev_elem, dev_name, save_id, dev_guid, x, y, pc_phys_x, 215, dev_idx, planned)
                if office_children is not None:
                    office_children.append(self._create_physical_node(dev_name, dev_guid, pc_phys_x, 215))

            devices_node.append(dev_elem)

        # 4. Instantiate each link
        for conn in planned.connections:
            link_elem = self._create_link_element(
                save_ids[conn["from_dev"]],
                conn["from_port"],
                save_ids[conn["to_dev"]],
                conn["to_port"],
                conn["link_type"]
            )
            links_node.append(link_elem)

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _calculate_layout(self, planned: PlannedNetwork) -> Dict[str, Tuple[float, float]]:
        """Calculates canvas coordinates (X, Y) for all devices."""
        coords: Dict[str, Tuple[float, float]] = {}

        routers = [d for d, t in planned.devices.items() if t == "router"]
        switches = [d for d, t in planned.devices.items() if t == "switch"]
        pcs = [d for d, t in planned.devices.items() if t == "pc"]

        num_routers = max(len(routers), 1)
        r_spacing = 250.0
        start_x = 180.0

        for i, r in enumerate(routers):
            coords[r] = (start_x + i * r_spacing, 260.0)

        sw_connections: Dict[str, List[str]] = {}
        for conn in planned.connections:
            u, v = conn["from_dev"], conn["to_dev"]
            if planned.devices[u] == "switch" and planned.devices[v] == "router":
                sw_connections.setdefault(u, []).append(v)
            elif planned.devices[v] == "switch" and planned.devices[u] == "router":
                sw_connections.setdefault(v, []).append(u)

        for i, sw in enumerate(switches):
            connected_routers = sw_connections.get(sw, [])
            if connected_routers:
                avg_x = sum(coords[r][0] for r in connected_routers) / len(connected_routers)
                sw_y = 130.0 if i % 2 == 0 else 390.0
                coords[sw] = (avg_x + (i % 2) * 30.0, sw_y)
            else:
                coords[sw] = (start_x + i * 200.0, 130.0)

        pc_parents: Dict[str, str] = {}
        for conn in planned.connections:
            u, v = conn["from_dev"], conn["to_dev"]
            if planned.devices[u] == "pc":
                pc_parents[u] = v
            elif planned.devices[v] == "pc":
                pc_parents[v] = u

        parent_pcs: Dict[str, List[str]] = {}
        for pc, parent in pc_parents.items():
            parent_pcs.setdefault(parent, []).append(pc)

        for parent, pc_list in parent_pcs.items():
            parent_x, parent_y = coords.get(parent, (300.0, 260.0))
            is_above = parent_y <= 260.0
            pc_y = parent_y - 100.0 if is_above else parent_y + 100.0
            num_pcs = len(pc_list)
            offset_start = -((num_pcs - 1) * 70.0) / 2.0

            for j, pc in enumerate(sorted(pc_list)):
                coords[pc] = (parent_x + offset_start + j * 70.0, pc_y)

        for i, pc in enumerate(pcs):
            if pc not in coords:
                coords[pc] = (100.0 + i * 80.0, 480.0)

        return coords

    def _set_physical_path(self, dev_elem: ET.Element, path: str):
        workspace = dev_elem.find("WORKSPACE")
        if workspace is None:
            workspace = ET.SubElement(dev_elem, "WORKSPACE")
        phys = workspace.find("PHYSICAL")
        if phys is None:
            phys = ET.SubElement(workspace, "PHYSICAL")
        phys.text = path

    def _set_physical_cpur(self, dev_elem: ET.Element, parent_path: str, container_id: str, x: int, y: int, x_pn: str = "0.154", y_pn: str = "0.11675"):
        workspace = dev_elem.find("WORKSPACE")
        if workspace is None:
            workspace = ET.SubElement(dev_elem, "WORKSPACE")
        cpur = workspace.find("PHYSICAL_CPUR")
        if cpur is None:
            cpur = ET.SubElement(workspace, "PHYSICAL_CPUR")
        
        tags_values = [
            ("X_PN", x_pn),
            ("Y_PN", y_pn),
            ("X", str(x)),
            ("Y", str(y)),
            ("SLOT", "0"),
            ("SUBSLOT", "0"),
            ("PARENT_PATH", parent_path),
            ("CONTAINER_ID", container_id),
        ]
        for tag, val in tags_values:
            el = cpur.find(tag)
            if el is None:
                el = ET.SubElement(cpur, tag)
            el.text = val

    def _configure_router_element(self, dev_elem: ET.Element, name: str, save_id: str, guid: str, x: float, y: float, slot_x: int, dev_idx: int, planned: PlannedNetwork):
        name_elem = dev_elem.find(".//ENGINE/NAME")
        if name_elem is not None:
            name_elem.text = name

        save_elem = dev_elem.find(".//ENGINE/SAVE_REF_ID")
        if save_elem is None:
            engine = dev_elem.find("ENGINE")
            if engine is not None:
                save_elem = ET.SubElement(engine, "SAVE_REF_ID")
        if save_elem is not None:
            save_elem.text = save_id

        # Logical Coordinates
        logical_x = dev_elem.find(".//WORKSPACE/LOGICAL/X")
        logical_y = dev_elem.find(".//WORKSPACE/LOGICAL/Y")
        if logical_x is not None:
            logical_x.text = str(x)
        if logical_y is not None:
            logical_y.text = str(y)

        # Synchronize Physical Workspace references
        self._set_physical_path(dev_elem, f"{GUID_INTERCITY},{GUID_CITY},{GUID_OFFICE},{GUID_CLOSET},{GUID_RACK},{guid}")
        self._set_physical_cpur(dev_elem, f"{GUID_INTERCITY},{GUID_CITY},{GUID_OFFICE},{GUID_CLOSET}", GUID_RACK, slot_x, 0, x_pn="0.154", y_pn="0.11675")

        # Hardware Port Configuration
        port_map = {
            "GigabitEthernet0/0": 0,
            "GigabitEthernet0/1": 1,
            "GigabitEthernet0/2": 2,
        }
        ports = dev_elem.findall(".//PORT")
        iface_by_port = {iface.port: iface for iface in planned.router_interfaces.get(name, [])}

        for p_name, p_idx in port_map.items():
            if p_idx < len(ports):
                port_elem = ports[p_idx]
                mac_str = f"0060.2F{dev_idx:02X}.0{p_idx+1:03X}"
                mac_elem = port_elem.find("MACADDRESS")
                if mac_elem is not None:
                    mac_elem.text = mac_str
                bia_elem = port_elem.find("BIA")
                if bia_elem is not None:
                    bia_elem.text = mac_str

                if p_name in iface_by_port:
                    iface = iface_by_port[p_name]
                    # Power on the port and bind IP/Subnet in simulation engine
                    p_power = port_elem.find("POWER")
                    if p_power is not None:
                        p_power.text = "true"

                    up_elem = port_elem.find("UP_METHOD")
                    if up_elem is None:
                        up_elem = ET.SubElement(port_elem, "UP_METHOD")
                    up_elem.text = "3"

                    p_ip = port_elem.find("IP")
                    if p_ip is None:
                        p_ip = ET.SubElement(port_elem, "IP")
                    p_ip.text = iface.ip

                    p_sub = port_elem.find("SUBNET")
                    if p_sub is None:
                        p_sub = ET.SubElement(port_elem, "SUBNET")
                    p_sub.text = iface.mask

                    full_dup = port_elem.find("FULLDUPLEX")
                    if full_dup is not None:
                        full_dup.text = "true"

                    speed_elem = port_elem.find("SPEED")
                    if speed_elem is None:
                        speed_elem = ET.SubElement(port_elem, "SPEED")
                    speed_elem.text = "1000"

                    ipv6_ll = port_elem.find("IPV6_DEFAULT_LINK_LOCAL")
                    if ipv6_ll is not None:
                        ipv6_ll.text = f"FE80::260:2FFF:FE{dev_idx:02X}:{p_idx+1:04X}"
                else:
                    p_power = port_elem.find("POWER")
                    if p_power is not None:
                        p_power.text = "false"
                    up_elem = port_elem.find("UP_METHOD")
                    if up_elem is None:
                        up_elem = ET.SubElement(port_elem, "UP_METHOD")
                    up_elem.text = "5"

        # Cisco IOS running-config
        ios_lines = generate_router_ios_config(name, planned)
        rc_elem = dev_elem.find(".//ENGINE/RUNNINGCONFIG")
        if rc_elem is not None:
            rc_elem.clear()
            for line in ios_lines:
                line_elem = ET.SubElement(rc_elem, "LINE")
                line_elem.text = line

        sc_elem = dev_elem.find(".//ENGINE/STARTUPCONFIG")
        if sc_elem is not None:
            sc_elem.clear()
            for line in ios_lines:
                line_elem = ET.SubElement(sc_elem, "LINE")
                line_elem.text = line

    def _configure_switch_element(self, dev_elem: ET.Element, name: str, save_id: str, guid: str, x: float, y: float, slot_x: int, dev_idx: int):
        name_elem = dev_elem.find(".//ENGINE/NAME")
        if name_elem is not None:
            name_elem.text = name

        save_elem = dev_elem.find(".//ENGINE/SAVE_REF_ID")
        if save_elem is not None:
            save_elem.text = save_id

        logical_x = dev_elem.find(".//WORKSPACE/LOGICAL/X")
        logical_y = dev_elem.find(".//WORKSPACE/LOGICAL/Y")
        if logical_x is not None:
            logical_x.text = str(x)
        if logical_y is not None:
            logical_y.text = str(y)

        # Synchronize Physical Workspace references
        self._set_physical_path(dev_elem, f"{GUID_INTERCITY},{GUID_CITY},{GUID_OFFICE},{GUID_CLOSET},{GUID_RACK},{guid}")
        self._set_physical_cpur(dev_elem, f"{GUID_INTERCITY},{GUID_CITY},{GUID_OFFICE},{GUID_CLOSET}", GUID_RACK, slot_x, 0, x_pn="0.03225", y_pn="0.0355")

        # Unique MAC addresses for switch ports
        for s_idx, port_elem in enumerate(dev_elem.findall(".//PORT")):
            mac_str = f"000A.41{dev_idx:02X}.{s_idx+1:04X}"
            mac_elem = port_elem.find("MACADDRESS")
            if mac_elem is not None:
                mac_elem.text = mac_str
            bia_elem = port_elem.find("BIA")
            if bia_elem is not None:
                bia_elem.text = mac_str

        ios_lines = generate_switch_ios_config(name)
        rc_elem = dev_elem.find(".//ENGINE/RUNNINGCONFIG")
        if rc_elem is not None:
            rc_elem.clear()
            for line in ios_lines:
                line_elem = ET.SubElement(rc_elem, "LINE")
                line_elem.text = line

    def _configure_pc_element(self, dev_elem: ET.Element, name: str, save_id: str, guid: str, x: float, y: float, phys_x: int, phys_y: int, dev_idx: int, planned: PlannedNetwork):
        name_elem = dev_elem.find(".//ENGINE/NAME")
        if name_elem is not None:
            name_elem.text = name

        save_elem = dev_elem.find(".//ENGINE/SAVE_REF_ID")
        if save_elem is not None:
            save_elem.text = save_id

        logical_x = dev_elem.find(".//WORKSPACE/LOGICAL/X")
        logical_y = dev_elem.find(".//WORKSPACE/LOGICAL/Y")
        if logical_x is not None:
            logical_x.text = str(x)
        if logical_y is not None:
            logical_y.text = str(y)

        # Synchronize Physical Workspace references
        self._set_physical_path(dev_elem, f"{GUID_INTERCITY},{GUID_CITY},{GUID_OFFICE},{guid}")
        self._set_physical_cpur(dev_elem, f"{GUID_INTERCITY},{GUID_CITY},{GUID_OFFICE}", GUID_OFFICE, phys_x, phys_y, x_pn="0.024971", y_pn="0.100561")

        # Hardware Port Configuration
        ports = dev_elem.findall(".//PORT")
        if ports:
            port0 = ports[0]
            mac_str = f"0030.F2{dev_idx:02X}.0001"
            mac_elem = port0.find("MACADDRESS")
            if mac_elem is not None:
                mac_elem.text = mac_str
            bia_elem = port0.find("BIA")
            if bia_elem is not None:
                bia_elem.text = mac_str

            p_power = port0.find("POWER")
            if p_power is not None:
                p_power.text = "true"

            up_elem = port0.find("UP_METHOD")
            if up_elem is None:
                up_elem = ET.SubElement(port0, "UP_METHOD")
            up_elem.text = "5"

            full_dup = port0.find("FULLDUPLEX")
            if full_dup is not None:
                full_dup.text = "true"

            iface = planned.pc_interfaces.get(name)
            if iface:
                ip_elem = port0.find("IP")
                if ip_elem is None:
                    ip_elem = ET.SubElement(port0, "IP")
                ip_elem.text = iface.ip

                sub_elem = port0.find("SUBNET")
                if sub_elem is None:
                    sub_elem = ET.SubElement(port0, "SUBNET")
                sub_elem.text = iface.mask

                gw_elem = port0.find("PORT_GATEWAY")
                if gw_elem is None:
                    gw_elem = ET.SubElement(port0, "PORT_GATEWAY")
                gw_elem.text = iface.gateway

                dhcp_elem = port0.find("PORT_DHCP_ENABLE")
                if dhcp_elem is None:
                    dhcp_elem = ET.SubElement(port0, "PORT_DHCP_ENABLE")
                dhcp_elem.text = "false"

                gw_engine = dev_elem.find(".//ENGINE/GATEWAY")
                if gw_engine is None:
                    engine_node = dev_elem.find("ENGINE")
                    if engine_node is not None:
                        gw_engine = ET.SubElement(engine_node, "GATEWAY")
                if gw_engine is not None:
                    gw_engine.text = iface.gateway

                ipv6_ll = port0.find("IPV6_DEFAULT_LINK_LOCAL")
                if ipv6_ll is not None:
                    ipv6_ll.text = f"FE80::230:F2FF:FE{dev_idx:02X}:0001"

        if len(ports) > 1:
            port1 = ports[1]
            mac_str_bt = f"0060.5C{dev_idx:02X}.0002"
            mac_elem = port1.find("MACADDRESS")
            if mac_elem is not None:
                mac_elem.text = mac_str_bt
            bia_elem = port1.find("BIA")
            if bia_elem is not None:
                bia_elem.text = mac_str_bt

    def _create_physical_node(self, name: str, guid: str, x: int, y: int) -> ET.Element:
        """Constructs a valid <NODE> inside the Physical Workspace hierarchy."""
        node = ET.Element("NODE")
        ET.SubElement(node, "X").text = str(x)
        ET.SubElement(node, "Y").text = str(y)
        ET.SubElement(node, "TYPE").text = "6"
        name_elem = ET.SubElement(node, "NAME")
        name_elem.text = name
        name_elem.attrib["translate"] = "true"

        ET.SubElement(node, "SX").text = "0.2"
        ET.SubElement(node, "SY").text = "0.2"
        ET.SubElement(node, "W").text = "20"
        ET.SubElement(node, "H").text = "20"
        ET.SubElement(node, "D").text = "0"

        path_elem = ET.SubElement(node, "PATH")
        path_elem.text = "../art/Background/grid_100x100.png"
        path_elem.attrib["isanim"] = "false"

        ET.SubElement(node, "CHILDREN")
        ET.SubElement(node, "MANUAL_SCALING").text = "false"
        ET.SubElement(node, "SCALED_PIXMAP_WIDTH").text = "0"
        ET.SubElement(node, "SCALED_PIXMAP_HEIGHT").text = "0"
        ET.SubElement(node, "INIT_WIDTH").text = "20"
        ET.SubElement(node, "INIT_HEIGHT").text = "20"
        ET.SubElement(node, "INIT_DEPTH").text = "0"
        ET.SubElement(node, "INIT_SX").text = "0.2"
        ET.SubElement(node, "INIT_SY").text = "0.2"
        ET.SubElement(node, "INIT_SZ").text = "0.2"
        ET.SubElement(node, "BG_TILED").text = "false"
        ET.SubElement(node, "CUSTOM_IMAGE_WIDTH").text = "-1"
        ET.SubElement(node, "CUSTOM_IMAGE_HEIGHT").text = "-1"
        ET.SubElement(node, "SCALE_FACTOR").text = "1"
        ET.SubElement(node, "UUID_STR").text = guid
        ET.SubElement(node, "SLOT").text = "0"
        ET.SubElement(node, "SUB_SLOT").text = "0"

        return node

    def _create_link_element(self, from_save_id: str, from_port: str, to_save_id: str, to_port: str, link_type: str) -> ET.Element:
        """Constructs a valid <LINK> element."""
        link = ET.Element("LINK")
        ET.SubElement(link, "TYPE").text = "eCopper"

        cable = ET.SubElement(link, "CABLE")
        ET.SubElement(cable, "LENGTH").text = "1"
        ET.SubElement(cable, "FUNCTIONAL").text = "true"
        ET.SubElement(cable, "FROM").text = from_save_id
        ET.SubElement(cable, "PORT").text = from_port
        ET.SubElement(cable, "TO").text = to_save_id
        ET.SubElement(cable, "PORT").text = to_port
        ET.SubElement(cable, "TYPE").text = link_type

        return link
