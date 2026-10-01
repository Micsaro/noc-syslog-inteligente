"""Envía mensajes Syslog de PRUEBA por UDP al receptor local (127.0.0.1:5514)."""
import socket

HOST, PORT = "127.0.0.1", 5514
MESSAGES = [
    '<132>date=2026-10-01 time=20:50:00 devname="SIM-FORTI-FW01" level="warning" msg="Admin login failed"',
    "<188>Oct  1 2026 20:50:05 SIM-HUAWEI-RT01 %%01SSH/4/USERAUTH_FAIL(l)[0]:Failed to authenticate user admin.",
    "<190>Oct  1 20:50:10 EQUIPO-NO-REGISTRADO Mensaje de prueba de un equipo desconocido",
    "mensaje sin cabecera PRI",
]

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    for m in MESSAGES:
        sock.sendto(m.encode("utf-8"), (HOST, PORT))
        print("Enviado:", m[:70])