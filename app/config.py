"""Configuracion central. Nunca poner secretos aqui: usar variables de entorno."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("NOC_DB_PATH", BASE_DIR / "data" / "noc_syslog.db"))
SCHEMA_PATH = BASE_DIR / "app" / "schema.sql"
APP_VERSION = "0.2.0"

# --- Syslog (Fase 3) ---
UDP_ENABLED = os.getenv("NOC_UDP_ENABLED", "1") == "1"
UDP_HOST = os.getenv("NOC_UDP_HOST", "127.0.0.1")   # solo local por defecto
UDP_PORT = int(os.getenv("NOC_UDP_PORT", "5514"))    # el 514 exige privilegios
# En este proyecto académico todo lo recibido se etiqueta como SIMULADO,
# salvo que se active explícitamente NOC_UDP_REAL=1.
UDP_IS_SIMULATED = os.getenv("NOC_UDP_REAL", "0") != "1"
MAX_RAW_CHARS = 4096          # tope del mensaje original
MAX_MESSAGE_CHARS = 1024      # tope del mensaje saneado
DEDUP_WINDOW_SECONDS = 60     # ventana de deduplicación
RATE_LIMIT_PER_MIN = 300      # mensajes máximos por origen y minuto