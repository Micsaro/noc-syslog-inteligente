"""Carga datos SIMULADOS de demostración. No usar IPs reales de producción.
Las IPs usan rangos reservados para documentación (RFC 5737)."""
from app.database import db_session, init_db

DEMO_DEVICES = [
    ("SIM-CISCO-SW01",  "192.0.2.10",   "cisco",    "Catalyst 9300", "IOS XE 17.9", "Sala TIC - Rack A (SIMULADO)"),
    ("SIM-FORTI-FW01",  "192.0.2.20",   "fortinet", "FortiGate 100F", "FortiOS 7.4", "Sala TIC - Rack B (SIMULADO)"),
    ("SIM-HUAWEI-RT01", "198.51.100.30", "huawei",  "AR6120",        "VRP V200R021", "Sede alterna (SIMULADO)"),
]

if __name__ == "__main__":
    init_db()
    with db_session() as conn:
        inserted = 0
        for d in DEMO_DEVICES:
            cur = conn.execute(
                "INSERT OR IGNORE INTO devices "
                "(name, ip_address, vendor, model, os_version, location, is_simulated) "
                "VALUES (?,?,?,?,?,?,1)", d)
            inserted += cur.rowcount
        if inserted:
            conn.execute(
                "INSERT INTO audit_log (actor, action, details) VALUES (?,?,?)",
                ("system", "seed.demo", f"Carga de datos simulados ({inserted} equipos)"))
    print(f"Equipos simulados insertados: {inserted}")