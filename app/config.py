"""Configuracion central. Nunca poner secretos aqui: usar variables de entorno."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("NOC_DB_PATH", BASE_DIR / "data" / "noc_syslog.db"))
SCHEMA_PATH = BASE_DIR / "app" / "schema.sql"
APP_VERSION = "0.2.0"