# NOC Syslog Inteligente (v0.2.0 · MVP)

Proyecto académico de **Administración y Gestión de Redes** (2026-2).
Centraliza mensajes Syslog de equipos Cisco, Fortinet y Huawei, los clasifica, los muestra en un
dashboard, gestiona incidentes y ofrece una consola simulada de solo lectura. Está diseñado con una
idea central: **los logs son datos no confiables, nunca instrucciones**, para resistir la
manipulación de agentes de IA.

> **Aviso:** todos los datos son **simulados**. No hay credenciales, tokens ni IPs de producción
> (las IPs usan rangos de documentación RFC 5737). La consola **no** se conecta a equipos reales.

## Capturas
Agrega tus imágenes en `docs/img/` (resumen, eventos, incidentes, consola) y enlázalas aquí.

## Requisitos
Python 3.11 o superior. Probado en Windows con PowerShell.

## Instalación y ejecución
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.seed_demo           # equipos simulados
python -m uvicorn app.main:app --reload
```
- Dashboard: http://127.0.0.1:8000/
- Documentación interactiva de la API: http://127.0.0.1:8000/docs
- Receptor Syslog UDP: `127.0.0.1:5514`. Para probarlo: `python -m scripts.send_test_udp`

## Variables de entorno
| Variable | Por defecto | Descripción |
|---|---|---|
| `NOC_DB_PATH` | `data/noc_syslog.db` | Ruta de la base SQLite |
| `NOC_UDP_ENABLED` | `1` | `0` desactiva el receptor UDP |
| `NOC_UDP_HOST` | `127.0.0.1` | Interfaz de escucha (solo local por defecto) |
| `NOC_UDP_PORT` | `5514` | Puerto UDP (el 514 exige privilegios) |
| `NOC_UDP_REAL` | `0` | `1` marca lo recibido por UDP como `real` en lugar de `simulado` |

## Pruebas
```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -v
```
Las pruebas usan una base de datos temporal y no tocan tus datos.

## API (resumen)
| Ruta | Descripción |
|---|---|
| `GET/POST/PATCH/DELETE /api/devices` | Inventario de equipos |
| `POST /api/syslog/ingest`, `POST /api/syslog/simulate` | Importar un mensaje / generar tráfico simulado |
| `GET /api/events`, `/api/events/{id}`, `/api/events/stats` | Consulta con filtros (severidad, marca, equipo, fecha, etiqueta, texto) |
| `GET /api/dashboard/summary` | Datos agregados del dashboard |
| `GET/POST/PATCH /api/incidents`, `/{id}/history`, `/{id}/notes` | Gestión de incidentes |
| `POST /api/console/connect`, `/exec`; `GET /api/console/ports, /policy/{vendor}` | Consola simulada |
| `GET/POST/DELETE /api/console/macros`, `POST .../{id}/run` | Macros |
| `POST /api/config/generate` | Plantillas comentadas Cisco/Fortinet/Huawei |
| `GET /api/audit` | Auditoría |

## Seguridad por diseño
- **Saneamiento** de logs y conservación del original como evidencia (`raw_message`).
- **Etiquetado** de patrones sospechosos (inyección de instrucciones, XSS, comandos embebidos, SQLi).
- **Control de tormentas**: deduplicación y límite de tasa por origen.
- **Consola de solo lectura**: denegar por defecto, bloqueados primero, sin abreviaturas ni metacaracteres.
- **Frontend sin HTML construido con datos** (solo nodos de texto) y **CSP** estricta.
- **Auditoría** de cada cambio y de cada comando, permitido o bloqueado.

Detalle en [`docs/politica-defensa-ia.md`](docs/politica-defensa-ia.md) y
[`docs/diseno-ssh-real.md`](docs/diseno-ssh-real.md).

## Matriz de cobertura frente a los requisitos del MVP
✅ implementado · 🟡 parcial · 📐 solo diseñado · ⬜ pendiente

| # | Requisito | Estado | Notas |
|---|---|---|---|
| 1 | Inventario editable | 🟡 | CRUD completo por API; falta formulario en el dashboard |
| 2 | Recepción/importación de Syslog (simulado/real identificados) | ✅ | UDP, API y simulador; etiquetas `simulado`/`real` |
| 3 | Clasificación por equipo, marca, fecha, facility y severidad 0-7 | ✅ | |
| 4 | Dashboard: estado, eventos recientes, críticos, incidentes | ✅ | |
| 4 | Modo oscuro/claro | ✅ | |
| 4 | Mapa de calor y tendencias de errores | ✅ | Volumen de mensajes por equipo y hora (no tráfico de red) |
| 4 | Búsqueda avanzada con autocompletado | 🟡 | Filtros combinables; autocompletado de equipo y etiqueta |
| 4 | Notificaciones push/email | 🟡 | Aviso del navegador con la página abierta; email pendiente |
| 5 | Filtros por fecha, marca, equipo y severidad | ✅ | |
| 6 | Incidentes: crear, asignar, seguimiento y cierre | ✅ | Con historial y reglas de transición |
| 7 | Plantillas Cisco / Fortinet / Huawei | ✅ | Syslog y endurecimiento |
| 8 | Consola simulada de solo lectura | ✅ | Permitidos y bloqueados |
| 8 | Conexión real por SSH | 📐 | `docs/diseno-ssh-real.md` |
| 8 | Botones de verificación por marca | ✅ | |
| 8 | Detección automática del puerto COM | 🟡 | Lista puertos y propone uno; la sesión es simulada |
| 8 | Macros personalizadas | ✅ | |
| 9 | Política de defensa ante agentes de IA | ✅ | `docs/politica-defensa-ia.md` |
| 10 | MFA | ⬜ | |
| 10 | TLS en la transmisión de logs | 📐 | El receptor UDP no cifra |
| 10 | Roles y permisos granulares | ⬜ | `X-Actor` no se verifica |
| 10 | Alertas en tiempo real ante patrones sospechosos | 🟡 | Etiquetado, auditoría y aviso por severidad |
| 10 | Integración con SIEM | ⬜ | |
| 11 | Informes (PDF/PowerPoint, KPIs) | ⬜ | Los KPIs se ven en el dashboard |
| 12 | API REST para consultar logs | ✅ | |
| 12 | Docker / Kubernetes | ⬜ | |
| 12 | Sistema de etiquetas | 🟡 | Automáticas; sin edición manual |
| 12 | Modo simulación | ✅ | Generador; falta guía de entrenamiento |

## Estructura
```
app/            API, parser, política de comandos, consola simulada y dashboard (static/)
scripts/        carga de datos simulados y envío UDP de prueba
tests/          pruebas funcionales (pytest)
docs/           política de defensa ante IA y diseño de la conexión SSH real
```

## Licencia y autoría
Proyecto académico. Autor: `<tu nombre>` · Docente: Ing. John Harold Pérez Calderón.