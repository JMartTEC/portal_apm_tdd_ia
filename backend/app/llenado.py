"""
llenado.py
----------
Propone el llenado de las fichas APM y TDD a partir de un documento ya
analizado. Es el motor detras del boton "Llenar documento".

Como funciona, en una linea: BUSCA, NO INVENTA.

El extractor recorre el documento armando un indice de pares
`etiqueta -> valor` (de tablas de dos columnas, de renglones tipo
"Responsable: Juan Perez", de propiedades del archivo) y luego, para cada campo
de la plantilla, busca ese indice con las pistas del catalogo. Si encuentra, el
campo se llena y se guarda la linea exacta como evidencia. Si no encuentra, el
campo se queda VACIO y marcado.

Por que no se le pide al modelo que llene la ficha completa: porque lo haria.
Un LLM al que se le pasa una plantilla de 40 campos y un documento que solo
habla de tres devuelve los 40 llenos, con valores plausibles y sin respaldo.
Ese es exactamente el error que esta POC existe para no cometer: un inventario
con huecos visibles se puede completar; uno con datos inventados que se ven
bien ya no se puede auditar.

Los cuatro estados de un campo:

    extraido     el documento lo dice; se guarda la linea como evidencia
    heredado     viene de la ficha ya clasificada del activo (mismo documento,
                 dato ya validado en el paso 4)
    referenciado el documento toca ese grupo pero sin dar el dato: hay que
                 confirmarlo con la fuente. Es el ambar.
    faltante     nada. Es la alerta.
"""

from __future__ import annotations

import re
import unicodedata

from . import campos as cat_campos
from . import fuentes

# Un valor mas largo que esto casi siempre es un parrafo que arrastro el
# separador, no el dato. Se recorta para que la ficha siga siendo legible.
MAX_VALOR = 300

# Valores que en un documento significan "no hay dato", aunque esten escritos.
VACIOS = {"", "-", "--", "n/a", "na", "n.a.", "no aplica", "nd", "n/d",
          "pendiente", "por definir", "tbd", "sin informacion", "no identificado",
          "no identificada", "ninguno", "ninguna", "x", "[ ]", "()"}

# Separadores etiqueta/valor que aparecen en documentos reales.
_SEPARADOR = re.compile(r"^\s*([^:–—]{2,60}?)\s*[:–—]\s*(.+)$")


def _norm(texto: str) -> str:
    """Minusculas, sin acentos, sin puntuacion: para comparar etiquetas que en
    el documento vienen como 'Dueño de Negocio' y en el catalogo como
    'dueno de negocio'."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower().replace("ñ", "n")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _util(valor: str) -> bool:
    v = _norm(valor)
    return bool(v) and v not in {_norm(x) for x in VACIOS} and len(v) > 1


def _limpiar(valor: str) -> str:
    v = re.sub(r"\s+", " ", str(valor or "")).strip(" .;\t")
    return v[:MAX_VALOR] + ("…" if len(v) > MAX_VALOR else "")


# ---------------------------------------------------------------------------
# Indice etiqueta -> valor del documento
# ---------------------------------------------------------------------------

def _indice(doc: dict) -> list[tuple[str, str, str]]:
    """Lista de (etiqueta_normalizada, valor, evidencia).

    Se conserva el orden de aparicion: si un documento repite una etiqueta, gana
    la PRIMERA. En una plantilla, la primera suele ser la de la portada o la
    tabla de control; las siguientes suelen ser ejemplos o encabezados de otra
    seccion.
    """
    pares: list[tuple[str, str, str]] = []

    def agregar(etiqueta: str, valor: str, evidencia: str):
        if not _util(valor):
            return
        clave = _norm(etiqueta)
        if not clave or len(clave) > 70:
            return
        pares.append((clave, _limpiar(valor), _limpiar(evidencia)))

    # 1. Tablas. Las de dos columnas son fichas: columna izquierda etiqueta,
    #    derecha valor. Las de mas columnas se recorren igual por si la primera
    #    columna es la etiqueta y la segunda el dato.
    for tabla in (doc.get("tablas") or []):
        for fila in (tabla.get("filas") or []):
            celdas = [str(c or "").strip() for c in fila]
            if len(celdas) >= 2 and celdas[0]:
                agregar(celdas[0], celdas[1], f"{celdas[0]} | {celdas[1]}")

    # 2. Parrafos con separador. base.py ya aplana las tablas de dos columnas
    #    como "clave: valor", asi que aqui caen tambien esas.
    for parrafo in (doc.get("parrafos") or []):
        for linea in str(parrafo).split("\n"):
            m = _SEPARADOR.match(linea.strip())
            if m:
                agregar(m.group(1), m.group(2), linea.strip())

    # 3. Propiedades del archivo, si el parser las trajo.
    props = doc.get("propiedades") or {}
    if isinstance(props, dict):
        for k, v in props.items():
            agregar(k, v, f"propiedad del archivo · {k}: {v}")

    return pares


def _buscar(pares: list[tuple[str, str, str]], pistas: list[str]):
    """Tres pasadas, de mas exacta a mas laxa. Se para en la primera que da,
    para que 'version' no gane sobre 'version del sistema' cuando ambas estan."""
    normas = [_norm(p) for p in pistas if _norm(p)]

    for clave, valor, ev in pares:               # 1. igual
        if clave in normas:
            return valor, ev, "igual"
    for clave, valor, ev in pares:               # 2. la etiqueta contiene la pista
        for p in normas:
            if len(p) >= 4 and re.search(rf"\b{re.escape(p)}\b", clave):
                return valor, ev, "contiene"
    for clave, valor, ev in pares:               # 3. la pista contiene la etiqueta
        for p in normas:
            if len(clave) >= 5 and clave in p:
                return valor, ev, "parcial"
    return None, None, None


# ---------------------------------------------------------------------------
# Herencia desde la ficha ya clasificada
# ---------------------------------------------------------------------------
# El paso 4 ya dejo campos validados por un humano. Repetir la extraccion sobre
# ellos seria peor: se perderia la correccion manual.

HERENCIA_APM = {
    "descripcion_aplicacion": ("descripcion", "descripción del activo"),
    "version_aplicacion": ("version", "versión del activo"),
    "dueno_tecnico": ("responsable", "responsable del activo"),
    "fecha_evaluacion": ("fecha", "fecha del activo"),
    "clasificacion_datos": ("confidencialidad", "confidencialidad del activo"),
    "fuente_sharepoint": ("fuente", "fuente del activo"),
    "estatus": ("estado", "estado del activo"),
}

HERENCIA_TDD = {
    "responsable_tdd": ("responsable", "responsable del activo"),
    "proposito_documento": ("descripcion", "descripción del activo"),
}


def _heredar(activo: dict, mapa: dict, clave: str):
    origen = mapa.get(clave)
    if not origen:
        return None, None
    valor = activo.get(origen[0])
    if not _util(str(valor or "")):
        return None, None
    return _limpiar(str(valor)), f"heredado de la ficha · {origen[1]}"


def _de_contexto(activo: dict, clave: str):
    """Un puñado de campos técnicos que el clasificador ya dejó en `contexto`."""
    ctx = activo.get("contexto") or {}
    mapa = {
        "stack_tecnologico": "contexto_tecnico",
        "modelo_despliegue": "contexto_tecnico",
        "ecosistema": "dominio",
    }
    campo = mapa.get(clave)
    if not campo:
        return None, None
    valor = ctx.get(campo)
    if not _util(str(valor or "")):
        return None, None
    return _limpiar(str(valor)), f"heredado del contexto · {campo.replace('_', ' ')}"


# ---------------------------------------------------------------------------
# Propuesta
# ---------------------------------------------------------------------------

def _coberturas(activo: dict, fuente: str) -> dict[str, str]:
    """Grupo -> cobertura, tal como la dejo el analisis del paso 3."""
    return {f.get("grupo", ""): f.get("cobertura", "")
            for f in (activo.get(fuente) or [])}


def _propuesta_fuente(activo: dict, pares: list, fuente: str) -> dict:
    cobertura = _coberturas(activo, fuente)
    herencia = HERENCIA_APM if fuente == "apm" else HERENCIA_TDD
    grupos_salida = []
    conteo = {"extraido": 0, "heredado": 0, "referenciado": 0, "faltante": 0}

    for grupo in fuentes.catalogo(fuente):
        nombre = grupo["grupo"]
        cob = cobertura.get(nombre, "Ausente")
        lista = []

        for campo in cat_campos.por_grupo(fuente).get(nombre, []):
            valor, evidencia, modo = _buscar(pares, campo["pistas"])
            if valor:
                estado, origen = "extraido", f"documento · coincidencia {modo}"
            else:
                valor, evidencia = _heredar(activo, herencia, campo["clave"])
                if not valor:
                    valor, evidencia = _de_contexto(activo, campo["clave"])
                if valor:
                    estado, origen = "heredado", "ficha clasificada"
                else:
                    # Sin dato. El documento toca el grupo pero no da la cifra:
                    # eso NO es lo mismo que un grupo del que no dice nada.
                    estado = "referenciado" if cob in ("Documentado", "Referenciado") else "faltante"
                    origen, evidencia, valor = "", "", ""

            conteo[estado] += 1
            lista.append({
                "clave": campo["clave"],
                "etiqueta": campo["etiqueta"],
                "valor": valor,
                "estado": estado,
                "origen": origen,
                "evidencia": evidencia or "",
            })

        grupos_salida.append({
            "grupo": nombre,
            "nivel": grupo["nivel"],
            "cobertura": cob,
            "campos": lista,
        })

    total = sum(conteo.values())
    llenos = conteo["extraido"] + conteo["heredado"]
    criticos_pendientes = sum(
        1 for g in grupos_salida if g["nivel"] == "Critico"
        for c in g["campos"] if c["estado"] in ("referenciado", "faltante"))

    return {
        "etiqueta": fuentes.FUENTES[fuente]["etiqueta"],
        "grupos": grupos_salida,
        "resumen": {
            "total": total,
            "llenos": llenos,
            "extraidos": conteo["extraido"],
            "heredados": conteo["heredado"],
            "referenciados": conteo["referenciado"],
            "faltantes": conteo["faltante"],
            "criticos_pendientes": criticos_pendientes,
            "porcentaje": round(llenos * 100 / total) if total else 0,
        },
    }


def proponer(activo: dict, doc: dict) -> dict:
    """Propuesta de llenado para las dos fuentes. No modifica el activo: el
    usuario decide si la aplica desde el boton 'Llenar documento'."""
    pares = _indice(doc)
    salida = {f: _propuesta_fuente(activo, pares, f) for f in ("apm", "tdd")}
    salida["pares_detectados"] = len(pares)
    return salida


# ---------------------------------------------------------------------------
# Aplicacion y diff
# ---------------------------------------------------------------------------

def aplicar(ficha_previa: dict | None, propuesta: dict, fuente: str) -> tuple[dict, list]:
    """Aplica la propuesta sobre la ficha que ya existiera y devuelve
    (ficha_nueva, cambios). Vale para el frontend y para un llenado por lote.

    Regla de fusion, la misma que rige el resto del proyecto: lo que ya estaba
    escrito manda. La propuesta solo rellena huecos; nunca pisa un valor que un
    humano ya puso.
    """
    previa = dict(ficha_previa or {})
    nueva = dict(previa)
    cambios = []

    for grupo in propuesta[fuente]["grupos"]:
        for campo in grupo["campos"]:
            # "calculado" es de solo lectura -- el valor que el libro YA trae
            # de una formula. No se captura, no se compara, y sobre todo no se
            # cuenta como algo que "Llenar documento" aplico: mezclarlo con
            # extraido/heredado inflaria el conteo de campos llenados con algo
            # que nunca fue una propuesta.
            if campo.get("estado") == "calculado":
                continue
            antes = str(previa.get(campo["clave"], "") or "")
            despues = campo["valor"]
            if not despues or antes.strip():
                continue
            nueva[campo["clave"]] = despues
            cambios.append({
                "clave": campo["clave"],
                "etiqueta": campo["etiqueta"],
                "grupo": grupo["grupo"],
                # .get(): las fichas REALES del APM (_ficha_apm_real, en
                # main.py) no traen "nivel" -- ese es un concepto de la
                # plantilla generica vieja (campos.py), no de las columnas
                # reales del libro. Esta funcion sirve a las dos.
                "nivel": grupo.get("nivel", ""),
                "antes": antes,
                "despues": despues,
                "origen": campo["origen"],
                "evidencia": campo["evidencia"],
            })
    return nueva, cambios
