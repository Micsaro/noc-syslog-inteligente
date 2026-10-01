"""Auditoría: cada cambio relevante deja huella (quién, qué, cuándo)."""
import json
import sqlite3
from fastapi import APIRouter, Query
from app.database import db_session

router = APIRouter(prefix="/api/audit", tags=["Auditoría"])


def write_audit(conn: sqlite3.Connection, actor: str, action: str,
                entity: str, entity_id: int | None, details: dict) -> None:
    """Escribe en audit_log usando la MISMA transacción del cambio."""
    conn.execute(
        "INSERT INTO audit_log (actor, action, entity, entity_id, details) "
        "VALUES (?,?,?,?,?)",
        (actor, action, entity, entity_id, json.dumps(details, ensure_ascii=False)),
    )


@router.get("")
def list_audit(limit: int = Query(50, ge=1, le=500)):
    """Últimos registros de auditoría (más recientes primero)."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]