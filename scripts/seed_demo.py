"""Carga datos SIMULADOS de demostracion. No usar IPs reales de produccion.
Las IPs usan rangos reservados para documentacion (RFC 5737)."""
from app.database import init_db, get_connection

DEMO_DEVICES = [
    ("SIM-CISCO-SW01",  "192.0.2.10",   "cisco",    "Catalyst 9300", "IOS XE 17.9", "Sala TIC - Rack A (SIMULADO)"),
    ("SIM-FORTI-FW01",  "192.0.2.20",   "fortinet", "FortiGate 100F", "FortiOS 7.4", "Sala TIC - Rack B (SIMULADO)"),
    ("SIM-HUAWEI-RT01", "198.51.100.30", "huawei",  "AR6120",        "VRP V200R021", "Sede alterna (SIMULADO)"),
]

if __name__ == "__main__":
    init_db()
    with get_connection() as conn:
        for d in DEMO_DEVICES:
            conn.execute(
                "INSERT OR IGNORE INTO devices "
                "(name, ip_address, vendor, model, os_version, location, is_simulated) "
                "VALUES (?,?,?,?,?,?,1)", d)
        conn.execute(
            "INSERT INTO audit_log (actor, action, details) VALUES (?,?,?)",
            ("system", "seed.demo", "Carga de datos simulados"))
    print("Datos simulados cargados.")