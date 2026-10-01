"""Modelos de validación. Todo dato que entra a la API se trata como NO confiable."""
from ipaddress import ip_address
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

Vendor = Literal["cisco", "fortinet", "huawei", "other"]
Status = Literal["active", "inactive", "maintenance"]

# Solo letras, números, punto, guion y guion bajo: evita caracteres de inyección.
NAME_PATTERN = r"^[A-Za-z0-9._-]+$"


def _check_ip(value: str) -> str:
    """Acepta IPv4/IPv6 válidas; rechaza cualquier otra cosa."""
    try:
        ip_address(value)
    except ValueError:
        raise ValueError("Dirección IP inválida")
    return value


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=NAME_PATTERN)
    ip_address: str
    vendor: Vendor
    model: Optional[str] = Field(default=None, max_length=64)
    os_version: Optional[str] = Field(default=None, max_length=64)
    location: Optional[str] = Field(default=None, max_length=128)
    status: Status = "active"
    is_simulated: bool = True  # por defecto, todo dato es simulado

    _ip = field_validator("ip_address")(_check_ip)


class DeviceUpdate(BaseModel):
    """Actualización parcial: solo se modifican los campos enviados."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=NAME_PATTERN)
    ip_address: Optional[str] = None
    vendor: Optional[Vendor] = None
    model: Optional[str] = Field(default=None, max_length=64)
    os_version: Optional[str] = Field(default=None, max_length=64)
    location: Optional[str] = Field(default=None, max_length=128)
    status: Optional[Status] = None
    is_simulated: Optional[bool] = None

    @field_validator("ip_address")
    @classmethod
    def _ip(cls, v):
        return _check_ip(v) if v is not None else v


class DeviceOut(BaseModel):
    id: int
    name: str
    ip_address: str
    vendor: str
    model: Optional[str]
    os_version: Optional[str]
    location: Optional[str]
    status: str
    is_simulated: bool
    updated_at: str