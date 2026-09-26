"""Modelos de intercambio de la POC. No hay modelos de persistencia: no se persiste."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Relacion(BaseModel):
    tipo: str
    nombre: str


class Evidencia(BaseModel):
    metodo: str
    origen: str
    cita: str = ""


class ActivoIAReady(BaseModel):
    id: str
    tipo: str
    descripcion: str
    version: str
    estado: str
    responsable: str
    fecha: str
    fuente: str
    confidencialidad: str
    contexto: dict[str, str]
    relaciones: list[Relacion] = Field(default_factory=list)
    trazabilidad: str
    evidencias: dict[str, Evidencia] = Field(default_factory=dict)
    confianza: dict[str, int] = Field(default_factory=dict)
    niveles: dict[str, str] = Field(default_factory=dict)
    requiere_revision: list[str] = Field(default_factory=list)
    observaciones: list[str] = Field(default_factory=list)


class RespuestaAnalisis(BaseModel):
    ok: bool
    duracion_segundos: float
    activo: dict[str, Any]


class SolicitudValidacion(BaseModel):
    activo: dict[str, Any]
    decision: str = "aceptado"          # aceptado | pendiente
    comentario: str = ""


class RespuestaValidacion(BaseModel):
    ok: bool
    mensaje: str
    decision: str
    campos_pendientes: list[str] = Field(default_factory=list)
