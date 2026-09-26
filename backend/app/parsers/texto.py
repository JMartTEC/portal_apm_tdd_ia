"""parsers/texto.py -- .md, .txt, .csv, .json, .html"""

from __future__ import annotations

import csv
import io
import re

from .base import DocumentoIlegible, cerrar, documento_vacio

EXTENSIONES = {".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".html", ".htm"}
MAX_BYTES = 5_000_000

FORMATOS = {
    ".md": "Markdown", ".markdown": "Markdown", ".txt": "Texto",
    ".csv": "CSV", ".tsv": "TSV", ".json": "JSON",
    ".html": "HTML", ".htm": "HTML",
}


def _leer(ruta: str) -> str:
    crudo = open(ruta, "rb").read(MAX_BYTES)
    for codificacion in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return crudo.decode(codificacion)
        except UnicodeDecodeError:
            continue
    raise DocumentoIlegible("No se pudo determinar la codificacion del archivo.")


def parse(ruta: str, nombre: str, extension: str = "") -> dict:
    ext = (extension or "." + nombre.rsplit(".", 1)[-1]).lower()
    d = documento_vacio(nombre, ext)
    d["formato"] = FORMATOS.get(ext, "Texto")

    contenido = _leer(ruta)

    if ext in (".csv", ".tsv"):
        delimitador = "\t" if ext == ".tsv" else ","
        filas = []
        for i, fila in enumerate(csv.reader(io.StringIO(contenido), delimiter=delimitador)):
            if i >= 200:
                d["avisos"].append("El archivo se trunco a 200 filas.")
                break
            if any(c.strip() for c in fila):
                filas.append([c.strip() for c in fila[:30]])
        if filas:
            d["tablas"].append({"filas": filas, "n_filas": len(filas)})
            d["parrafos"].append("Columnas: " + ", ".join(c for c in filas[0] if c))
        return cerrar(d)

    if ext in (".html", ".htm"):
        contenido = re.sub(r"<script.*?</script>|<style.*?</style>", " ",
                           contenido, flags=re.DOTALL | re.IGNORECASE)
        for m in re.finditer(r"<h[1-6][^>]*>(.*?)</h[1-6]>", contenido,
                             flags=re.DOTALL | re.IGNORECASE):
            titulo = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if titulo:
                d["encabezados"].append(titulo)
        contenido = re.sub(r"<[^>]+>", "\n", contenido)

    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        d["parrafos"].append(linea)
        if ext in (".md", ".markdown") and linea.startswith("#"):
            d["encabezados"].append(linea.lstrip("# ").strip())

    # el frontmatter YAML de un .md ya trae metadatos declarados: es evidencia
    if ext in (".md", ".markdown") and contenido.lstrip().startswith("---"):
        cierre = contenido.find("\n---", 3)
        if cierre > 0:
            d["zonas"].append(("frontmatter", contenido[:cierre]))

    d["zonas"].append(("inicio", "\n".join(d["parrafos"][:25])))
    return cerrar(d)
