"""parsers/imagen_suelta.py -- .png, .jpg, .webp, .gif como documento"""

from __future__ import annotations

from . import imagenes as img
from .base import DocumentoIlegible, cerrar, documento_vacio

EXTENSIONES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_BYTES = 8_000_000


def parse(ruta: str, nombre: str, extension: str = "") -> dict:
    ext = (extension or "." + nombre.rsplit(".", 1)[-1]).lower()
    d = documento_vacio(nombre, ext)
    d["formato"] = "Imagen"

    datos = open(ruta, "rb").read(MAX_BYTES)
    if not datos:
        raise DocumentoIlegible("El archivo de imagen esta vacio.")

    tipo = img.media_type(datos)
    if not tipo:
        raise DocumentoIlegible("El archivo no es una imagen reconocible.")

    import base64
    d["imagenes"] = [{
        "media_type": tipo,
        "base64": base64.b64encode(datos).decode("ascii"),
        "bytes": len(datos),
        "origen": "archivo completo",
    }]

    # Una imagen no tiene texto. El unico contexto previo es su nombre, y eso
    # se dice explicitamente para que el modelo no invente contenido.
    d["parrafos"].append(
        f"Este activo es una imagen sin texto extraible. Nombre del archivo: "
        f"{nombre}. Toda la clasificacion debe salir de lo que se vea en ella.")
    d["avisos"].append(
        "Es una imagen: solo se puede clasificar con un modelo de vision "
        "(AI_MODO=claude). En modo local quedara sin clasificar.")
    d["n_paginas"] = 1
    return cerrar(d)
