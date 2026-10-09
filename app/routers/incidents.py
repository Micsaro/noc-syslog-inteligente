"""Gestión de incidentes: creación, asignación, seguimiento y cierre.
El historial se apoya en audit_log: cada cambio queda registrado con quién y cuándo."""
import json
import sqlite3
from typing import Literal, Optional
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from app.audit import write_audit
from app.database import db_session
from app.syslog_parser import SEVERITY_NAMES

router = APIRouter(prefix="/api/incidents", tags=["Incidentes"])

IncStatus = Literal["open", "assigned", "in_progress", "resolved", "closed"]

# Transiciones permitidas (closed es terminal: solo lectura).
TRANSITIONS = {
    "open":        ["assigned", "in_progress", "closed"],
    "assigned":    ["open", "in_progress", "resolved", "closed"],
    "in_progress": ["assigned", "resolved"],
    "resolved":    ["in_progress", "closed"],
    "closed":      [],
}
ASSIGNEE_PATTERN = r"^[A-Za-z0-9._@ -]{1,64}$"

INC_SELECT = (
    "SELECT i.*, d.name AS device_name, "
    "(SELECT COUNT(*) FROM incident_events ie WHERE ie.incident_id = i.id) AS events_count "
    "FROM incidents i LEFT JOIN devices d ON d.id = i.device_id"
)


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    severity: int = Field(ge=0, le=7)
    device_id: Optional[int] = None
    assigned_to: Optional[str] = Field(default=None, pattern=ASSIGNEE_PATTERN)
    event_ids: list[int] = Field(default_factory=list, max_length=50)


class IncidentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    severity: Optional[int] = Field(default=None, ge=0, le=7)
    status: Optional[IncStatus] = None
    assigned_to: Optional[str] = Field(default=None, pattern=ASSIGNEE_PATTERN)
    note: Optional[str] = Field(default=None, max_length=500)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def _get_or_404(conn: sqlite3.Connection, incident_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Incidente no encontrado")
    return row


def _load(conn: sqlite3.Connection, incident_id: int) -> dict:
    row = conn.execute(INC_SELECT + " WHERE i.id = ?", (incident_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Incidente no encontrado")
    inc = dict(row)
    inc["severity_name"] = SEVERITY_NAMES[inc["severity"]]
    inc["allowed_next"] = TRANSITIONS[inc["status"]]
    return inc


@router.get("")
def list_incidents(
    status: Optional[IncStatus] = None,
    active: Optional[bool] = Query(None, description="true = ni resueltos ni cerrados"),
    device_id: Optional[int] = None,
    assigned_to: Optional[str] = Query(None, max_length=64),
    limit: int = Query(100, ge=1, le=500),
):
    where, params = [], []
    if status:
        where.append("i.status = ?"); params.append(status)
    if active is True:
        where.append("i.status NOT IN ('resolved','closed')")
    if device_id is not None:
        where.append("i.device_id = ?"); params.append(device_id)
    if assigned_to:
        where.append("i.assigned_to = ?"); params.append(assigned_to)
    sql = INC_SELECT + (" WHERE " + " AND ".join(where) if where else "")
    # Abiertos primero, más graves primero (0 = más grave), más recientes primero.
    sql += (" ORDER BY CASE WHEN i.status = 'closed' THEN 1 ELSE 0 END, "
            "i.severity ASC, i.id DESC LIMIT ?")
    with db_session() as conn:
        rows = conn.execute(sql, params + [limit]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["severity_name"] = SEVERITY_NAMES[d["severity"]]
        out.append(d)
    return out


@router.post("", status_code=201)
def create_incident(body: IncidentCreate, x_actor: str = Header(default="anonymous")):
    with db_session() as conn:
        device_id = body.device_id
        ids = sorted(set(body.event_ids))
        if ids:
            # Solo se generan marcadores '?'; los valores van parametrizados.
            marks = ",".join("?" * len(ids))
            found = conn.execute(
                f"SELECT id, device_id FROM syslog_events WHERE id IN ({marks})", ids).fetchall()
            if len(found) != len(ids):
                raise HTTPException(422, "Alguno de los eventos indicados no existe")
            if device_id is None:   # se infiere el equipo del primer evento que lo tenga
                device_id = next((r["device_id"] for r in found if r["device_id"]), None)
        if device_id is not None and conn.execute(
                "SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone() is None:
            raise HTTPException(422, "El equipo indicado no existe")

        status = "assigned" if body.assigned_to else "open"
        cur = conn.execute(
            "INSERT INTO incidents (title, description, severity, status, device_id, assigned_to) "
            "VALUES (?,?,?,?,?,?)",
            (body.title.strip(), body.description, body.severity, status, device_id, body.assigned_to))
        new_id = cur.lastrowid
        for eid in ids:
            conn.execute("INSERT OR IGNORE INTO incident_events (incident_id, event_id) VALUES (?,?)",
                         (new_id, eid))
        write_audit(conn, x_actor, "incident.create", "incidents", new_id,
                    {"title": body.title.strip(), "severity": body.severity, "device_id": device_id,
                     "assigned_to": body.assigned_to, "event_ids": ids})
        return _load(conn, new_id)


@router.get("/{incident_id}")
def get_incident(incident_id: int):
    with db_session() as conn:
        inc = _load(conn, incident_id)
        rows = conn.execute(
            "SELECT e.id, e.severity, e.message, e.received_at, e.repeat_count, "
            "d.name AS device_name FROM incident_events ie "
            "JOIN syslog_events e ON e.id = ie.event_id "
            "LEFT JOIN devices d ON d.id = e.device_id "
            "WHERE ie.incident_id = ? ORDER BY e.id", (incident_id,)).fetchall()
    inc["events"] = [{**dict(r), "severity_name": SEVERITY_NAMES[r["severity"]]} for r in rows]
    return inc


@router.get("/{incident_id}/history")
def history(incident_id: int):
    with db_session() as conn:
        _get_or_404(conn, incident_id)
        rows = conn.execute(
            "SELECT timestamp, actor, action, details FROM audit_log "
            "WHERE entity = 'incidents' AND entity_id = ? ORDER BY id", (incident_id,)).fetchall()
    out = []
    for r in rows:
        try:
            details = json.loads(r["details"]) if r["details"] else {}
        except ValueError:
            details = {"raw": r["details"]}
        out.append({"timestamp": r["timestamp"], "actor": r["actor"],
                    "action": r["action"], "details": details})
    return out


@router.patch("/{incident_id}")
def update_incident(incident_id: int, changes: IncidentUpdate,
                    x_actor: str = Header(default="anonymous")):
    data = changes.model_dump(exclude_unset=True)
    note = data.pop("note", None)
    for field in ("title", "severity", "status"):
        if field in data and data[field] is None:
            raise HTTPException(422, f"'{field}' no puede ser nulo")

    with db_session() as conn:
        old = _get_or_404(conn, incident_id)
        if old["status"] == "closed":
            raise HTTPException(409, "El incidente está cerrado: es de solo lectura")

        if "status" in data and data["status"] == old["status"]:
            del data["status"]                      # no hay cambio real
        if not data and not note:
            raise HTTPException(400, "No se enviaron cambios")
        if "status" in data and data["status"] not in TRANSITIONS[old["status"]]:
            raise HTTPException(409, f"Transición no permitida: {old['status']} → {data['status']}")
        if data.get("assigned_to") and old["status"] == "open" and "status" not in data:
            data["status"] = "assigned"             # asignar un incidente abierto lo pasa a 'assigned'

        new_status = data.get("status", old["status"])
        new_assignee = data.get("assigned_to", old["assigned_to"])
        if new_status in ("assigned", "in_progress") and not new_assignee:
            raise HTTPException(422, "Asigna el incidente a una persona antes de ese estado")
        if data.get("status") in ("resolved", "closed") and not (note and len(note.strip()) >= 5):
            raise HTTPException(422, "Para resolver o cerrar indica una nota de al menos 5 caracteres")

        if data:
            # Las claves salen de IncidentUpdate (campos fijos); los valores van parametrizados.
            sets = ", ".join(f"{k} = :{k}" for k in data)
            extra = ", closed_at = datetime('now')" if data.get("status") == "closed" else ""
            conn.execute(
                f"UPDATE incidents SET {sets}{extra}, updated_at = datetime('now') WHERE id = :id",
                {**data, "id": incident_id})
            write_audit(conn, x_actor, "incident.update", "incidents", incident_id,
                        {"antes": {k: old[k] for k in data}, "despues": data, "nota": note})
        else:
            conn.execute("UPDATE incidents SET updated_at = datetime('now') WHERE id = ?", (incident_id,))
            write_audit(conn, x_actor, "incident.note", "incidents", incident_id, {"text": note.strip()})
        return _load(conn, incident_id)


@router.post("/{incident_id}/notes", status_code=201)
def add_note(incident_id: int, body: NoteIn, x_actor: str = Header(default="anonymous")):
    with db_session() as conn:
        inc = _get_or_404(conn, incident_id)
        if inc["status"] == "closed":
            raise HTTPException(409, "El incidente está cerrado: es de solo lectura")
        conn.execute("UPDATE incidents SET updated_at = datetime('now') WHERE id = ?", (incident_id,))
        write_audit(conn, x_actor, "incident.note", "incidents", incident_id, {"text": body.text.strip()})
    return {"ok": True}