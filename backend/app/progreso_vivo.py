"""
progreso_vivo.py
-----------------
Igual que lotes.py pero para UN solo documento: el trabajo corre en un hilo
aparte y el navegador va preguntando el avance real, etapa por etapa, en vez
de esperar una sola respuesta larga o fingir un avance con un temporizador.

    POST /api/analizar-vivo (o /subir)  -> registra el trabajo, responde un id
    GET  /api/analizar-vivo/{id}        -> el frontend consulta el avance

El estado vive en memoria del proceso, igual que en lotes.py -- deliberado,
la POC no persiste esto y no hace falta.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Analisis:
    id: str
    estado: str = "corriendo"          # corriendo | terminado | error
    etapas: dict = field(default_factory=dict)
    vinculacion: dict | None = None
    resultado: dict | None = None      # el JSON final, mismo formato que /api/analyze-ruta
    error: dict | None = None
    inicio: float = field(default_factory=time.time)
    fin: float = 0.0

    def resumen(self) -> dict:
        return {
            "id": self.id,
            "estado": self.estado,
            "etapas": self.etapas,
            "vinculacion": self.vinculacion,
            "resultado": self.resultado if self.estado == "terminado" else None,
            "error": self.error,
            "segundos_transcurridos": round((self.fin or time.time()) - self.inicio, 1),
        }


_TRABAJOS: dict[str, Analisis] = {}
_CANDADO = threading.Lock()


def crear() -> Analisis:
    analisis = Analisis(id=uuid.uuid4().hex[:12])
    with _CANDADO:
        _TRABAJOS[analisis.id] = analisis
        if len(_TRABAJOS) > 40:
            mas_viejo = min(_TRABAJOS.values(), key=lambda a: a.inicio)
            _TRABAJOS.pop(mas_viejo.id, None)
    return analisis


def obtener(analisis_id: str) -> Analisis | None:
    return _TRABAJOS.get(analisis_id)


def lanzar(analisis: Analisis, trabajo) -> None:
    """Corre `trabajo(analisis)` en un hilo aparte para no bloquear la peticion
    que lo arranco. `trabajo` es responsable de fijar `analisis.estado` en
    "terminado" o "error" y de llenar `resultado` o `error` -- esto solo es
    una red de seguridad por si el hilo muere sin avisar."""
    def _envoltura():
        try:
            trabajo(analisis)
        except Exception as exc:
            analisis.error = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
            analisis.estado = "error"
        finally:
            analisis.fin = time.time()

    threading.Thread(target=_envoltura, daemon=True, name=f"vivo-{analisis.id}").start()
