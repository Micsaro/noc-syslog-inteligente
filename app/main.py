"""Punto de entrada de la API y del dashboard."""
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.audit import router as audit_router
from app.config import APP_VERSION
from app.database import init_db, list_tables
from app.routers.dashboard import router as dashboard_router
from app.routers.devices import router as devices_router
from app.routers.events import router as events_router
from app.routers.incidents import router as incidents_router
from app.routers.syslog import router as syslog_router
from app.udp_receiver import start_udp_listener

logging.basicConfig(level=logging.INFO)

# En Windows el registro a veces asocia .js con text/plain; con 'nosniff' el navegador
# se negaría a ejecutarlo. Se fija explícitamente.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Política estricta: solo recursos propios, sin scripts ni estilos en línea.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")   # Swagger necesita recursos externos


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    transport = await start_udp_listener()
    yield
    if transport:
        transport.close()


app = FastAPI(title="NOC Syslog Inteligente", version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith(DOCS_PATHS):
        response.headers["Content-Security-Policy"] = CSP
    return response


app.include_router(devices_router)
app.include_router(syslog_router)
app.include_router(events_router)
app.include_router(incidents_router)
app.include_router(dashboard_router)
app.include_router(audit_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "tables": list_tables()}