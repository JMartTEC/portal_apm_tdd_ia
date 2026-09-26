"""
lotes.py
--------
Escaneo de carpetas y ejecucion en segundo plano.

Un lote no se puede resolver en una peticion HTTP: 40 documentos por 25 s cada
uno son 17 minutos y cualquier proxy corta antes. Por eso el flujo es:

    POST /api/lote        -> registra el trabajo, responde un id al instante
    GET  /api/lote/{id}   -> el frontend consulta el avance cuando quiere

El estado vive en memoria del proceso. Es deliberado: la POC no persiste. Si el
servidor se reinicia, los lotes en curso se pierden, pero los .md y .json que
alcanzo a escribir siguen en disco.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import parsers

# Carpetas que nunca se recorren: son ruido, no conocimiento.
CARPETAS_IGNORADAS = {
    "_ia-ready", "__macosx", "node_modules", ".git", ".svn", "venv", ".venv",
    "__pycache__", ".idea", ".vscode", "_to_delete", "$recycle.bin",
}

# Prefijos de archivo que se saltan: temporales de Office y ocultos.
PREFIJOS_IGNORADOS = ("~$", ".", "_arranque")

MAX_ARCHIVOS = 500
MAX_BYTES_ARCHIVO = 60 * 1024 * 1024


# ---------------------------------------------------------------------------
# Exploracion
# ---------------------------------------------------------------------------

def explorar(raiz: Path, recursivo: bool = True) -> dict:
    """Lista que se procesaria, SIN procesar nada. Alimenta la vista previa
    del paso 2: el usuario ve el alcance antes de gastar 20 minutos."""
    if not raiz.exists():
        raise FileNotFoundError(f"La ruta no existe: {raiz}")
    if not raiz.is_dir():
        raise NotADirectoryError(f"La ruta no es una carpeta: {raiz}")

    aceptados: list[dict] = []
    descartados: list[dict] = []

    iterador = raiz.rglob("*") if recursivo else raiz.glob("*")
    for ruta in sorted(iterador):
        if len(aceptados) >= MAX_ARCHIVOS:
            descartados.append({"nombre": "...", "motivo":
                                f"Se alcanzo el tope de {MAX_ARCHIVOS} archivos."})
            break
        if not ruta.is_file():
            continue
        if any(parte.lower() in CARPETAS_IGNORADAS for parte in ruta.parts):
            continue
        if ruta.name.lower().startswith(PREFIJOS_IGNORADOS):
            continue

        relativa = str(ruta.relative_to(raiz))
        try:
            tam = ruta.stat().st_size
        except OSError as exc:
            descartados.append({"nombre": relativa, "motivo": f"No se pudo leer: {exc}"})
            continue

        if not parsers.soportado(ruta.name):
            descartados.append({"nombre": relativa,
                                "motivo": f"Formato no soportado ({ruta.suffix or 'sin extension'})"})
            continue
        if tam == 0:
            descartados.append({"nombre": relativa, "motivo": "Archivo vacio"})
            continue
        if tam > MAX_BYTES_ARCHIVO:
            descartados.append({"nombre": relativa,
                                "motivo": f"Excede {MAX_BYTES_ARCHIVO // 1024 // 1024} MB"})
            continue

        aceptados.append({
            "nombre": relativa,
            "ruta": str(ruta),
            "extension": ruta.suffix.lower(),
            "bytes": tam,
            "requiere_vision": ruta.suffix.lower() in parsers.REQUIEREN_VISION,
        })

    return {
        "raiz": str(raiz),
        "recursivo": recursivo,
        "aceptados": aceptados,
        "descartados": descartados,
        "n_aceptados": len(aceptados),
        "n_descartados": len(descartados),
    }


# ---------------------------------------------------------------------------
# Estado de un lote
# ---------------------------------------------------------------------------

@dataclass
class Lote:
    id: str
    raiz: str
    total: int
    estado: str = "pendiente"          # pendiente | corriendo | terminado | cancelado
    procesados: int = 0
    con_error: int = 0
    actual: str = ""
    inicio: float = field(default_factory=time.time)
    fin: float = 0.0
    carpeta_salida: str = ""
    resultados: list = field(default_factory=list)
    cancelar: bool = False

    def resumen(self) -> dict:
        transcurrido = (self.fin or time.time()) - self.inicio
        restantes = max(self.total - self.procesados, 0)
        por_doc = transcurrido / self.procesados if self.procesados else 0
        return {
            "id": self.id,
            "raiz": self.raiz,
            "estado": self.estado,
            "total": self.total,
            "procesados": self.procesados,
            "con_error": self.con_error,
            "actual": self.actual,
            "segundos_transcurridos": round(transcurrido, 1),
            "segundos_estimados_restantes": round(por_doc * restantes) if por_doc else None,
            "carpeta_salida": self.carpeta_salida,
            "resultados": self.resultados,
        }


_LOTES: dict[str, Lote] = {}
_CANDADO = threading.Lock()


def crear(raiz: str, total: int, carpeta_salida: str) -> Lote:
    lote = Lote(id=uuid.uuid4().hex[:12], raiz=raiz, total=total,
                carpeta_salida=carpeta_salida)
    with _CANDADO:
        _LOTES[lote.id] = lote
        # no acumular lotes viejos indefinidamente
        if len(_LOTES) > 20:
            mas_viejo = min(_LOTES.values(), key=lambda l: l.inicio)
            _LOTES.pop(mas_viejo.id, None)
    return lote


def obtener(lote_id: str) -> Lote | None:
    return _LOTES.get(lote_id)


def cancelar(lote_id: str) -> bool:
    lote = _LOTES.get(lote_id)
    if not lote or lote.estado in ("terminado", "cancelado"):
        return False
    lote.cancelar = True
    return True


def lanzar(lote: Lote, trabajo) -> None:
    """Corre `trabajo(lote)` en un hilo aparte para no bloquear la peticion."""
    def _envoltura():
        lote.estado = "corriendo"
        try:
            trabajo(lote)
        except Exception as exc:  # el hilo nunca debe morir en silencio
            lote.resultados.append({
                "nombre": "(lote)", "ok": False,
                "error": f"{type(exc).__name__}: {exc}"})
            lote.con_error += 1
        finally:
            lote.fin = time.time()
            lote.actual = ""
            if lote.estado != "cancelado":
                lote.estado = "terminado"

    threading.Thread(target=_envoltura, daemon=True, name=f"lote-{lote.id}").start()
