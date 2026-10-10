"""Política de comandos de la consola simulada (SOLO LECTURA).

Principios:
- Se DENIEGA POR DEFECTO: solo corre lo que está en la lista de permitidos.
- La lista de bloqueados siempre gana y explica el motivo.
- Los comandos los escribe o aprueba una PERSONA. Nunca se extraen de logs ni de
  salidas de equipos (regla de oro: los logs son datos, no instrucciones).
"""
import re
from dataclasses import dataclass
from typing import Optional

MAX_COMMAND_LEN = 160
_CHARS_OK = re.compile(r"^[A-Za-z0-9 _./:|-]+$")        # lista blanca de caracteres
_IF = r"[A-Za-z][A-Za-z0-9/.-]{1,30}"                    # nombre de interfaz
_FILTER = re.compile(r"^(include|exclude|begin|section|grep|count)\s+([A-Za-z0-9_./:-]{1,40})$", re.I)

# (comando, descripción, ¿botón de verificación rápida?)
ALLOWED = {
    "cisco": [
        ("show version", "Versión de IOS XE, modelo y uptime", True),
        ("show ip interface brief", "Estado de las interfaces de capa 3", True),
        ("show interfaces status", "Estado de los puertos físicos", True),
        ("show vlan brief", "VLANs y puertos asignados", True),
        ("show logging", "Últimos mensajes de log del equipo", True),
        ("show clock", "Hora del equipo", False),
        ("show inventory", "Inventario de hardware", False),
        ("show processes cpu", "Uso de CPU", False),
        ("show cdp neighbors", "Vecinos CDP", False),
        ("show running-config", "Configuración activa (secretos ocultos)", False),
        ("show interfaces <if>", "Detalle de una interfaz", False),
    ],
    "fortinet": [
        ("get system status", "Versión, serie y modo de operación", True),
        ("get system performance status", "CPU, memoria y uptime", True),
        ("get system interface physical", "Interfaces físicas", True),
        ("get router info routing-table all", "Tabla de rutas", True),
        ("get system ha status", "Estado de alta disponibilidad", False),
        ("get system arp", "Tabla ARP", False),
        ("diagnose sys session stat", "Estadísticas de sesiones", False),
    ],
    "huawei": [
        ("display version", "Versión de VRP y uptime", True),
        ("display ip interface brief", "Interfaces con IP", True),
        ("display interface brief", "Estado de las interfaces", True),
        ("display ip routing-table", "Tabla de rutas", True),
        ("display logbuffer", "Últimos mensajes de log del equipo", True),
        ("display clock", "Hora del equipo", False),
        ("display cpu-usage", "Uso de CPU", False),
        ("display memory-usage", "Uso de memoria", False),
        ("display device", "Estado del hardware", False),
        ("display current-configuration", "Configuración activa (secretos ocultos)", False),
        ("display interface <if>", "Detalle de una interfaz", False),
    ],
    "other": [],
}

# (categoría, motivo, expresión sobre la 1.ª palabra, ejemplos)
_BLOCKED_DEFS = [
    ("configuracion", "Entrar a modo de configuración o modificarla",
     r"^(configure|conf|config|system-view|edit|set|unset|append|rename|no|undo|interface|router|"
     r"vlan|username|hostname|sysname|aaa|crypto|snmp-server|access-list|route|switchport|shutdown|description)\b",
     ["configure terminal", "set status disable", "undo info-center enable"]),
    ("persistencia", "Guardar, copiar, borrar, limpiar o reiniciar",
     r"^(write|wr|copy|save|erase|format|reload|reboot|boot|reset|factory-reset|clear|delete|restore|backup)\b",
     ["write erase", "reload", "save", "delete flash:config"]),
    ("ejecucion", "Ejecución con efecto sobre el equipo, pruebas o depuración",
     r"^(execute|exec|debug|undebug|terminal|test|monitor)\b|^diagnose\s+(debug|sys\s+(kill|reboot))",
     ["execute reboot", "debug all", "diagnose debug enable"]),
    ("privilegios", "Escalada de privilegios",
     r"^(enable|login|su|sudo|super|privilege)\b",
     ["enable", "super 15", "sudo su"]),
    ("red-activa", "Sondeo activo o transferencia de archivos (requeriría aprobación)",
     r"^(ping|traceroute|tracert|tftp|ftp|scp|sftp|ssh|telnet|curl|wget|nc|netcat)\b",
     ["ping 192.0.2.1", "tftp flash:config", "ssh 192.0.2.5"]),
    ("sistema-operativo", "Intérpretes del sistema o scripting",
     r"^(bash|zsh|cmd|powershell|pwsh|python|perl|rm|cat)\b",
     ["bash", "powershell", "python"]),
]
_BLOCKED = [(c, r, re.compile(rx), ex) for c, r, rx, ex in _BLOCKED_DEFS]


def _compile(cmd: str) -> re.Pattern:
    parts = cmd.split("<if>")
    return re.compile("^" + f"({_IF})".join(re.escape(p) for p in parts) + "$", re.I)


_COMPILED = {v: [(_compile(c), c, d, p) for c, d, p in items] for v, items in ALLOWED.items()}


@dataclass
class Decision:
    allowed: bool
    command: str                    # comando normalizado
    category: str
    reason: str
    canon: str = ""                 # plantilla permitida que coincidió
    arg: Optional[str] = None       # argumento (interfaz) si aplica
    flt: Optional[str] = None       # filtro tras '|', si aplica


def _deny(cmd: str, category: str, reason: str) -> Decision:
    return Decision(False, cmd, category, reason)


def evaluate(vendor: str, raw: str) -> Decision:
    cmd = " ".join((raw or "").split())              # normaliza espacios y saltos de línea
    if not cmd:
        return _deny("", "vacio", "Comando vacío")
    if len(cmd) > MAX_COMMAND_LEN:
        return _deny(cmd[:MAX_COMMAND_LEN], "longitud", f"Supera {MAX_COMMAND_LEN} caracteres")
    if not _CHARS_OK.match(cmd):
        return _deny(cmd, "caracteres",
                     "Contiene caracteres no permitidos (solo letras, números, espacio y _ . / : | -)")

    base, flt = cmd, None
    if "|" in cmd:
        pieces = [p.strip() for p in cmd.split("|")]
        if len(pieces) != 2:
            return _deny(cmd, "filtro", "Solo se admite un filtro con '|'")
        base, flt = pieces
        if not _FILTER.match(flt):
            return _deny(cmd, "filtro",
                         "Filtro no permitido (solo include, exclude, begin, section, grep, count)")

    low = base.lower()
    for category, reason, rx, _ in _BLOCKED:         # los bloqueados SIEMPRE ganan
        if rx.search(low):
            return _deny(cmd, f"bloqueado-{category}", reason)

    for rx, canon, desc, _ in _COMPILED.get(vendor, []):
        m = rx.match(base)
        if m:
            return Decision(True, cmd, "permitido", desc, canon=canon,
                            arg=m.group(1) if m.groups() else None, flt=flt)

    return _deny(cmd, "no-listado",
                 "No está en la lista de permitidos (se deniega por defecto). "
                 "Escribe el comando completo: no se aceptan abreviaturas.")


def presets_for(vendor: str) -> list[dict]:
    return [{"command": c, "description": d} for c, d, preset in ALLOWED.get(vendor, []) if preset]


def policy_summary(vendor: str) -> dict:
    return {
        "vendor": vendor,
        "allowed": [{"command": c, "description": d} for c, d, _ in ALLOWED.get(vendor, [])],
        "blocked": [{"category": c, "reason": r, "examples": ex} for c, r, _, ex in _BLOCKED],
        "rules": [
            "Se deniega por defecto: solo corren los comandos de la lista de permitidos.",
            "La lista de bloqueados siempre gana.",
            "No se aceptan abreviaturas (por ejemplo 'sh ver' o 'wr').",
            "Solo caracteres: letras, números, espacio y _ . / : | -",
            "Un único filtro '|' con include, exclude, begin, section, grep o count.",
            "Los comandos solo los escribe o aprueba una persona; nunca vienen de un log.",
        ],
    }