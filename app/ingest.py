"""Motor de ingestión: parsea, clasifica, limita, deduplica y guarda.

Flujo: recepción -> límite de tasa -> parseo/saneamiento -> detección de
patrones sospechosos -> asociación con inventario -> deduplicación -> guardado -> auditoría.
El contenido del log NUNCA se ejecuta ni se pasa a una IA como instrucción.
"""
import hashlib
import re
import sqlite3
import time
from collections import defaultdict, deque
from typing import Optional
from app.audit import write_audit
from app.config import DEDUP_WINDOW_SECONDS, MAX_RAW_CHARS, RATE_LIMIT_PER_MIN
from app.database import db_session
from app.syslog_parser import SEVERITY_NAMES, detect_suspicious, parse_syslog

# Límite de tasa en memoria (se reinicia al reiniciar el servidor).
_hits: dict[str, deque] = defaultdict(deque)
_limited: set[str] = set()


def _allow(source_key: str) -> tuple[bool, bool]:
    """Devuelve (permitido, es_primer_descarte_de_este_origen)."""
    if len(_hits) > 5000:        # evita crecimiento sin límite con IPs falsificadas
        _hits.clear()
    now = time.monotonic()
    window = _hits[source_key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MIN:
        first = source_key not in _limited
        _limited.add(source_key)
        return False, first
    _limited.discard(source_key)
    window.append(now)
    return True, False


def _dedup_hash(device_key: str, facility: int, severity: int, message: str) -> str:
    """Hash estable: los números se normalizan para agrupar mensajes casi idénticos."""
    normalized = re.sub(r"\d+", "#", message.lower())
    base = f"{device_key}|{facility}|{severity}|{normalized}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _match_device(conn: sqlite3.Connection, source_ip: Optional[str],
                  hostname: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """Asocia el evento a un equipo del inventario. Devuelve (device_id, etiqueta)."""
    if source_ip:
        row = conn.execute("SELECT id FROM devices WHERE ip_address = ?", (source_ip,)).fetchone()
        if row:
            return row["id"], None
    if hostname:   # el hostname lo declara el mensaje: es más débil, por eso se etiqueta
        row = conn.execute("SELECT id FROM devices WHERE lower(name) = lower(?)",
                           (hostname,)).fetchone()
        if row:
            return row["id"], "match-hostname"
    return None, "dispositivo-desconocido"


def ingest_message(raw: str, source_ip: Optional[str] = None, is_simulated: bool = True,
                   actor: str = "syslog-receiver") -> dict:
    raw = raw[:MAX_RAW_CHARS]

    allowed, first_drop = _allow(source_ip or "desconocido")
    if not allowed:
        if first_drop:   # un solo registro de auditoría por ráfaga, para no inundar el log
            with db_session() as conn:
                write_audit(conn, actor, "syslog.rate_limited", "syslog_events", None,
                            {"source_ip": source_ip, "limite_por_minuto": RATE_LIMIT_PER_MIN})
        return {"status": "rate_limited"}

    parsed = parse_syslog(raw)
    suspicious = detect_suspicious(raw)

    tags = ["simulado" if is_simulated else "real"]
    if not parsed.pri_valid:
        tags.append("sin-pri")
    if suspicious:
        tags += ["sospechoso"] + suspicious

    with db_session() as conn:
        device_id, match_tag = _match_device(conn, source_ip, parsed.hostname)
        if match_tag:
            tags.append(match_tag)

        device_key = str(device_id or source_ip or parsed.hostname or "?")
        dedup = _dedup_hash(device_key, parsed.facility, parsed.severity, parsed.message)

        dup = conn.execute(
            "SELECT id FROM syslog_events WHERE dedup_hash = ? "
            "AND received_at >= datetime('now', ?) ORDER BY id DESC LIMIT 1",
            (dedup, f"-{DEDUP_WINDOW_SECONDS} seconds")).fetchone()
        if dup:
            conn.execute(
                "UPDATE syslog_events SET repeat_count = repeat_count + 1, "
                "last_seen = datetime('now') WHERE id = ?", (dup["id"],))
            return {"status": "deduplicated", "event_id": dup["id"]}

        cur = conn.execute(
            "INSERT INTO syslog_events (device_id, source_ip, hostname, event_time, "
            "facility, severity, message, raw_message, dedup_hash, tags, is_simulated, "
            "last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now'))",
            (device_id, source_ip, parsed.hostname, parsed.event_time, parsed.facility,
             parsed.severity, parsed.message, raw, dedup, ",".join(tags), int(is_simulated)))
        event_id = cur.lastrowid

        if suspicious:
            write_audit(conn, actor, "syslog.suspicious", "syslog_events", event_id,
                        {"patrones": suspicious, "severidad": parsed.severity})

    return {"status": "stored", "event_id": event_id, "format": parsed.fmt,
            "facility": parsed.facility, "severity": parsed.severity,
            "severity_name": SEVERITY_NAMES[parsed.severity],
            "device_id": device_id, "tags": tags}