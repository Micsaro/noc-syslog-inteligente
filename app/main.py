"""Punto de entrada de la API."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import APP_VERSION
from app.database import init_db, list_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()          # se ejecuta al arrancar el servidor
    yield


app = FastAPI(title="NOC Syslog Inteligente", version=APP_VERSION, lifespan=lifespan)


@app.get("/health")
def health():
    """Comprobacion rapida: version y tablas creadas."""
    return {"status": "ok", "version": APP_VERSION, "tables": list_tables()}