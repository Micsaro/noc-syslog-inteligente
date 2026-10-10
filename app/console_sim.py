"""Salidas SIMULADAS de comandos de lectura. No hay conexión con equipos reales."""
from datetime import datetime, timezone

NEEDS_EVENTS = {"show logging", "display logbuffer"}   # comandos que muestran logs del equipo


def _dt(received_at) -> datetime:
    try:
        return datetime.strptime(received_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _cisco_logs(c) -> str:
    lines = [f"*{_dt(e['received_at']):%b %d %H:%M:%S}: {e['message']}" for e in reversed(c["events"])]
    return "\n".join(lines) or "(sin mensajes registrados para este equipo)"


def _huawei_logs(c) -> str:
    lines = [f"{_dt(e['received_at']):%b %d %Y %H:%M:%S} {c['name']} {e['message']}"
             for e in reversed(c["events"])]
    return "\n".join(lines) or "(sin mensajes registrados para este equipo)"


OUTPUTS = {
    # ---------------- Cisco IOS XE ----------------
    ("cisco", "show version"): lambda c: (
        f"Cisco IOS XE Software, Version {c['ver']}\n"
        f"Cisco {c['model']} (plataforma simulada)\n"
        f"{c['name']} uptime is 12 days, 4 hours, 31 minutes\n"
        'System image file is "flash:packages.conf"\n'
        "Last reload reason: Reload Command"),
    ("cisco", "show ip interface brief"): lambda c: (
        "Interface              IP-Address      OK? Method Status                Protocol\n"
        f"Vlan1                  {c['ip']:<15} YES manual up                    up\n"
        "GigabitEthernet1/0/1   unassigned      YES unset  up                    up\n"
        "GigabitEthernet1/0/2   unassigned      YES unset  up                    up\n"
        "GigabitEthernet1/0/3   unassigned      YES unset  down                  down\n"
        "GigabitEthernet1/0/4   unassigned      YES unset  administratively down down"),
    ("cisco", "show interfaces status"): lambda c: (
        "Port      Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi1/0/1   Uplink-SIM         connected    trunk      a-full  a-1000 10/100/1000BaseTX\n"
        "Gi1/0/2   Servidor-SIM       connected    10         a-full  a-1000 10/100/1000BaseTX\n"
        "Gi1/0/3                      notconnect   1          auto    auto   10/100/1000BaseTX\n"
        "Gi1/0/4                      disabled     1          auto    auto   10/100/1000BaseTX"),
    ("cisco", "show vlan brief"): lambda c: (
        "VLAN Name                             Status    Ports\n"
        "---- -------------------------------- --------- ---------------\n"
        "1    default                          active    Gi1/0/3, Gi1/0/4\n"
        "10   SERVIDORES-SIM                   active    Gi1/0/2\n"
        "20   USUARIOS-SIM                     active"),
    ("cisco", "show logging"): lambda c: (
        "Syslog logging: enabled (0 messages dropped)\n"
        "    Console logging: level debugging\n"
        "    Buffer logging: level informational\n\n"
        "Log Buffer (16384 bytes):\n" + _cisco_logs(c)),
    ("cisco", "show clock"): lambda c: f"*{c['now']:%H:%M:%S}.000 UTC {c['now']:%a %b %d %Y}",
    ("cisco", "show inventory"): lambda c: (
        f'NAME: "Switch 1", DESCR: "{c["model"]}"\n'
        f"PID: {c['model']}, VID: V01, SN: SIM000000001"),
    ("cisco", "show processes cpu"): lambda c: (
        "CPU utilization for five seconds: 7%/1%; one minute: 6%; five minutes: 5%\n"
        " PID Runtime(ms)     Invoked      uSecs   5Sec   1Min   5Min TTY Process\n"
        "   1           0           1          0  0.00%  0.00%  0.00%   0 Chunk Manager"),
    ("cisco", "show cdp neighbors"): lambda c: (
        "Capability Codes: R - Router, S - Switch\n"
        "Device ID        Local Intrfce  Holdtme  Capability  Platform   Port ID\n"
        "SIM-CISCO-SW02   Gig 1/0/48     150      S           C9200      Gig 1/0/48"),
    ("cisco", "show running-config"): lambda c: (
        "Building configuration... (SIMULADO)\n!\nversion 17.9\nservice password-encryption\n!\n"
        f"hostname {c['name']}\n!\nenable secret 9 <OCULTO>\n!\ninterface Vlan1\n"
        f" ip address {c['ip']} 255.255.255.0\n!\nline vty 0 15\n transport input ssh\n!\nend"),
    ("cisco", "show interfaces <if>"): lambda c: (
        f"{c['arg']} is up, line protocol is up (connected)\n"
        "  Hardware is Gigabit Ethernet (simulado)\n"
        "  MTU 1500 bytes, BW 1000000 Kbit/sec\n"
        "  5 minute input rate 1000 bits/sec, 2 packets/sec\n"
        "  0 input errors, 0 CRC, 0 output errors"),

    # ---------------- Fortinet FortiOS ----------------
    ("fortinet", "get system status"): lambda c: (
        f"Version: {c['model']} {c['ver']}\nSerial-Number: SIMFW00000001\n"
        f"Hostname: {c['name']}\nOperation Mode: NAT\nCurrent HA mode: standalone\n"
        f"System time: {c['now']:%a %b %d %H:%M:%S %Y}"),
    ("fortinet", "get system performance status"): lambda c: (
        "CPU states: 3% user 2% system 0% nice 95% idle\n"
        "Memory: 8049680k total, 3411036k used (42.4%), 4638644k free\n"
        "Average network usage: 12345 / 12011 kbps in 1 minute\n"
        "Uptime: 12 days, 4 hours, 31 minutes"),
    ("fortinet", "get system interface physical"): lambda c: (
        f"== [port1]\n    mode: static ip: {c['ip']} 255.255.255.0 status: up\n"
        "== [port2]\n    mode: static ip: 198.51.100.1 255.255.255.0 status: up\n"
        "== [port3]\n    mode: static ip: 0.0.0.0 0.0.0.0 status: down"),
    ("fortinet", "get router info routing-table all"): lambda c: (
        "Codes: K - kernel, C - connected, S - static, R - RIP, B - BGP, O - OSPF\n"
        "S*      0.0.0.0/0 [10/0] via 198.51.100.254, port2\n"
        "C       192.0.2.0/24 is directly connected, port1\n"
        "C       198.51.100.0/24 is directly connected, port2"),
    ("fortinet", "get system ha status"): lambda c: (
        "HA Health Status: not configured\nModel: " + c["model"] + "\nMode: Standalone"),
    ("fortinet", "get system arp"): lambda c: (
        "Address           Age(min)   Hardware Addr      Interface\n"
        "192.0.2.10        1          00:00:5e:00:53:10  port1"),
    ("fortinet", "diagnose sys session stat"): lambda c: (
        "misc info:       session_count=1523 setup_rate=3 exp_count=0 clash=0"),

    # ---------------- Huawei VRP ----------------
    ("huawei", "display version"): lambda c: (
        "Huawei Versatile Routing Platform Software\n"
        f"VRP (R) software, Version {c['ver']}\n"
        f"HUAWEI {c['model']} (simulado) uptime is 12 days, 4 hours, 31 minutes"),
    ("huawei", "display ip interface brief"): lambda c: (
        "Interface                   IP Address/Mask      Physical   Protocol\n"
        f"GigabitEthernet0/0/1        {c['ip']}/24    up         up\n"
        "GigabitEthernet0/0/2        unassigned           down       down\n"
        "NULL0                       unassigned           up         up(s)"),
    ("huawei", "display interface brief"): lambda c: (
        "PHY: Physical\n*down: administratively down\n"
        "Interface                   PHY     Protocol InUti OutUti   inErrors  outErrors\n"
        "GE0/0/1                     up      up       0.01%  0.01%          0          0\n"
        "GE0/0/2                     down    down        0%     0%          0          0"),
    ("huawei", "display ip routing-table"): lambda c: (
        "Route Flags: R - relay, D - download to fib\n"
        "Destination/Mask    Proto   Pre  Cost   Flags NextHop         Interface\n"
        "0.0.0.0/0           Static  60   0      RD    198.51.100.254  GigabitEthernet0/0/1\n"
        "198.51.100.0/24     Direct  0    0      D     198.51.100.30   GigabitEthernet0/0/1"),
    ("huawei", "display logbuffer"): lambda c: (
        "Logging buffer configuration and contents: enabled\n"
        "Channel number: 4, Channel name: logbuffer\nDropped messages: 0\n\n" + _huawei_logs(c)),
    ("huawei", "display clock"): lambda c: (
        f"{c['now']:%Y-%m-%d %H:%M:%S}+00:00\n{c['now']:%A}\nTime Zone(UTC) : UTC+00:00"),
    ("huawei", "display cpu-usage"): lambda c: "CPU Usage Stat. Cycle: 60 (Second)\nCPU Usage            : 5% Max: 12%",
    ("huawei", "display memory-usage"): lambda c: "Memory Using Percentage Is: 38%",
    ("huawei", "display device"): lambda c: (
        f"{c['name']}'s Device status:\n"
        "Slot  Sub  Type        Online   Power    Register     Alarm   Primary\n"
        f"-     -    {c['model']:<11} Present  PowerOn  Registered   Normal  NA"),
    ("huawei", "display current-configuration"): lambda c: (
        f"#\nsysname {c['name']}\n#\naaa\n local-user admin password irreversible-cipher <OCULTO>\n#\n"
        f"interface GigabitEthernet0/0/1\n ip address {c['ip']} 255.255.255.0\n#\nreturn"),
    ("huawei", "display interface <if>"): lambda c: (
        f"{c['arg']} current state : UP\nLine protocol current state : UP\n"
        "Maximum Transmit Unit : 1500\nInput:  0 input errors\nOutput: 0 output errors"),
}


def apply_filter(text: str, flt: str) -> str:
    """Filtros simples por subcadena (sin expresiones regulares, para evitar ReDoS)."""
    mode, arg = flt.split(None, 1)
    mode, arg = mode.lower(), arg.lower()
    lines = text.splitlines()
    if mode in ("include", "grep", "section"):
        keep = [ln for ln in lines if arg in ln.lower()]
    elif mode == "exclude":
        keep = [ln for ln in lines if arg not in ln.lower()]
    elif mode == "begin":
        i = next((i for i, ln in enumerate(lines) if arg in ln.lower()), None)
        keep = lines[i:] if i is not None else []
    else:  # count
        return f"Number of lines which match = {sum(1 for ln in lines if arg in ln.lower())}"
    return "\n".join(keep)


def run_simulated(vendor: str, device, decision, events) -> str:
    fn = OUTPUTS.get((vendor, decision.canon.lower()))
    if fn is None:
        return "(sin salida simulada para este comando)"
    ctx = {
        "name": device["name"], "ip": device["ip_address"],
        "model": device["model"] or "equipo simulado", "ver": device["os_version"] or "desconocida",
        "arg": decision.arg, "events": events, "now": datetime.now(timezone.utc),
    }
    out = fn(ctx)
    if decision.flt:
        out = apply_filter(out, decision.flt) or "(sin coincidencias)"
    return out