"""Acceso a SQLite: conexión, sesion transaccional e inicializacion."""
import sqlite3
from contextlib import contextmanager
from app.config import DB_PATH, SCHEMA_PATH


def get_connection() -> sqlite3.Connection:
    """Devuelve una conexión con filas accesibles por nombre y FKs activas."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_session():
    """Sesión transaccional: commit si todo sale bien, rollback si hay error,
    y siempre cierra la conexión. Así el cambio y su auditoría son atómicos."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Migración ligera: agrega columnas nuevas a bases creadas en fases anteriores."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(syslog_events)").fetchall()}
    if "repeat_count" not in cols:
        conn.execute("ALTER TABLE syslog_events ADD COLUMN repeat_count INTEGER NOT NULL DEFAULT 1")
    if "last_seen" not in cols:
        conn.execute("ALTER TABLE syslog_events ADD COLUMN last_seen TEXT")


def init_db() -> None:
    """Crea las tablas si no existen y aplica migraciones (idempotente)."""
    with db_session() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)


def list_tables() -> list[str]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [r["name"] for r in rows]