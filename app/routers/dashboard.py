"""Datos agregados para el dashboard. Las horas se manejan en UTC."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from app.database import db_session
from app.routers.events import BASE_SELECT, _to_event
from app.syslog_parser import SEVERITY_NAMES

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _health(status: str, worst) -> str:
    if status == "inactive":
        return "inactivo"
    if status == "maintenance":
        return "mantenimiento"
    if worst is None:
        return "sin-datos"
    if worst <= 2:
        return "critico"
    if worst <= 4:
        return "alerta"
    return "ok"


@router.get("/summary")
def summary(hours: int = Query(24, ge=1, le=72)):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    buckets = [(now - timedelta(hours=i)).strftime("%Y-%m-%d %H:00")
               for i in range(hours - 1, -1, -1)]
    since = buckets[0] + ":00"
    idx = {b: i for i, b in enumerate(buckets)}

    with db_session() as conn:
        k = conn.execute(
            "SELECT COUNT(*) AS events, COALESCE(SUM(repeat_count),0) AS occurrences, "
            "COALESCE(SUM(CASE WHEN severity <= 2 THEN repeat_count END),0) AS critical, "
            "COALESCE(SUM(CASE WHEN severity <= 3 THEN repeat_count END),0) AS errors, "
            "COALESCE(SUM(CASE WHEN (',' || tags || ',') LIKE '%,sospechoso,%' THEN 1 END),0) AS suspicious "
            "FROM syslog_events WHERE received_at >= ?", (since,)).fetchone()

        by_sev = {i: {"severity": i, "name": SEVERITY_NAMES[i], "events": 0, "occurrences": 0}
                  for i in range(8)}
        for r in conn.execute(
                "SELECT severity, COUNT(*) AS events, SUM(repeat_count) AS occurrences "
                "FROM syslog_events WHERE received_at >= ? GROUP BY severity", (since,)):
            by_sev[r["severity"]].update(events=r["events"], occurrences=r["occurrences"])

        timeline = [{"hour": b, "total": 0, "errors": 0} for b in buckets]
        for r in conn.execute(
                "SELECT strftime('%Y-%m-%d %H:00', received_at) AS h, SUM(repeat_count) AS total, "
                "SUM(CASE WHEN severity <= 3 THEN repeat_count ELSE 0 END) AS errors "
                "FROM syslog_events WHERE received_at >= ? GROUP BY h", (since,)):
            i = idx.get(r["h"])
            if i is not None:
                timeline[i].update(total=r["total"], errors=r["errors"])

        devices = []
        for r in conn.execute(
                "SELECT d.id, d.name, d.ip_address, d.vendor, d.status, d.is_simulated, "
                "MIN(e.severity) AS worst, COALESCE(SUM(e.repeat_count),0) AS occurrences, "
                "MAX(e.received_at) AS last_event "
                "FROM devices d LEFT JOIN syslog_events e "
                "ON e.device_id = d.id AND e.received_at >= ? GROUP BY d.id ORDER BY d.name",
                (since,)):
            devices.append({"id": r["id"], "name": r["name"], "ip_address": r["ip_address"],
                            "vendor": r["vendor"], "status": r["status"],
                            "is_simulated": bool(r["is_simulated"]),
                            "health": _health(r["status"], r["worst"]),
                            "occurrences": r["occurrences"], "last_event": r["last_event"]})

        grid = {d["name"]: [0] * hours for d in devices}
        for r in conn.execute(
                "SELECT COALESCE(d.name, '(desconocido)') AS device, "
                "strftime('%Y-%m-%d %H:00', e.received_at) AS h, SUM(e.repeat_count) AS c "
                "FROM syslog_events e LEFT JOIN devices d ON d.id = e.device_id "
                "WHERE e.received_at >= ? GROUP BY device, h", (since,)):
            i = idx.get(r["h"])
            if i is not None:
                grid.setdefault(r["device"], [0] * hours)[i] = r["c"]
        heat = {"devices": [{"name": n, "counts": c} for n, c in sorted(grid.items())],
                "max": max((max(c) for c in grid.values()), default=0)}

        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM incidents GROUP BY status")}
        incidents = {"open": counts.get("open", 0),
                     "active": sum(n for s, n in counts.items() if s not in ("resolved", "closed")),
                     "total": sum(counts.values())}

        recent = [_to_event(r) for r in conn.execute(
            BASE_SELECT + " WHERE e.severity <= 3 ORDER BY e.id DESC LIMIT 6").fetchall()]

    return {"hours": hours, "kpis": dict(k), "by_severity": list(by_sev.values()),
            "timeline": timeline, "devices": devices, "heatmap": heat,
            "incidents": incidents, "recent": recent}