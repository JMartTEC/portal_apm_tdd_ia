"""
parsers
-------
Registro de formatos. Es la unica pieza que sabe que extension va con que modulo.

Cada parser devuelve la estructura de base.documento_vacio(), asi que el resto
de la aplicacion trabaja igual con un Word, un PDF o una hoja de Excel.
"""

from __future__ import annotations

from pathlib import Path

from .base import DocumentoIlegible, FormatoNoSoportado, documento_vacio
from . import excel, imagen_suelta, pdf, powerpoint, texto, word

MODULOS = (word, pdf, powerpoint, excel, texto, imagen_suelta)

# extension -> modulo
REGISTRO: dict[str, object] = {}
for _m in MODULOS:
    for _ext in _m.EXTENSIONES:
        REGISTRO[_ext] = _m

EXTENSIONES_SOPORTADAS = sorted(REGISTRO)

# Formatos que solo se clasifican bien con un modelo de vision.
REQUIEREN_VISION = set(imagen_suelta.EXTENSIONES)

# Nunca se procesan: macros y binarios que no aportan conocimiento.
BLOQUEADAS = {".docm", ".xlsm_macro", ".exe", ".dll", ".msi", ".bat", ".ps1"}


def catalogo() -> list[dict]:
    """Para que el frontend muestre que acepta, sin duplicar la lista."""
    vistos, salida = set(), []
    for modulo in MODULOS:
        etiqueta = modulo.__name__.rsplit(".", 1)[-1]
        if etiqueta in vistos:
            continue
        vistos.add(etiqueta)
        salida.append({
            "modulo": etiqueta,
            "extensiones": sorted(modulo.EXTENSIONES),
            "requiere_vision": bool(modulo.EXTENSIONES & REQUIEREN_VISION),
        })
    return salida


def soportado(nombre: str) -> bool:
    return Path(nombre).suffix.lower() in REGISTRO


def parse(ruta: str, nombre: str) -> dict:
    """Despacha al parser que corresponda. Lanza FormatoNoSoportado o
    DocumentoIlegible; nunca devuelve una estructura a medias."""
    extension = Path(nombre).suffix.lower()

    if extension in BLOQUEADAS:
        raise FormatoNoSoportado(
            f"Los archivos {extension} no se procesan por seguridad.")

    modulo = REGISTRO.get(extension)
    if modulo is None:
        raise FormatoNoSoportado(
            f"Formato no soportado ({extension or 'sin extension'}). "
            f"Aceptados: {', '.join(EXTENSIONES_SOPORTADAS)}.")

    try:
        # texto e imagen_suelta reciben la extension para no re-deducirla
        if modulo in (texto, imagen_suelta):
            doc = modulo.parse(ruta, nombre, extension)
        else:
            doc = modulo.parse(ruta, nombre)
    except (DocumentoIlegible, FormatoNoSoportado):
        raise
    except Exception as exc:
        raise DocumentoIlegible(
            f"{type(exc).__name__} al leer el archivo: {exc}") from None

    if not doc["parrafos"] and not doc["tablas"] and not doc["imagenes"]:
        raise DocumentoIlegible(
            "El archivo no contiene texto, tablas ni imagenes que analizar.")
    return doc
