"""CRUD del inventario de equipos."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query, Response
from app.audit import write_audit
from app.database import db_session
from app.schemas import DeviceCreate, DeviceOut, DeviceUpdate, Status, Vendor

router = APIRouter(prefix="/api/devices", tags=["Inventario"])

# Campos que no admiten NULL en la base de datos.
REQUIRED_FIELDS = ("name", "ip_address", "vendor", "status", "is_simulated")


def _get_or_404(conn: sqlite3.Connection, device_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    return row


@router.get("", response_model=list[DeviceOut])
def list_devices(
    vendor: Optional[Vendor] = None,
    status: Optional[Status] = None,
    q: Optional[str] = Query(None, max_length=64, description="Busca en nombre, IP o ubicación"),
):
    sql, params = "SELECT * FROM devices WHERE 1=1", []
    if vendor:
        sql += " AND vendor = ?"
        params.append(vendor)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (name LIKE ? OR ip_address LIKE ? OR location LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY name"
    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [DeviceOut(**dict(r)) for r in rows]


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: int):
    with db_session() as conn:
        return DeviceOut(**dict(_get_or_404(conn, device_id)))


@router.post("", response_model=DeviceOut, status_code=201)
def create_device(device: DeviceCreate, x_actor: str = Header(default="anonymous")):
    data = device.model_dump()
    data["is_simulated"] = int(data["is_simulated"])
    with db_session() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO devices (name, ip_address, vendor, model, os_version, "
                "location, status, is_simulated) VALUES (:name, :ip_address, :vendor, "
                ":model, :os_version, :location, :status, :is_simulated)", data)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Ya existe un equipo con ese nombre")
        new_id = cur.lastrowid
        write_audit(conn, x_actor, "device.create", "devices", new_id, data)
        return DeviceOut(**dict(_get_or_404(conn, new_id)))


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(device_id: int, changes: DeviceUpdate,
                  x_actor: str = Header(default="anonymous")):
    data = changes.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No se enviaron cambios")
    for field in REQUIRED_FIELDS:
        if field in data and data[field] is None:
            raise HTTPException(status_code=422, detail=f"'{field}' no puede ser nulo")
    if "is_simulated" in data:
        data["is_simulated"] = int(data["is_simulated"])

    with db_session() as conn:
        old = _get_or_404(conn, device_id)
        # Las claves salen de DeviceUpdate (campos fijos validados), no del usuario,
        # por eso es seguro construir el SET dinámicamente. Los VALORES van parametrizados.
        sets = ", ".join(f"{k} = :{k}" for k in data)
        try:
            conn.execute(
                f"UPDATE devices SET {sets}, updated_at = datetime('now') WHERE id = :id",
                {**data, "id": device_id})
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Ya existe un equipo con ese nombre")
        write_audit(conn, x_actor, "device.update", "devices", device_id,
                    {"antes": {k: old[k] for k in data}, "despues": data})
        return DeviceOut(**dict(_get_or_404(conn, device_id)))


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: int, x_actor: str = Header(default="anonymous")):
    with db_session() as conn:
        old = _get_or_404(conn, device_id)
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        # Los eventos e incidentes asociados se conservan (device_id queda en NULL).
        write_audit(conn, x_actor, "device.delete", "devices", device_id, dict(old))
    return Response(status_code=204)