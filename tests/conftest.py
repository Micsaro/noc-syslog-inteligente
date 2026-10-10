"""Entorno de pruebas: base de datos temporal y sin receptor UDP.
Las variables de entorno se fijan ANTES de importar la aplicación."""
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="noc_test_")
os.environ["NOC_DB_PATH"] = str(Path(_TMP) / "test.db")
os.environ["NOC_UDP_ENABLED"] = "0"

import pytest
from fastapi.testclient import TestClient

from app import ingest
from app.database import db_session
from app.main import app
from scripts.seed_demo import DEMO_DEVICES


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:      # al entrar se ejecuta el lifespan (init_db)
        yield c


@pytest.fixture(autouse=True)
def clean_state(client):
    """Cada prueba parte de cero: tablas vacías, 3 equipos simulados y límite de tasa reiniciado."""
    ingest._hits.clear()
    ingest._limited.clear()
    with db_session() as conn:
        for table in ("incident_events", "incidents", "syslog_events",
                      "console_macros", "audit_log", "devices"):
            conn.execute(f"DELETE FROM {table}")
        for d in DEMO_DEVICES:
            conn.execute(
                "INSERT INTO devices (name, ip_address, vendor, model, os_version, location, "
                "is_simulated) VALUES (?,?,?,?,?,?,1)", d)
    yield