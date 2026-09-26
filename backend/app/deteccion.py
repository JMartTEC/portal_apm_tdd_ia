"""
deteccion.py
------------
Reglas deterministas que corren ANTES de preguntarle a un modelo.

Los patrones son los mismos que probo la v1; lo que cambia es de donde leen:
ahora reciben la estructura comun de parsers/base.py, asi que las mismas reglas
aplican a un Word, un PDF, un PowerPoint o un Excel sin duplicar codigo.

Lo que se detecta aqui llega al modelo como contexto YA VERIFICADO, y el
validador le da mas autoridad que a lo que el modelo proponga por su cuenta.
"""

from __future__ import annotations

import re

RE_VERSION = re.compile(
    r"(?:versi[oó]n|version|ver\.?|v)\s*[:\-]?\s*"
    r"(\d+(?:\.\d+){0,2}[a-zA-Z]?)",
    re.IGNORECASE,
)
RE_VERSION_ARCHIVO = re.compile(r"[_\-\s]v(\d+(?:\.\d+){0,2})", re.IGNORECASE)

RE_FECHA_ISO = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
RE_FECHA_TEXTO = re.compile(
    r"\b(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)"
    r"\s+(?:de\s+)?(20\d{2})\b",
    re.IGNORECASE,
)
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

RE_RESPONSABLE = re.compile(
    r"(?:responsable|propietario|owner|autor|elabor[oó]|elaborado por|"
    r"preparado por|aprobado por|revisado por|due[nñ]o)\s*[:\-]\s*"
    r"([^\n\|]{3,80})",
    re.IGNORECASE,
)

# Autores que Word o las herramientas dejan por defecto: no son responsables reales.
AUTORES_GENERICOS = {
    "", "python-docx", "python-pptx", "openpyxl", "libreoffice", "apache poi",
    "usuario", "user", "admin", "administrador", "microsoft office user",
    "windows user", "autor", "unknown", "office", "word", "excel",
    "powerpoint", "adobe acrobat", "microsoft word", "microsoft excel",
}

MARCAS_ESTADO = {
    "Borrador": [r"\bborrador\b", r"\bdraft\b", r"\bwork in progress\b", r"\bwip\b"],
    "En revision": [r"\ben revisi[oó]n\b", r"\bpara revisi[oó]n\b", r"\bin review\b"],
    "Aprobado": [r"\baprobado\b", r"\bapproved\b", r"\bvisto bueno\b"],
    "Vigente": [r"\bvigente\b", r"\bversi[oó]n vigente\b", r"\bliberado\b"],
    "Obsoleto": [r"\bobsoleto\b", r"\bdeprecad[oa]\b", r"\bsuperad[oa] por\b"],
}

MARCAS_CONFIDENCIALIDAD = {
    "Publico": [r"\bp[uú]blico\b", r"\bpublic\b", r"\buso p[uú]blico\b"],
    "Interno": [r"\buso interno\b", r"\binterno\b", r"\binternal use\b"],
    "Confidencial": [r"\bconfidencial\b", r"\bconfidential\b"],
    "Restringido": [r"\brestringid[oa]\b", r"\brestricted\b", r"\buso exclusivo\b"],
}

# ---------------------------------------------------------------------------
# Zonas donde vive la evidencia, ordenadas por confiabilidad
# ---------------------------------------------------------------------------

def _zonas_prioritarias(doc: dict) -> list[tuple[str, str]]:
    """(origen, texto). El orden importa: la primera coincidencia gana."""
    zonas: list[tuple[str, str]] = []

    props = " | ".join(f"{k}={v}" for k, v in doc["propiedades"].items() if v)
    zonas.append(("propiedades del archivo", props))

    # zonas que aporto el parser: portada, encabezado, pie, notas, frontmatter
    for origen, texto in doc["zonas"]:
        zonas.append((origen, texto))

    zonas.append(("nombre del archivo", doc["nombre"]))

    for i, tabla in enumerate(doc["tablas"][:4], start=1):
        etiqueta = f"tabla {i}"
        if tabla.get("hoja"):
            etiqueta = f"hoja '{tabla['hoja']}'"
        # Una tabla de dos columnas es una ficha de control de cambios: se
        # aplana como "clave: valor" para que los patrones la reconozcan.
        # Con " ; " en medio, "Version ; 2.1" no coincidia con nada.
        partes = []
        for fila in tabla["filas"][:12]:
            celdas = [c for c in fila if c]
            if len(celdas) == 2:
                partes.append(f"{celdas[0]}: {celdas[1]}")
            else:
                partes.append(" ; ".join(celdas))
        zonas.append((etiqueta, "\n".join(partes)))

    # los primeros parrafos, por si el parser no marco portada
    zonas.append(("inicio del contenido", "\n".join(doc["parrafos"][:30])))

    return [(o, t) for o, t in zonas if t]


def detectar_candidatos(doc: dict) -> dict:
    """Version, fecha, responsable, estado y confidencialidad por reglas.
    Lo que sale de aqui NO lo tiene que adivinar el modelo."""
    cand: dict[str, dict] = {}
    zonas = _zonas_prioritarias(doc)

    # --- version -----------------------------------------------------------
    for origen, texto in zonas:
        m = RE_VERSION.search(texto)
        if m:
            cand["version"] = {"valor": m.group(1), "evidencia": origen,
                               "metodo": "extraido"}
            break
    if "version" not in cand:
        m = RE_VERSION_ARCHIVO.search(doc["nombre"])
        if m:
            cand["version"] = {"valor": m.group(1),
                               "evidencia": "nombre del archivo",
                               "metodo": "derivado"}

    # --- fecha -------------------------------------------------------------
    # Las propiedades del archivo traen la fecha del ARCHIVO, no la del
    # documento: una plantilla reutilizada arrastra la fecha original. Por eso
    # primero se busca en el contenido, y si solo aparece en propiedades el
    # metodo es "derivado", que no tiene autoridad para sobrescribir al modelo.
    zonas_contenido = [(o, t) for o, t in zonas if o != "propiedades del archivo"]
    for origen, texto in zonas_contenido:
        m = RE_FECHA_ISO.search(texto)
        if m:
            y, mo, d = m.groups()
            cand["fecha"] = {"valor": f"{y}-{int(mo):02d}-{int(d):02d}",
                             "evidencia": origen, "metodo": "extraido"}
            break
        m = RE_FECHA_TEXTO.search(texto)
        if m:
            d, mes, y = m.groups()
            cand["fecha"] = {"valor": f"{y}-{MESES[mes.lower()]:02d}-{int(d):02d}",
                             "evidencia": origen, "metodo": "extraido"}
            break
    if "fecha" not in cand:
        prop_fecha = (doc["propiedades"].get("modificado")
                      or doc["propiedades"].get("creado"))
        if prop_fecha:
            cand["fecha"] = {
                "valor": str(prop_fecha)[:10],
                "evidencia": "fecha de archivo (no es fecha documental confirmada)",
                "metodo": "derivado"}

    # --- responsable -------------------------------------------------------
    for origen, texto in zonas:
        m = RE_RESPONSABLE.search(texto)
        if m:
            valor = m.group(1).strip(" .;-")
            if valor and valor.lower() not in ("", "n/a", "na"):
                cand["responsable"] = {"valor": valor, "evidencia": origen,
                                       "metodo": "extraido"}
                break
    autor = str(doc["propiedades"].get("autor") or "").strip()
    if "responsable" not in cand and autor and autor.lower() not in AUTORES_GENERICOS:
        cand["responsable"] = {"valor": autor,
                               "evidencia": "propiedad autor del archivo",
                               "metodo": "derivado"}

    # --- estado ------------------------------------------------------------
    for origen, texto in zonas:
        bajo = texto.lower()
        for estado, patrones in MARCAS_ESTADO.items():
            if any(re.search(p, bajo) for p in patrones):
                cand["estado"] = {"valor": estado, "evidencia": origen,
                                  "metodo": "extraido"}
                break
        if "estado" in cand:
            break

    # --- confidencialidad --------------------------------------------------
    for origen, texto in zonas:
        bajo = texto.lower()
        for nivel, patrones in MARCAS_CONFIDENCIALIDAD.items():
            if any(re.search(p, bajo) for p in patrones):
                cand["confidencialidad"] = {"valor": nivel, "evidencia": origen,
                                            "metodo": "extraido"}
                break
        if "confidencialidad" in cand:
            break

    return cand


# ---------------------------------------------------------------------------
# Serializacion para el modelo
# ---------------------------------------------------------------------------

def bloque_para_modelo(doc: dict, max_chars: int = 150_000) -> str:
    """Convierte la estructura comun en el texto que ve el modelo,
    conservando la estructura en vez de aplanarlo todo a un chorro de texto."""
    partes = [f"ARCHIVO: {doc['nombre']}  (formato: {doc['formato']})"]

    if doc["n_paginas"]:
        partes.append(f"EXTENSION: {doc['n_paginas']} paginas/hojas/diapositivas")

    props = {k: v for k, v in doc["propiedades"].items() if v}
    if props:
        partes.append("PROPIEDADES DEL ARCHIVO:\n" +
                      "\n".join(f"  - {k}: {v}" for k, v in props.items()))

    for origen, texto in doc["zonas"]:
        if origen != "inicio":
            partes.append(f"{origen.upper()}:\n{texto[:2000]}")

    if doc["encabezados"]:
        partes.append("ESTRUCTURA DE SECCIONES:\n" +
                      "\n".join(f"  - {t}" for t in doc["encabezados"][:60]))

    partes.append("CONTENIDO:\n" + "\n".join(doc["parrafos"]))

    for i, tabla in enumerate(doc["tablas"][:10], start=1):
        etiqueta = f"TABLA {i}"
        if tabla.get("hoja"):
            etiqueta = f"TABLA {i} (hoja '{tabla['hoja']}')"
        filas = "\n".join("  | " + " | ".join(f) for f in tabla["filas"][:15])
        partes.append(f"{etiqueta} ({tabla['n_filas']} filas):\n{filas}")

    if doc["avisos"]:
        partes.append("AVISOS DEL EXTRACTOR:\n" +
                      "\n".join(f"  - {a}" for a in doc["avisos"]))

    texto = "\n\n".join(partes)
    if len(texto) > max_chars:
        mitad = max_chars // 2
        texto = (texto[:mitad] +
                 "\n\n[... contenido intermedio truncado por longitud ...]\n\n" +
                 texto[-mitad:])
    return texto
