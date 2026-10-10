"""Generador de plantillas de configuración comentadas.
Son PROPUESTAS de solo texto: nada se envía a ningún equipo (flujo: revisión humana -> aprobación)."""
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Literal, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.audit import write_audit
from app.database import db_session
from app.schemas import NAME_PATTERN

router = APIRouter(prefix="/api/config", tags=["Plantillas"])

COMMENT = {"cisco": "!", "fortinet": "#", "huawei": "#"}
SEV_NAMES = {
    "cisco": ["emergencies", "alerts", "critical", "errors", "warnings", "notifications", "informational", "debugging"],
    "fortinet": ["emergency", "alert", "critical", "error", "warning", "notification", "information", "debug"],
    "huawei": ["emergencies", "alert", "critical", "error", "warning", "notification", "informational", "debugging"],
}
TEMPLATE_LIST = [
    {"id": "syslog", "name": "Envío de Syslog al NOC"},
    {"id": "hardening", "name": "Endurecimiento base (SSH, NTP, tiempos de espera)"},
]

TEMPLATES = {
    ("cisco", "syslog"): """configure terminal
 ! Marca de tiempo con milisegundos y zona horaria para correlacionar eventos
 service timestamps log datetime msec localtime show-timezone
 ! Servidor Syslog del NOC (IP de ejemplo, rango RFC 5737)
 logging host {shost} transport udp port {sport}
 ! Enviar mensajes hasta la severidad indicada (0 = más grave ... 7 = depuración)
 logging trap {sev}
 ! Facility local7 (23), la misma que espera el parser del NOC
 logging facility local7
 ! IP de origen estable: siempre la misma interfaz (ajustar a la interfaz de gestión)
 logging source-interface Vlan1
 ! Búfer local por si el servidor no está disponible
 logging buffered 16384 informational
 ! Registrar quién cambia la configuración y cuándo
 archive
  log config
   logging enable
   notify syslog contenttype plaintext
end
! Verificar: show logging
! Guardar solo tras validar: write memory
""",
    ("cisco", "hardening"): """configure terminal
 ! Identidad del equipo
 hostname {host}
 ip domain-name lab.example
 ! Ocultar contraseñas en texto claro de la configuración (no reemplaza usar 'secret')
 service password-encryption
 ! Claves RSA para SSH (requiere hostname y domain-name definidos)
 crypto key generate rsa modulus 2048
 ! Solo SSH versión 2, con tiempo de espera y reintentos limitados
 ip ssh version 2
 ip ssh time-out 60
 ip ssh authentication-retries 3
 ! Deshabilitar servicios innecesarios
 no ip http server
 no service pad
 ! Acceso remoto: solo SSH y cierre por inactividad (10 minutos)
 line vty 0 15
  transport input ssh
  exec-timeout 10 0
  login local
 exit
 ! Usuario administrador: definir FUERA de esta plantilla, con un secreto robusto
 ! username <USUARIO> privilege 15 algorithm-type scrypt secret <SECRETO>
 ! Sincronización horaria (necesaria para correlacionar logs)
 ntp server {ntp}
 ! Aviso legal de acceso
 banner login ^C
 Acceso autorizado solamente. La actividad se registra y se audita.
 ^C
end
! Verificar: show ip ssh
! Guardar solo tras validar: write memory
""",
    ("fortinet", "syslog"): """config log syslogd setting
    set status enable
    # Servidor Syslog del NOC (IP de ejemplo, rango RFC 5737)
    set server "{shost}"
    set port {sport}
    # udp es el modo clásico. Para cifrar el transporte usar: set mode reliable
    set mode udp
    # Facility local7, la que espera el parser del NOC
    set facility local7
    # Formato por defecto (clave=valor), reconocido por el parser del NOC
    set format default
end
config log syslogd filter
    # Enviar desde esta severidad hacia arriba
    set severity {sev}
end
# Verificar: get log syslogd setting
""",
    ("fortinet", "hardening"): """config system global
    set hostname "{host}"
    # Cierre de sesión de administración por inactividad (minutos)
    set admintimeout 10
    # Cifrado fuerte y versiones TLS modernas para la administración web
    set strong-crypto enable
    set admin-https-ssl-versions tlsv1-2 tlsv1-3
    # Bloqueo temporal tras intentos fallidos
    set admin-lockout-threshold 3
    set admin-lockout-duration 300
end
config system interface
    edit "port1"
        # Solo acceso administrativo seguro: sin http ni telnet
        set allowaccess ping https ssh
    next
end
config system ntp
    set ntpsync enable
    set type custom
    config ntpserver
        edit 1
            set server "{ntp}"
        next
    end
end
# Cuentas de administrador: crearlas fuera de la plantilla (sin contraseñas aquí)
# Verificar: get system global
""",
    ("huawei", "syslog"): """system-view
 # Habilitar el centro de información
 info-center enable
 # Enviar logs al servidor del NOC (IP de ejemplo), facility local7
 info-center loghost {shost} facility local7 port {sport}
 # Severidad máxima enviada al servidor
 info-center source default channel loghost log level {sev}
 # Marca de tiempo con fecha en los logs
 info-center timestamp log date
return
# Verificar: display info-center
# Guardar solo tras validar: save
""",
    ("huawei", "hardening"): """system-view
 sysname {host}
 # Generar claves del servidor SSH (interactivo, ejecutar manualmente): rsa local-key-pair create
 # Servicios seguros: SSH (STelnet) habilitado y Telnet deshabilitado
 stelnet server enable
 undo telnet server enable
 # Acceso por línea virtual: solo SSH, autenticación AAA y cierre por inactividad
 user-interface vty 0 4
  authentication-mode aaa
  protocol inbound ssh
  idle-timeout 10 0
 quit
 # Cuentas locales: crearlas fuera de la plantilla (sin contraseñas aquí)
 # aaa
 #  local-user <USUARIO> password irreversible-cipher <SECRETO>
 #  local-user <USUARIO> service-type ssh
 #  local-user <USUARIO> privilege level 15
 # Sincronización horaria
 ntp-service unicast-server {ntp}
return
# Verificar: display ssh server status
# Guardar solo tras validar: save
""",
}


class GenerateIn(BaseModel):
    vendor: Literal["cisco", "fortinet", "huawei"]
    template: Literal["syslog", "hardening"]
    device_id: Optional[int] = None
    syslog_host: str = "192.0.2.50"
    syslog_port: int = Field(default=514, ge=1, le=65535)
    severity: int = Field(default=6, ge=0, le=7)
    ntp_host: str = "192.0.2.123"

    @field_validator("syslog_host", "ntp_host")
    @classmethod
    def _ip(cls, v):
        try:
            ip_address(v)
        except ValueError:
            raise ValueError("Dirección IP inválida")
        return v


def _header(vendor: str, template: str) -> str:
    c = COMMENT[vendor]
    return "\n".join([
        f"{c} PROPUESTA generada por NOC Syslog Inteligente ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)",
        f"{c} Plantilla: {template}. Requiere revisión humana y aprobación antes de aplicarse.",
        f"{c} Probar primero en laboratorio y validar la sintaxis con la versión exacta del equipo.",
        f"{c} No contiene contraseñas ni claves: defínelas fuera de la plantilla.",
        "",
    ])


@router.get("/templates")
def list_templates():
    return TEMPLATE_LIST


@router.post("/generate")
def generate(body: GenerateIn, x_actor: str = Header(default="anonymous")):
    host = "SIM-EQUIPO-01"
    with db_session() as conn:
        if body.device_id is not None:
            dev = conn.execute("SELECT name, vendor FROM devices WHERE id = ?",
                               (body.device_id,)).fetchone()
            if dev is None:
                raise HTTPException(404, "Equipo no encontrado")
            if dev["vendor"] in COMMENT and dev["vendor"] != body.vendor:
                raise HTTPException(422, f"El equipo es {dev['vendor']}, no {body.vendor}")
            host = dev["name"]
        text = _header(body.vendor, body.template) + TEMPLATES[(body.vendor, body.template)].format(
            host=host, shost=body.syslog_host, sport=body.syslog_port,
            sev=SEV_NAMES[body.vendor][body.severity], ntp=body.ntp_host)
        write_audit(conn, x_actor, "config.generate", "devices", body.device_id,
                    {"vendor": body.vendor, "template": body.template})
    return {"vendor": body.vendor, "template": body.template,
            "filename": f"{body.template}-{body.vendor}.txt", "content": text}