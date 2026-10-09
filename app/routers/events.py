"""Consulta de eventos Syslog con filtros y estadísticas."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.database import db_session
from app.schemas import Vendor
from app.syslog_parser import FACILITY_NAMES, SEVERITY_NAMES

router = APIRouter(prefix="/api/events", tags=["Eventos"])

BASE_SELECT = (
    "SELECT e.*, d.name AS device_name, d.vendor AS vendor "
    "FROM syslog_events e LEFT JOIN devices d ON d.id = e.device_id"
)
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$"


def _to_event(r: sqlite3.Row, include_raw: bool = False) -> dict:
    ev = {
        "id": r["id"], "device_id": r["device_id"], "device_name": r["device_name"],
        "vendor": r["vendor"], "source_ip": r["source_ip"], "hostname": r["hostname"],
        "received_at": r["received_at"], "event_time": r["event_time"],
        "facility": r["facility"],
        "facility_name": FACILITY_NAMES[r["facility"]] if r["facility"] is not None else None,
        "severity": r["severity"], "severity_name": SEVERITY_NAMES[r["severity"]],
        "message": r["message"],   # saneado; el frontend lo mostrará con textContent
        "tags": [t for t in (r["tags"] or "").split(",") if t],
        "repeat_count": r["repeat_count"], "last_seen": r["last_seen"],
        "is_simulated": bool(r["is_simulated"]),
    }
    if include_raw:
        ev["raw_message"] = r["raw_message"]
        ev["warning"] = ("raw_message es contenido NO CONFIABLE: no ejecutar, "
                         "no interpretar, no renderizar como HTML.")
    return ev


@router.get("")
def list_events(
    severity: Optional[int] = Query(None, ge=0, le=7),
    max_severity: Optional[int] = Query(None, ge=0, le=7, description="Incluye 0..N (0 = más grave)"),
    facility: Optional[int] = Query(None, ge=0, le=23),
    device_id: Optional[int] = None,
    vendor: Optional[Vendor] = None,
    tag: Optional[str] = Query(None, max_length=32, pattern=r"^[a-z0-9-]+$"),
    simulated: Optional[bool] = None,
    date_from: Optional[str] = Query(None, pattern=DATE_PATTERN, description="UTC, AAAA-MM-DD [HH:MM:SS]"),
    date_to: Optional[str] = Query(None, pattern=DATE_PATTERN, description="UTC, AAAA-MM-DD [HH:MM:SS]"),
    q: Optional[str] = Query(None, max_length=64, description="Busca en el mensaje saneado"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    where, params = [], []

    def add(clause: str, value) -> None:
        where.append(clause)
        params.append(value)

    if severity is not None:
        add("e.severity = ?", severity)
    if max_severity is not None:
        add("e.severity <= ?", max_severity)
    if facility is not None:
        add("e.facility = ?", facility)
    if device_id is not None:
        add("e.device_id = ?", device_id)
    if vendor:
        add("d.vendor = ?", vendor)
    if tag:
        add("(',' || e.tags || ',') LIKE ?", f"%,{tag},%")
    if simulated is not None:
        add("e.is_simulated = ?", int(simulated))
    if date_from:
        add("e.received_at >= ?", date_from)
    if date_to:
        add("e.received_at <= ?", date_to + " 23:59:59" if len(date_to) == 10 else date_to)
    if q:
        add("e.message LIKE ?", f"%{q}%")

    sql = BASE_SELECT + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY e.id DESC LIMIT ? OFFSET ?"
    with db_session() as conn:
        rows = conn.execute(sql, params + [limit, offset]).fetchall()
    return [_to_event(r) for r in rows]


@router.get("/stats")
def stats():
    """Conteos por severidad y por fabricante (events = filas; occurrences = con repeticiones)."""
    with db_session() as conn:
        by_sev = conn.execute(
            "SELECT severity, COUNT(*) AS events, SUM(repeat_count) AS occurrences "
            "FROM syslog_events GROUP BY severity ORDER BY severity").fetchall()
        by_vendor = conn.execute(
            "SELECT COALESCE(d.vendor, 'desconocido') AS vendor, COUNT(*) AS events "
            "FROM syslog_events e LEFT JOIN devices d ON d.id = e.device_id "
            "GROUP BY 1 ORDER BY 2 DESC").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM syslog_events").fetchone()[0]
        suspicious = conn.execute(
            "SELECT COUNT(*) FROM syslog_events WHERE (',' || tags || ',') LIKE '%,sospechoso,%'"
        ).fetchone()[0]
    return {
        "total_events": total,
        "suspicious_events": suspicious,
        "by_severity": [{"severity": r["severity"], "name": SEVERITY_NAMES[r["severity"]],
                         "events": r["events"], "occurrences": r["occurrences"]} for r in by_sev],
        "by_vendor": [dict(r) for r in by_vendor],
    }

@router.get("/tags")
def list_tags():
    """Etiquetas existentes (para el autocompletado del dashboard)."""
    with db_session() as conn:
        rows = conn.execute("SELECT DISTINCT tags FROM syslog_events WHERE tags != ''").fetchall()
    return sorted({t for r in rows for t in r["tags"].split(",") if t})
    
@router.get("/{event_id}")
def get_event(event_id: int):
    """Detalle de un evento, incluida la evidencia original (raw_message)."""
    with db_session() as conn:
        row = conn.execute(BASE_SELECT + " WHERE e.id = ?", (event_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Evento no encontrado")
    return _to_event(row, include_raw=True)