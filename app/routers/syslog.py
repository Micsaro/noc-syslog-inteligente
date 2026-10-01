"""Entrada de mensajes: importación individual y modo simulación."""
import random
from collections import Counter
from ipaddress import ip_address
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from app.audit import write_audit
from app.config import MAX_RAW_CHARS
from app.database import db_session
from app.ingest import ingest_message
from app.simulator import build_hostile, build_raw

router = APIRouter(prefix="/api/syslog", tags=["Syslog"])


class SyslogIngestIn(BaseModel):
    raw: str = Field(min_length=1, max_length=MAX_RAW_CHARS)
    source_ip: Optional[str] = None
    is_simulated: bool = True   # por defecto todo se marca como simulado

    @field_validator("source_ip")
    @classmethod
    def _ip(cls, v):
        if v is not None:
            try:
                ip_address(v)
            except ValueError:
                raise ValueError("Dirección IP inválida")
        return v


@router.post("/ingest")
def ingest(msg: SyslogIngestIn, x_actor: str = Header(default="anonymous")):
    """Importa UN mensaje Syslog en crudo (por ejemplo: <187>Oct  1 20:50:00 host mensaje)."""
    return ingest_message(msg.raw, source_ip=msg.source_ip,
                          is_simulated=msg.is_simulated, actor=x_actor)


@router.post("/simulate")
def simulate(
    count: int = Query(20, ge=1, le=200),
    storm: bool = Query(False, description="Repite UN mismo mensaje 'count' veces (tormenta)"),
    include_hostile: bool = Query(True, description="Agrega 1 mensaje hostil de prueba"),
    x_actor: str = Header(default="anonymous"),
):
    """Modo simulación: genera mensajes por fabricante usando los equipos del inventario."""
    with db_session() as conn:
        devices = conn.execute(
            "SELECT name, ip_address, vendor FROM devices WHERE status != 'inactive'").fetchall()
    if not devices:
        raise HTTPException(400, "Inventario vacío. Ejecuta: python -m scripts.seed_demo")

    summary: Counter = Counter()

    def send(dev, raw: str) -> None:
        res = ingest_message(raw, source_ip=dev["ip_address"], is_simulated=True, actor=x_actor)
        summary[res["status"]] += 1

    if storm:
        dev = random.choice(devices)
        raw = build_raw(dev["vendor"], dev["name"])
        for _ in range(count):
            send(dev, raw)
    else:
        for _ in range(count):
            dev = random.choice(devices)
            send(dev, build_raw(dev["vendor"], dev["name"]))

    if include_hostile:
        dev = random.choice(devices)
        send(dev, build_hostile(dev["name"]))

    result = dict(summary)
    with db_session() as conn:
        write_audit(conn, x_actor, "syslog.simulate", "syslog_events", None,
                    {"count": count, "storm": storm, "hostil": include_hostile, "resultado": result})
    return {"resultado": result}