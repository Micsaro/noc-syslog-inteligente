"""Consola simulada de SOLO LECTURA: conexión, ejecución, puertos, macros y política.
Toda acción (permitida o bloqueada) queda en audit_log."""
import json
import sqlite3
from typing import Annotated, Optional
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints
from app.audit import write_audit
from app.command_policy import MAX_COMMAND_LEN, evaluate, policy_summary, presets_for
from app.console_sim import NEEDS_EVENTS, run_simulated
from app.database import db_session
from app.schemas import Vendor
from app.syslog_parser import sanitize

router = APIRouter(prefix="/api/console", tags=["Consola"])

PROMPTS = {"cisco": "{name}#", "fortinet": "{name} #", "huawei": "<{name}>", "other": "{name}>"}
BAUDRATE = 9600   # parámetro estándar de consola: 9600 8N1
Cmd = Annotated[str, StringConstraints(max_length=300)]


class ConnectIn(BaseModel):
    device_id: int
    port: Optional[str] = Field(default=None, max_length=40)


class ExecIn(BaseModel):
    device_id: int
    command: Cmd


class RunIn(BaseModel):
    device_id: int


class MacroIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9 _.-]{3,40}$")
    vendor: Vendor
    commands: list[Cmd] = Field(min_length=1, max_length=10)


def _detect_ports() -> dict:
    """Lista los puertos serie del equipo donde corre el servidor. NO abre ningún puerto."""
    ports, has_lib = [], True
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            ports.append({"device": sanitize(p.device, 40),
                          "description": sanitize(p.description or "puerto serie", 80),
                          "usb": p.vid is not None, "simulated": False})
    except ImportError:
        has_lib = False
    except Exception:       # fallo del sistema al enumerar: se ignora y se ofrece el simulado
        pass
    ports.append({"device": "SIM1", "description": "Puerto simulado (sin hardware)",
                  "usb": False, "simulated": True})
    real = [p for p in ports if not p["simulated"]]
    usb = [p for p in real if p["usb"]]
    useful = [p for p in real if "bluetooth" not in p["description"].lower()]
    fallback = [p for p in ports if p["simulated"]]
    return {"ports": ports, "recommended": (usb or useful or fallback)[0]["device"],
            "pyserial": has_lib}


def _device(conn: sqlite3.Connection, device_id: int) -> sqlite3.Row:
    dev = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if dev is None:
        raise HTTPException(404, "Equipo no encontrado")
    if dev["status"] == "inactive":
        raise HTTPException(409, "El equipo está inactivo")
    return dev


def _prompt(dev: sqlite3.Row) -> str:
    return PROMPTS.get(dev["vendor"], PROMPTS["other"]).format(name=dev["name"])


def _execute(conn, dev, command: str, actor: str, macro: Optional[str] = None) -> dict:
    """Evalúa, simula y audita UN comando. Lo usan la consola y las macros por igual."""
    d = evaluate(dev["vendor"], command)
    extra = {"macro": macro} if macro else {}
    if not d.allowed:
        shown = sanitize(command, MAX_COMMAND_LEN)
        write_audit(conn, actor, "console.blocked", "devices", dev["id"],
                    {"command": shown, "categoria": d.category, "razon": d.reason, **extra})
        return {"command": shown, "allowed": False, "category": d.category,
                "reason": d.reason, "output": "", "prompt": _prompt(dev)}
    events = []
    if d.canon.lower() in NEEDS_EVENTS:
        events = conn.execute(
            "SELECT message, received_at FROM syslog_events WHERE device_id = ? "
            "ORDER BY id DESC LIMIT 8", (dev["id"],)).fetchall()
    output = run_simulated(dev["vendor"], dev, d, events)
    write_audit(conn, actor, "console.command", "devices", dev["id"], {"command": d.command, **extra})
    return {"command": d.command, "allowed": True, "category": d.category,
            "reason": d.reason, "output": output, "prompt": _prompt(dev)}


@router.get("/ports")
def ports():
    return _detect_ports()


@router.post("/connect")
def connect(body: ConnectIn, x_actor: str = Header(default="anonymous")):
    info = _detect_ports()
    port = body.port or info["recommended"]
    if port not in {p["device"] for p in info["ports"]}:
        raise HTTPException(422, "El puerto indicado no fue detectado")
    with db_session() as conn:
        dev = _device(conn, body.device_id)
        write_audit(conn, x_actor, "console.connect", "devices", dev["id"],
                    {"puerto": port, "modo": "simulado-solo-lectura"})
    return {
        "device": {"id": dev["id"], "name": dev["name"], "vendor": dev["vendor"],
                   "ip_address": dev["ip_address"], "model": dev["model"]},
        "prompt": _prompt(dev), "port": port, "baudrate": BAUDRATE,
        "mode": "simulado-solo-lectura",
        "presets": presets_for(dev["vendor"]),
        "policy": policy_summary(dev["vendor"]),
        "banner": [
            "[SIMULADO] Sesión de consola de solo lectura. No hay conexión con equipos reales.",
            f"Equipo: {dev['name']} ({dev['ip_address']}) · {dev['vendor']} {dev['model'] or ''}".strip(),
            f"Puerto: {port} · {BAUDRATE} 8N1 (detectado automáticamente, sin configuración manual)",
            "Escribe 'help' para ver los comandos permitidos. Los bloqueados quedan en la auditoría.",
        ],
    }


@router.post("/exec")
def exec_command(body: ExecIn, x_actor: str = Header(default="anonymous")):
    with db_session() as conn:
        dev = _device(conn, body.device_id)
        return _execute(conn, dev, body.command, x_actor)


@router.get("/policy/{vendor}")
def policy(vendor: Vendor):
    return policy_summary(vendor)


# ---------------- Macros ----------------
def _macro_out(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "vendor": r["vendor"],
            "commands": json.loads(r["commands"]), "created_by": r["created_by"],
            "created_at": r["created_at"]}


@router.get("/macros")
def list_macros(vendor: Optional[Vendor] = None):
    sql, params = "SELECT * FROM console_macros", []
    if vendor:
        sql += " WHERE vendor = ?"
        params.append(vendor)
    with db_session() as conn:
        rows = conn.execute(sql + " ORDER BY name", params).fetchall()
    return [_macro_out(r) for r in rows]


@router.post("/macros", status_code=201)
def create_macro(body: MacroIn, x_actor: str = Header(default="anonymous")):
    cleaned, errors = [], []
    for i, raw in enumerate(body.commands, 1):
        if not raw.strip():
            continue
        d = evaluate(body.vendor, raw)
        if d.allowed:
            cleaned.append(d.command)
        else:
            errors.append(f"Línea {i} ('{sanitize(raw, 40)}'): {d.reason}")
    if errors:
        raise HTTPException(422, "; ".join(errors))
    if not cleaned:
        raise HTTPException(422, "La macro no tiene comandos")
    with db_session() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO console_macros (name, vendor, commands, created_by) VALUES (?,?,?,?)",
                (body.name.strip(), body.vendor, json.dumps(cleaned), sanitize(x_actor, 64)))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Ya existe una macro con ese nombre para ese fabricante")
        write_audit(conn, x_actor, "console.macro_create", "console_macros", cur.lastrowid,
                    {"name": body.name.strip(), "vendor": body.vendor, "commands": cleaned})
        return _macro_out(conn.execute("SELECT * FROM console_macros WHERE id = ?",
                                       (cur.lastrowid,)).fetchone())


@router.delete("/macros/{macro_id}", status_code=204)
def delete_macro(macro_id: int, x_actor: str = Header(default="anonymous")):
    with db_session() as conn:
        m = conn.execute("SELECT * FROM console_macros WHERE id = ?", (macro_id,)).fetchone()
        if m is None:
            raise HTTPException(404, "Macro no encontrada")
        conn.execute("DELETE FROM console_macros WHERE id = ?", (macro_id,))
        write_audit(conn, x_actor, "console.macro_delete", "console_macros", macro_id,
                    {"name": m["name"], "vendor": m["vendor"]})
    return Response(status_code=204)


@router.post("/macros/{macro_id}/run")
def run_macro(macro_id: int, body: RunIn, x_actor: str = Header(default="anonymous")):
    """Ejecuta la macro comando por comando; CADA uno se vuelve a validar y se detiene al primer bloqueo."""
    with db_session() as conn:
        m = conn.execute("SELECT * FROM console_macros WHERE id = ?", (macro_id,)).fetchone()
        if m is None:
            raise HTTPException(404, "Macro no encontrada")
        dev = _device(conn, body.device_id)
        if m["vendor"] != dev["vendor"]:
            raise HTTPException(409, f"La macro es de {m['vendor']} y el equipo es {dev['vendor']}")
        results = []
        for command in json.loads(m["commands"]):
            res = _execute(conn, dev, command, x_actor, macro=m["name"])
            results.append(res)
            if not res["allowed"]:
                break
        write_audit(conn, x_actor, "console.macro_run", "devices", dev["id"],
                    {"macro": m["name"], "ejecutados": len(results)})
    return {"macro": m["name"], "results": results}