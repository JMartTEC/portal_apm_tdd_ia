"""
exportador.py
-------------
Convierte un activo validado en los dos artefactos que consume una solucion RAG.

  .json  la ficha completa, para un indice o una base de datos.
  .md    frontmatter YAML + contenido, que es el formato que ingieren
         LangChain, LlamaIndex, Obsidian y la mayoria de los pipelines de
         busqueda semantica sin necesidad de un conector a medida.

Por que el .md importa: en un indice vectorial el frontmatter se vuelve
METADATOS FILTRABLES y el cuerpo se vuelve los CHUNKS. Eso permite preguntas
como "que dice la arquitectura vigente de facturacion" y que el motor descarte
por metadato los borradores y los documentos obsoletos, en vez de recuperarlos
por parecido de texto. Un JSON suelto no le sirve a la mayoria de los
ingestores sin escribir codigo; un .md con frontmatter si.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import campos as cat_campos

CARPETA_SALIDA = "_ia-ready"

# Campos que se vuelven filtros en el indice. El orden es el de lectura humana.
ORDEN_FRONTMATTER = [
    "id", "titulo", "tipo", "estado", "version", "fecha", "responsable",
    "confidencialidad", "fuente", "dominio", "contexto_funcional",
    "contexto_tecnico", "proceso_relacionado", "sistemas", "relaciones",
    "diagramas", "apm_grupos", "apm_criticos", "tdd_bloques", "tdd_criticos",
    "apm_llenos", "apm_total", "tdd_llenos", "tdd_total",
    "archivo_origen", "formato", "confianza_global",
    "requiere_revision", "generado_por", "generado_en",
]


# ---------------------------------------------------------------------------
# YAML minimo
# ---------------------------------------------------------------------------
# Se emite a mano en vez de usar PyYAML para controlar el orden de las llaves,
# forzar comillas donde hacen falta y no arrastrar una dependencia mas.

def _escapar(valor) -> str:
    """Escalar YAML entre comillas SIMPLES.

    Con comillas dobles YAML trata la barra invertida como escape, asi que una
    ruta de Windows rompe el frontmatter entero: en "C:\\Users\\..." la
    secuencia \\U arranca un escape unicode invalido y el documento deja de
    parsear. En comillas simples todo es literal y lo unico que hay que
    escapar es la propia comilla, duplicandola.
    """
    texto = str(valor).replace('\r', ' ').replace('\n', ' ').strip()
    return "'" + texto.replace("'", "''") + "'"


def _emitir(clave: str, valor, indent: int = 0) -> list[str]:
    pad = " " * indent
    if valor is None or valor == "" or valor == []:
        return [f"{pad}{clave}: []"] if isinstance(valor, list) else [f"{pad}{clave}: ''"]
    if isinstance(valor, bool):
        return [f"{pad}{clave}: {'true' if valor else 'false'}"]
    if isinstance(valor, (int, float)):
        return [f"{pad}{clave}: {valor}"]
    if isinstance(valor, list):
        if all(isinstance(v, str) for v in valor):
            return [f"{pad}{clave}: [" + ", ".join(_escapar(v) for v in valor) + "]"]
        lineas = [f"{pad}{clave}:"]
        for item in valor:
            if isinstance(item, dict):
                primera = True
                for k, v in item.items():
                    marca = "- " if primera else "  "
                    lineas.append(f"{pad}  {marca}{k}: {_escapar(v)}")
                    primera = False
            else:
                lineas.append(f"{pad}  - {_escapar(item)}")
        return lineas
    return [f"{pad}{clave}: {_escapar(valor)}"]


# ---------------------------------------------------------------------------
# Nombres de archivo
# ---------------------------------------------------------------------------

def slug(texto: str, maximo: int = 60) -> str:
    texto = unicodedata.normalize("NFD", str(texto))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return (texto[:maximo].rstrip("-")) or "activo"


def nombre_base(activo: dict) -> str:
    """id + titulo: ordena por identificador y sigue siendo legible."""
    doc = activo.get("_documento", {})
    titulo = (activo.get("titulo")
              or Path(doc.get("nombre_archivo", "")).stem
              or activo.get("descripcion", ""))
    return f"{slug(activo.get('id', 'activo'), 20)}_{slug(titulo)}"


# ---------------------------------------------------------------------------
# Construccion del frontmatter
# ---------------------------------------------------------------------------

def _total_real(activo: dict, fuente: str) -> int:
    """El total de campos de referencia para el frontmatter. Si el documento
    quedo identificado con un aplicativo real, es el total de columnas
    ESCRIBIBLES de ese aplicativo (_llenado); si no, se cae al conteo de la
    plantilla generica de siempre, para no dejar el dato en cero."""
    resumen = ((activo.get("_llenado") or {}).get(fuente) or {}).get("resumen") or {}
    return resumen.get("total") or cat_campos.total(fuente)


def _frontmatter(activo: dict, ruta_origen: str = "") -> dict:
    contexto = activo.get("contexto", {}) or {}
    doc = activo.get("_documento", {}) or {}
    uso = activo.get("_uso", {}) or {}
    confianzas = [v for v in (activo.get("confianza") or {}).values()
                  if isinstance(v, (int, float))]

    sistemas = [s.strip() for s in
                str(contexto.get("sistemas_involucrados", "")).split(",")
                if s.strip() and not s.strip().lower().startswith("no identificad")]

    return {
        "id": activo.get("id", ""),
        "titulo": activo.get("titulo") or Path(doc.get("nombre_archivo", "")).stem,
        "tipo": activo.get("tipo", ""),
        "estado": activo.get("estado", ""),
        "version": activo.get("version", ""),
        "fecha": activo.get("fecha", ""),
        "responsable": activo.get("responsable", ""),
        "confidencialidad": activo.get("confidencialidad", ""),
        "fuente": activo.get("fuente", ""),
        "dominio": contexto.get("dominio", ""),
        "contexto_funcional": contexto.get("contexto_funcional", ""),
        "contexto_tecnico": contexto.get("contexto_tecnico", ""),
        "proceso_relacionado": contexto.get("proceso_relacionado", ""),
        "sistemas": sistemas,
        "relaciones": [{"tipo": r.get("tipo", ""), "nombre": r.get("nombre", "")}
                       for r in (activo.get("relaciones") or [])],
        "diagramas": [d.get("titulo", "") for d in (activo.get("diagramas") or [])],
        # Dos ejes filtrables: que grupos toca, y cuales de esos son criticos.
        # Permite consultas como "damelo todo lo que documenta Seguridad de TDD".
        "apm_grupos": [f["grupo"] for f in (activo.get("apm") or [])],
        "apm_criticos": [f["grupo"] for f in (activo.get("apm") or [])
                         if f.get("nivel") == "Critico"
                         and f.get("cobertura") == "Documentado"],
        "tdd_bloques": [f["grupo"] for f in (activo.get("tdd") or [])],
        "tdd_criticos": [f["grupo"] for f in (activo.get("tdd") or [])
                         if f.get("nivel") == "Critico"
                         and f.get("cobertura") == "Documentado"],
        # Cuantos campos de cada plantilla quedaron llenos. Sirve de filtro
        # directo: "damelo todo lo que tiene menos de la mitad de APM".
        "apm_llenos": len([v for v in (activo.get("ficha_apm") or {}).values() if v]),
        "apm_total": _total_real(activo, "apm"),
        "tdd_llenos": len([v for v in (activo.get("ficha_tdd") or {}).values() if v]),
        "tdd_total": _total_real(activo, "tdd"),
        "archivo_origen": ruta_origen or doc.get("nombre_archivo", ""),
        "formato": doc.get("formato", ""),
        "confianza_global": round(sum(confianzas) / len(confianzas)) if confianzas else 0,
        "requiere_revision": list(activo.get("requiere_revision") or []),
        "generado_por": f"{uso.get('proveedor', 'claude')}/{uso.get('modelo', '')}".strip("/"),
        "generado_en": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def a_markdown(activo: dict, texto_documento: str = "",
               ruta_origen: str = "") -> str:
    fm = _frontmatter(activo, ruta_origen)

    lineas = ["---"]
    for clave in ORDEN_FRONTMATTER:
        lineas.extend(_emitir(clave, fm.get(clave)))
    lineas.append("---")
    lineas.append("")

    lineas.append(f"# {fm['titulo'] or 'Activo de conocimiento'}")
    lineas.append("")

    if activo.get("descripcion"):
        lineas += ["## Resumen", "", activo["descripcion"], ""]

    # Contexto en prosa: en un chunk suelto, una tabla de ejes no dice nada,
    # pero una frase completa si es recuperable por similitud semantica.
    ctx = activo.get("contexto", {}) or {}
    utiles = [(k.replace("_", " "), v) for k, v in ctx.items()
              if v and not str(v).lower().startswith("no identificad")]
    if utiles:
        lineas += ["## Contexto", ""]
        lineas += [f"- **{k.capitalize()}:** {v}" for k, v in utiles]
        lineas.append("")

    if activo.get("relaciones"):
        lineas += ["## Entidades relacionadas", ""]
        lineas += [f"- {r.get('tipo', '')}: {r.get('nombre', '')}"
                   for r in activo["relaciones"]]
        lineas.append("")

    # Los diagramas son la razon de ser de este bloque: convierten conocimiento
    # visual en texto indexable. Sin esto, un deck de arquitectura entra al
    # indice como un titulo y tres vinetas.
    if activo.get("diagramas"):
        lineas += ["## Diagramas", ""]
        for i, d in enumerate(activo["diagramas"], start=1):
            lineas.append(f"### {i}. {d.get('titulo', 'Sin titulo')} "
                          f"({d.get('tipo_diagrama', 'Otro')})")
            lineas.append("")
            lineas.append(d.get("descripcion", ""))
            lineas.append("")
            if d.get("elementos"):
                lineas += [f"**Elementos:** {d['elementos']}", ""]
            if d.get("flujo"):
                lineas += [f"**Flujo:** {d['flujo']}", ""]

    # APM y TDD en secciones separadas: son dos fuentes distintas y la decision
    # de que entra al Knowledge Hub se toma por fuente. Ademas, como seccion
    # propia cada una queda como un fragmento recuperable por si misma.
    for clave, titulo in (("apm", "APM · Inventario de Aplicaciones"),
                          ("tdd", "TDD · Diseño Técnico")):
        filas = activo.get(clave) or []
        if not filas:
            continue
        lineas.append(f"## {titulo}")
        lineas.append("")
        lineas.append("| Grupo | Nivel | Cobertura | Detalle |")
        lineas.append("|---|---|---|---|")
        for f in filas:
            detalle = (f.get("detalle") or "").replace("|", "/")
            lineas.append(f"| {f['grupo']} | {f['nivel']} | "
                          f"{f['cobertura']} | {detalle} |")
        lineas.append("")
        citas = [f for f in filas if f.get("cita")]
        if citas:
            for f in citas:
                lineas.append(f"- **{f['grupo']}:** \u201c{f['cita']}\u201d")
            lineas.append("")

    # Las fichas llenadas. Van DESPUES de las tablas de cobertura porque son
    # cosas distintas: arriba, que tanto aporta el documento; aqui, el dato en
    # si. Solo se listan los campos con valor: una tabla con 27 renglones
    # vacios no ayuda a nadie, y el conteo del frontmatter ya dice cuantos
    # faltan.
    for fuente, titulo in (("apm", "Ficha APM llenada"),
                           ("tdd", "Ficha TDD llenada")):
        ficha = activo.get(f"ficha_{fuente}") or {}
        if not any(ficha.values()):
            continue
        # Grupo y etiqueta reales del aplicativo identificado, cuando existen
        # (_llenado); si el documento se proceso sin una base de APM sembrada
        # solo se sabe la clave, y se usa esa como respaldo.
        grupos_reales = ((activo.get("_llenado") or {}).get(fuente) or {}).get("grupos") or []
        metadatos = {c["clave"]: (g["grupo"], c["etiqueta"])
                    for g in grupos_reales for c in g.get("campos", [])}
        total = _total_real(activo, fuente)
        llenos = len([v for v in ficha.values() if v])
        lineas += [f"## {titulo}", ""]
        # Si el documento no calzo con ningun aplicativo del inventario pero
        # de todos modos trae forma de ficha (`aplicacion_nueva`), esta tabla
        # es una PROPUESTA de alta, no el aplicativo ya dado de alta -- se
        # deja dicho aqui para que quien lea el .md despues no lo confunda
        # con una ficha real ya existente en el APM.
        if fuente == "apm" and (activo.get("_apm") or {}).get("aplicacion_nueva"):
            lineas += ["**Aplicación nueva (propuesta):** este documento no "
                       "coincide con ningún aplicativo ya dado de alta en el "
                       "inventario; lo de abajo es una propuesta para una "
                       "posible alta nueva, no un aplicativo existente.", ""]
        lineas += [f"{llenos} de {total} campos con dato. Los que faltan no "
                   "estaban en el documento; se dejan vacios a proposito.", "",
                   "| Grupo | Campo | Valor |", "|---|---|---|"]
        for clave, valor in ficha.items():
            valor = str(valor or "").strip()
            if not valor:
                continue
            grupo, etiqueta = metadatos.get(clave, ("", clave))
            lineas.append(f"| {grupo} | {etiqueta} | "
                          f"{valor.replace(chr(124), chr(47))} |")
        lineas.append("")

    if activo.get("trazabilidad"):
        lineas += ["## Trazabilidad de la clasificacion", "",
                   activo["trazabilidad"], ""]

    if activo.get("observaciones"):
        lineas += ["## Observaciones para revision humana", ""]
        lineas += [f"- {o}" for o in activo["observaciones"]]
        lineas.append("")

    if activo.get("requiere_revision"):
        lineas += ["> **Atencion:** los campos "
                   f"`{'`, `'.join(activo['requiere_revision'])}` no estan "
                   "respaldados por evidencia suficiente. No uses este activo "
                   "como fuente autoritativa hasta validarlos.", ""]

    if texto_documento.strip():
        lineas += ["---", "", "## Contenido del documento", "",
                   texto_documento.strip(), ""]

    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Escritura en disco
# ---------------------------------------------------------------------------

def escribir(activo: dict, carpeta_destino: Path, texto_documento: str = "",
             ruta_origen: str = "") -> dict[str, str]:
    """Deja <base>.md y <base>.json en carpeta_destino. Devuelve las rutas."""
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    base = nombre_base(activo)

    # nunca sobrescribir: dos documentos pueden compartir titulo
    destino_md = carpeta_destino / f"{base}.md"
    n = 2
    while destino_md.exists():
        destino_md = carpeta_destino / f"{base}-{n}.md"
        n += 1
    destino_json = destino_md.with_suffix(".json")

    destino_md.write_text(
        a_markdown(activo, texto_documento, ruta_origen), encoding="utf-8")
    destino_json.write_text(
        json.dumps(activo, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"md": str(destino_md), "json": str(destino_json)}
