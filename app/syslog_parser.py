"""Parser Syslog.

PRINCIPIO: el texto de un log es un DATO NO CONFIABLE. Este módulo solo extrae
campos y limpia texto; jamás interpreta ni ejecuta el contenido. El escape para
mostrarlo (HTML) se hace en la SALIDA (frontend con textContent), no aquí.
"""
import re
from dataclasses import dataclass
from typing import Optional
from app.config import MAX_MESSAGE_CHARS

SEVERITY_NAMES = ["Emergency", "Alert", "Critical", "Error",
                  "Warning", "Notice", "Informational", "Debug"]
FACILITY_NAMES = ["kern", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
                  "uucp", "cron", "authpriv", "ftp", "ntp", "audit", "alert", "clock",
                  "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7"]

DEFAULT_PRI = 13  # RFC 3164: sin <PRI> se asume user.notice (facility 1, severidad 5)

_PRI_RE = re.compile(r"^<(\d{1,3})>(.*)$", re.DOTALL)
_RFC5424_RE = re.compile(
    r"^(\d{1,2}) (\S+) (\S+) (\S+) (\S+) (\S+) (-|(?:\[[^\]]*\])+) ?(.*)$", re.DOTALL)
_RFC3164_RE = re.compile(
    r"^([A-Z][a-z]{2}\s+\d{1,2}(?:\s+\d{4})?\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(\S+)\s+(.*)$",
    re.DOTALL)
_FORTI_DEV_RE = re.compile(r'devname="?([A-Za-z0-9._-]{1,64})"?')
_FORTI_TIME_RE = re.compile(r"date=(\d{4}-\d{2}-\d{2}) time=(\d{2}:\d{2}:\d{2})")
_HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Caracteres de control (incluye ESC de ANSI) y caracteres Unicode que permiten
# falsear lo que se ve en pantalla (bidireccionales / ancho cero, "Trojan Source").
_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")

# Patrones que marcan un mensaje como SOSPECHOSO (solo etiquetan, nunca ejecutan).
SUSPICIOUS_PATTERNS = {
    "prompt-injection": re.compile(
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions"
        r"|ignora\s+(las\s+)?instrucciones|system\s+prompt|you\s+are\s+now\b"
        r"|disregard\s+(the\s+)?(rules|instructions)", re.I),
    "xss": re.compile(r"<\s*script|javascript\s*:|on(error|load)\s*=|<\s*iframe", re.I),
    "comando-embebido": re.compile(
        r"\b(rm\s+-rf|write\s+erase|erase\s+startup-config|format\s+(flash|disk)"
        r"|(curl|wget)\s+https?://|powershell\s+-e)", re.I),
    "sqli": re.compile(r"('|\")\s*(or|and)\s+\d+\s*=\s*\d+|union\s+select|;\s*drop\s+table", re.I),
}


@dataclass
class ParsedSyslog:
    facility: int
    severity: int
    event_time: Optional[str]   # lo que DICE el equipo (no confiable); received_at es la hora del servidor
    hostname: Optional[str]
    message: str                # saneado
    pri_valid: bool
    fmt: str                    # 'rfc5424' | 'rfc3164' | 'fortinet' | 'raw'


def sanitize(text: str, max_len: int = MAX_MESSAGE_CHARS) -> str:
    """Quita caracteres de control, colapsa espacios y limita la longitud."""
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len] + "…[truncado]"
    return text


def detect_suspicious(text: str) -> list[str]:
    """Devuelve las categorías sospechosas halladas (se evalúa sobre el texto ORIGINAL)."""
    return [name for name, rx in SUSPICIOUS_PATTERNS.items() if rx.search(text)]


def _valid_host(value: Optional[str]) -> Optional[str]:
    return value if value and _HOST_RE.match(value) else None


def parse_syslog(raw: str) -> ParsedSyslog:
    text = raw.strip()
    pri_valid, body = False, text
    facility, severity = divmod(DEFAULT_PRI, 8)

    m = _PRI_RE.match(text)
    if m and int(m.group(1)) <= 191:           # 191 = facility 23 * 8 + severidad 7
        facility, severity = divmod(int(m.group(1)), 8)
        body, pri_valid = m.group(2), True

    hostname = event_time = None
    message, fmt = body, "raw"

    m5 = _RFC5424_RE.match(body)
    m3 = _RFC3164_RE.match(body)
    if m5 and m5.group(1) == "1":
        _, ts, host, app, _, _, _, msg = m5.groups()
        event_time = None if ts == "-" else ts
        hostname = _valid_host(None if host == "-" else host)
        message = msg if app == "-" else f"{app}: {msg}"
        fmt = "rfc5424"
    elif m3:
        ts, host, msg = m3.groups()
        event_time = ts
        hostname = _valid_host(host)
        message = msg if hostname else f"{host} {msg}"   # si no era un hostname, es parte del mensaje
        fmt = "rfc3164"
    elif "devname=" in body:
        dev = _FORTI_DEV_RE.search(body)
        tm = _FORTI_TIME_RE.search(body)
        hostname = _valid_host(dev.group(1)) if dev else None
        event_time = f"{tm.group(1)} {tm.group(2)}" if tm else None
        fmt = "fortinet"

    return ParsedSyslog(
        facility=facility,
        severity=severity,
        event_time=sanitize(event_time, 64) if event_time else None,
        hostname=hostname,
        message=sanitize(message) or "(vacío)",
        pri_valid=pri_valid,
        fmt=fmt,
    )