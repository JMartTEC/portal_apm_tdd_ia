"""parsers/word.py -- .docx"""

from __future__ import annotations

import zipfile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from . import imagenes as img
from .base import DocumentoIlegible, cerrar, documento_vacio

EXTENSIONES = {".docx"}


def _iter_bloques(doc: Document):
    """Recorre parrafos y tablas en el orden real del documento."""
    cuerpo = doc.element.body
    for hijo in cuerpo.iterchildren():
        if hijo.tag.endswith("}p"):
            yield Paragraph(hijo, doc)
        elif hijo.tag.endswith("}tbl"):
            yield Table(hijo, doc)


def parse(ruta: str, nombre: str) -> dict:
    d = documento_vacio(nombre, ".docx")
    d["formato"] = "Word"
    try:
        doc = Document(ruta)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DocumentoIlegible(f"No se pudo abrir el .docx: {exc}") from None

    for bloque in _iter_bloques(doc):
        if isinstance(bloque, Paragraph):
            texto = bloque.text.strip()
            if not texto:
                continue
            d["parrafos"].append(texto)
            estilo = (bloque.style.name if bloque.style else "").lower()
            if estilo in ("title", "titulo", "título") and not d["titulo_probable"]:
                # estilo Titulo: es el nombre del documento, no una seccion
                d["titulo_probable"] = texto
            elif estilo.startswith(("heading", "titulo", "título", "encabezado")):
                d["encabezados"].append(texto)
        else:
            filas = [[c.text.strip() for c in f.cells] for f in bloque.rows]
            filas = [f for f in filas if any(f)]
            if filas:
                d["tablas"].append({"filas": filas, "n_filas": len(filas)})

    # portada: lo primero que aparece suele traer version, estado y responsable
    d["zonas"].append(("portada", "\n".join(d["parrafos"][:25])))

    for seccion in doc.sections:
        for cual, parte in (("encabezado", seccion.header), ("pie", seccion.footer)):
            texto = "\n".join(p.text.strip() for p in parte.paragraphs if p.text.strip())
            if texto:
                d["zonas"].append((cual, texto))

    props = doc.core_properties
    d["propiedades"] = {
        "titulo": props.title or "",
        "autor": props.author or "",
        "ultimo_modificado_por": props.last_modified_by or "",
        "creado": props.created.isoformat() if props.created else "",
        "modificado": props.modified.isoformat() if props.modified else "",
        "categoria": props.category or "",
        "comentarios": props.comments or "",
    }

    candidatas = []
    for rel in doc.part.rels.values():
        if "image" not in rel.reltype:
            continue
        try:
            paquete = img.empaquetar(rel.target_part.blob, "imagen incrustada")
        except Exception:
            continue
        if paquete:
            candidatas.append(paquete)
    d["imagenes"] = img.seleccionar(candidatas)

    return cerrar(d)
