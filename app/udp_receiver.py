"""Receptor Syslog por UDP (asyncio). Escucha solo en local por defecto."""
import asyncio
import logging
from app.config import UDP_ENABLED, UDP_HOST, UDP_IS_SIMULATED, UDP_PORT
from app.ingest import ingest_message

logger = logging.getLogger("noc.udp")


class SyslogUDPProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr) -> None:
        # Un datagrama malformado nunca debe tumbar el receptor.
        # No se registra el contenido en el log del sistema: es dato no confiable.
        try:
            text = data.decode("utf-8", errors="replace")
            ingest_message(text, source_ip=addr[0], is_simulated=UDP_IS_SIMULATED,
                           actor="udp-receiver")
        except Exception:
            logger.exception("Error procesando datagrama de %s", addr[0])


async def start_udp_listener():
    if not UDP_ENABLED:
        return None
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            SyslogUDPProtocol, local_addr=(UDP_HOST, UDP_PORT))
    except OSError as exc:
        logger.warning("No se pudo abrir UDP %s:%s (%s). La API sigue funcionando.",
                       UDP_HOST, UDP_PORT, exc)
        return None
    logger.info("Receptor Syslog UDP escuchando en %s:%s", UDP_HOST, UDP_PORT)
    return transport