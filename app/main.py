"""Punto de entrada de la API."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.audit import router as audit_router
from app.config import APP_VERSION
from app.database import init_db, list_tables
from app.routers.devices import router as devices_router
from app.routers.events import router as events_router
from app.routers.syslog import router as syslog_router
from app.udp_receiver import start_udp_listener

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    transport = await start_udp_listener()   # None si está desactivado o el puerto está ocupado
    yield
    if transport:
        transport.close()


app = FastAPI(title="NOC Syslog Inteligente", version=APP_VERSION, lifespan=lifespan)
app.include_router(devices_router)
app.include_router(syslog_router)
app.include_router(events_router)
app.include_router(audit_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "tables": list_tables()}