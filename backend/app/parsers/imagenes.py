"""
parsers/imagenes.py
-------------------
Utilidades compartidas de imagen.

Regla de la POC: las imagenes NO se guardan en disco. Viven en memoria como
base64 mientras dura el analisis y se descartan. Lo que sobrevive es la
descripcion textual que el modelo escribe sobre ellas.

Se filtran las chicas (logos, vinetas, lineas decorativas) porque gastar
tokens de vision en el logo institucional no aporta clasificacion.
"""

from __future__ import annotations

import base64

MIN_BYTES = 12_000     # por debajo de esto casi siempre es decorativo
MAX_IMAGENES = 6       # tope por documento, las mas pesadas primero
MAX_BYTES = 4_000_000  # la API rechaza imagenes gigantes

TIPOS = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
    b"RIFF": "image/webp",
}


def media_type(datos: bytes) -> str:
    for firma, tipo in TIPOS.items():
        if datos.startswith(firma):
            return tipo
    return ""


def empaquetar(datos: bytes, origen: str) -> dict | None:
    """Convierte bytes crudos en el bloque que espera la API. None si se descarta."""
    if len(datos) < MIN_BYTES or len(datos) > MAX_BYTES:
        return None
    tipo = media_type(datos)
    if not tipo:
        return None
    return {
        "media_type": tipo,
        "base64": base64.b64encode(datos).decode("ascii"),
        "bytes": len(datos),
        "origen": origen,
    }


def seleccionar(candidatas: list[dict]) -> list[dict]:
    """Las mas pesadas primero: un diagrama pesa mas que un icono."""
    return sorted(candidatas, key=lambda i: i["bytes"], reverse=True)[:MAX_IMAGENES]
