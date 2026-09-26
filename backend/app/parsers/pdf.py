"""parsers/pdf.py -- .pdf"""

from __future__ import annotations

from pypdf import PdfReader

from . import imagenes as img
from .base import DocumentoIlegible, cerrar, documento_vacio

EXTENSIONES = {".pdf"}
MAX_PAGINAS = 120


def parse(ruta: str, nombre: str) -> dict:
    d = documento_vacio(nombre, ".pdf")
    d["formato"] = "PDF"
    try:
        lector = PdfReader(ruta)
    except Exception as exc:
        raise DocumentoIlegible(f"No se pudo abrir el PDF: {exc}") from None

    if lector.is_encrypted:
        try:
            lector.decrypt("")
        except Exception:
            raise DocumentoIlegible(
                "El PDF esta protegido con contrasena.") from None

    paginas = lector.pages
    d["n_paginas"] = len(paginas)
    if len(paginas) > MAX_PAGINAS:
        d["avisos"].append(
            f"El PDF tiene {len(paginas)} paginas; solo se leyeron las primeras "
            f"{MAX_PAGINAS}.")

    candidatas = []
    for i, pagina in enumerate(paginas[:MAX_PAGINAS], start=1):
        try:
            texto = pagina.extract_text() or ""
        except Exception:
            texto = ""
        for linea in texto.splitlines():
            linea = linea.strip()
            if linea:
                d["parrafos"].append(linea)
        if i == 1 and texto.strip():
            d["zonas"].append(("portada", texto.strip()[:3000]))

        # imagenes incrustadas: en un PDF tecnico suelen ser los diagramas
        try:
            for recurso in pagina.images:
                paquete = img.empaquetar(recurso.data, f"pagina {i}")
                if paquete:
                    candidatas.append(paquete)
        except Exception:
            pass

    d["imagenes"] = img.seleccionar(candidatas)

    # Un PDF sin texto extraible es un escaneo: decirlo, no fingir que esta vacio.
    if not d["parrafos"]:
        d["avisos"].append(
            "El PDF no tiene texto extraible. Probablemente es un escaneo y "
            "necesitaria OCR, que esta POC no hace.")

    meta = lector.metadata or {}
    d["propiedades"] = {
        "titulo": str(meta.get("/Title", "") or ""),
        "autor": str(meta.get("/Author", "") or ""),
        "creado": str(meta.get("/CreationDate", "") or ""),
        "modificado": str(meta.get("/ModDate", "") or ""),
        "productor": str(meta.get("/Producer", "") or ""),
        "asunto": str(meta.get("/Subject", "") or ""),
    }

    # heuristica de encabezados: lineas cortas en mayusculas o numeradas
    for linea in d["parrafos"][:400]:
        if 3 < len(linea) < 90 and (
                linea.isupper() or linea[:2].strip().rstrip(".").isdigit()):
            d["encabezados"].append(linea)

    return cerrar(d)
