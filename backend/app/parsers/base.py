"""
parsers/base.py
---------------
Contrato unico que todo parser debe cumplir.

La v1 solo leia .docx y el parser estaba pegado al resto del codigo. Aqui se
invierte: cada formato es un modulo que devuelve SIEMPRE la misma estructura,
y el resto de la aplicacion (deteccion determinista, prompt, validador,
exportador) no sabe de que formato vino el documento.

Agregar un formato nuevo = un modulo nuevo + una linea en el registro.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Titulos que ponen las herramientas, no las personas. Aparecen en la propiedad
# "titulo" del archivo y no describen nada: PptxGenJS deja su firma en cada
# .pptx que genera, Word deja "Document" en plantillas vacias.
TITULOS_GENERICOS = {
    "pptxgenjs presentation", "powerpoint presentation", "presentation",
    "presentacion de powerpoint", "presentacion1", "document", "documento",
    "documento1", "untitled", "sin titulo", "libro1", "book1", "hoja1",
    "sheet1", "workbook", "libro", "titulo", "title",
}

# Primeras palabras que delatan un encabezado de seccion, no el nombre del
# documento. "Introduccion" es la seccion 1 de medio mundo; como titulo de un
# activo en un indice de busqueda no distingue nada.
SECCIONES_GENERICAS = {
    "introduccion", "indice", "objetivo", "objetivos", "alcance", "resumen",
    "contenido", "contexto", "antecedentes", "proposito", "prologo",
    "presentacion", "generalidades", "definiciones", "glosario",
}


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").lower().strip()


def _es_seccion_generica(titulo: str) -> bool:
    """Un encabezado corto que empieza con una palabra de seccion."""
    palabras = _plano(titulo).replace(".", " ").split()
    if not palabras or len(palabras) > 4:
        return False
    return palabras[0] in SECCIONES_GENERICAS


def _desde_nombre(nombre: str) -> str:
    """Ultimo recurso: el nombre del archivo, legible."""
    base = re.sub(r"\.[^.]+$", "", nombre)
    base = re.sub(r"[_\-]+", " ", base)
    return re.sub(r"\s+", " ", base).strip()


def documento_vacio(nombre: str, extension: str) -> dict[str, Any]:
    """Estructura canonica. Todo parser parte de aqui y llena lo que pueda."""
    return {
        # --- identidad del archivo ---
        "nombre": nombre,
        "extension": extension,
        "formato": "",             # etiqueta legible: Word, PDF, PowerPoint...

        # --- contenido textual ---
        "parrafos": [],            # list[str]
        "titulo_probable": "",     # primer encabezado o nombre del archivo
        "encabezados": [],         # list[str] jerarquia de titulos
        "zonas": [],               # list[(origen, texto)] portada, pie, notas...

        # --- contenido estructurado ---
        "tablas": [],              # list[{"filas": [[str]], "n_filas": int}]

        # --- contenido visual ---
        "imagenes": [],            # list[{"media_type","base64","bytes","origen"}]

        # --- metadatos del archivo ---
        "propiedades": {},         # autor, fechas, titulo... segun el formato

        # --- conteos, para el log y la ficha ---
        "n_parrafos": 0,
        "n_tablas": 0,
        "n_imagenes": 0,
        "n_paginas": 0,

        # --- incidencias del parseo, no del contenido ---
        "avisos": [],              # list[str]
    }


def cerrar(doc: dict[str, Any]) -> dict[str, Any]:
    """Calcula los conteos derivados. Se llama al final de cada parser."""
    doc["n_parrafos"] = len(doc["parrafos"])
    doc["n_tablas"] = len(doc["tablas"])
    doc["n_imagenes"] = len(doc["imagenes"])
    # Prioridad del titulo. El titulo termina en el frontmatter y en el nombre
    # del .md, asi que un titulo malo contamina la busqueda: "Introduccion" no
    # distingue un documento de otro, y "PptxGenJS Presentation" no dice nada.
    #   1. lo que el parser marco explicitamente (estilo Titulo, titulo de la
    #      primera diapositiva)
    #   2. la propiedad del archivo, si no es una firma de herramienta
    #   3. el primer encabezado, si no es un nombre de seccion generico
    #   4. el nombre del archivo, limpio
    if not doc["titulo_probable"]:
        propiedad = str(doc["propiedades"].get("titulo") or "").strip()
        if propiedad and _plano(propiedad) not in TITULOS_GENERICOS:
            doc["titulo_probable"] = propiedad

    if doc["titulo_probable"] and _plano(doc["titulo_probable"]) in TITULOS_GENERICOS:
        doc["titulo_probable"] = ""

    # Solo el PRIMER encabezado puede ser el titulo del documento: si ese es
    # generico, el siguiente tampoco sirve, porque tambien es una seccion.
    # Saltar a "Modelo de gobierno" porque "Introduccion" no valia produce un
    # titulo que describe un capitulo, no el activo.
    if not doc["titulo_probable"] and doc["encabezados"]:
        primero = doc["encabezados"][0].strip()
        if primero and not _es_seccion_generica(primero):
            doc["titulo_probable"] = primero

    if not doc["titulo_probable"]:
        doc["titulo_probable"] = _desde_nombre(doc["nombre"])

    return doc


class FormatoNoSoportado(Exception):
    """El archivo tiene una extension que ningun parser atiende."""


class DocumentoIlegible(Exception):
    """El archivo es del formato correcto pero no se pudo leer."""
