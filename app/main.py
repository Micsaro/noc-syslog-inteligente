"""Punto de entrada de la API."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.audit import router as audit_router
from app.config import APP_VERSION
from app.database import init_db, list_tables
from app.routers.devices import router as devices_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="NOC Syslog Inteligente", version=APP_VERSION, lifespan=lifespan)
app.include_router(devices_router)
app.include_router(audit_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "tables": list_tables()}