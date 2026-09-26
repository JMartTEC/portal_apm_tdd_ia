"""
conciliacion.py
---------------
El motor de validacion. Compara lo que dicen los documentos fuente contra lo que
ya dice el APM, y produce una lista de propuestas que NADIE puede guardar hasta
que una persona las decida una por una.

La regla que ordena todo el archivo: **la aplicacion nunca resuelve un
desacuerdo.** Puede proponer, puede señalar, puede explicar de donde salio cada
valor. Pero cuando dos cosas se contradicen, la salida es un conflicto abierto,
no una decision automatica. Un dato equivocado que entro "solo" en un inventario
de 70 aplicaciones no se encuentra nunca; uno marcado en rojo esperando decision
se resuelve en un minuto.

Los estados de una propuesta:

    coincide      el documento dice lo mismo que ya tiene el APM. No hay cambio,
                  pero si hay valor: queda VERIFICADO, que es informacion.
    propuesto     el campo esta vacio y hay un solo candidato. Se puede aceptar.
    sobre_sin_info el campo dice "Sin informacion" y aparecio un dato. Se separa
                  de `propuesto` a proposito: alguien ya afirmo que busco y no
                  encontro, asi que pisarlo es una decision, no un relleno.
    conflicto_fuentes  dos documentos dicen cosas distintas. Decide una persona.
    conflicto_apm      el APM ya tiene un valor y el documento dice otro.
                  Decide una persona. El APM no se pisa por inercia.
    bloqueado     la columna es formula o calculada. Ni se propone.

Solo `propuesto` y `coincide` son inofensivos. Los tres del medio exigen que
alguien escoja, y `aplicar` se niega a tocar el libro si queda uno sin decidir.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .apm import LibroAPM, es_sin_informacion, es_vacio

# Estados
COINCIDE = "coincide"
PROPUESTO = "propuesto"
SOBRE_SIN_INFO = "sobre_sin_info"
CONFLICTO_FUENTES = "conflicto_fuentes"
CONFLICTO_APM = "conflicto_apm"
BLOQUEADO = "bloqueado"

# Los que no se pueden guardar sin una decision explicita de una persona.
EXIGEN_DECISION = {SOBRE_SIN_INFO, CONFLICTO_FUENTES, CONFLICTO_APM}


def _norm(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s.,;]+", " ", t).strip().lower()


def _iguales(a, b) -> bool:
    """Dos valores son el mismo dato si coinciden salvo acentos, mayusculas y
    puntuacion. 'Cloud-SaaS' y 'cloud saas' no son un conflicto, son un formato."""
    na, nb = _norm(a), _norm(b)
    return bool(na) and na == nb


@dataclass
class Candidato:
    valor: str
    documento: str          # de que archivo salio
    evidencia: str = ""     # la linea exacta, para poder juzgarlo


@dataclass
class Propuesta:
    clave: str
    grupo: str
    etiqueta: str
    valor_actual: str
    estado: str
    candidatos: list[Candidato] = field(default_factory=list)
    motivo: str = ""
    lookup: list[str] = field(default_factory=list)
    nota: str = ""
    decision: str | None = None      # el valor que una persona escogio
    decidido_por_persona: bool = False

    @property
    def exige_decision(self) -> bool:
        return self.estado in EXIGEN_DECISION

    @property
    def resuelta(self) -> bool:
        return (not self.exige_decision) or self.decidido_por_persona

    @property
    def valor_final(self) -> str:
        if self.decision is not None:
            return self.decision
        if self.estado == PROPUESTO and self.candidatos:
            return self.candidatos[0].valor
        return ""

    def a_dict(self) -> dict:
        return {
            "clave": self.clave, "grupo": self.grupo, "etiqueta": self.etiqueta,
            "valor_actual": self.valor_actual, "estado": self.estado,
            "motivo": self.motivo, "nota": self.nota, "lookup": self.lookup,
            "exige_decision": self.exige_decision, "resuelta": self.resuelta,
            "decision": self.decision, "valor_final": self.valor_final,
            "candidatos": [{"valor": c.valor, "documento": c.documento,
                            "evidencia": c.evidencia} for c in self.candidatos],
        }


def conciliar_apm(libro: LibroAPM, aplicacion, hallazgos: dict[str, list[Candidato]]
                  ) -> list[Propuesta]:
    """Una propuesta por cada columna del APM que tenga algo que decir.

    `hallazgos` = {clave_de_columna: [Candidato, ...]} — lo que los documentos
    fuente aportaron para esta aplicacion. Las columnas sin candidatos y ya
    llenas no generan propuesta: no hay nada que revisar ahi.
    """
    salida: list[Propuesta] = []

    for col in libro.columnas:
        candidatos = hallazgos.get(col.clave, [])
        actual = aplicacion.valores.get(col.clave)
        actual_txt = "" if actual is None else str(actual).strip()

        if not candidatos:
            continue

        if not col.escribible:
            salida.append(Propuesta(
                col.clave, col.grupo, col.etiqueta, actual_txt, BLOQUEADO,
                candidatos, motivo=col.motivo, nota=col.nota))
            continue

        # ¿Los documentos se contradicen entre ellos?
        distintos = []
        for c in candidatos:
            if not any(_iguales(c.valor, d.valor) for d in distintos):
                distintos.append(c)

        if len(distintos) > 1:
            salida.append(Propuesta(
                col.clave, col.grupo, col.etiqueta, actual_txt, CONFLICTO_FUENTES,
                distintos, lookup=col.lookup, nota=col.nota,
                motivo=f"{len(distintos)} documentos dan valores distintos"))
            continue

        candidato = distintos[0]

        if es_sin_informacion(actual_txt):
            salida.append(Propuesta(
                col.clave, col.grupo, col.etiqueta, actual_txt, SOBRE_SIN_INFO,
                distintos, lookup=col.lookup, nota=col.nota,
                motivo=("el APM dice «Sin información», que significa que alguien "
                        "ya revisó y no encontró el dato. Sustituirlo es una decisión")))
        elif es_vacio(actual_txt):
            salida.append(Propuesta(
                col.clave, col.grupo, col.etiqueta, actual_txt, PROPUESTO,
                distintos, lookup=col.lookup, nota=col.nota))
        elif _iguales(actual_txt, candidato.valor):
            salida.append(Propuesta(
                col.clave, col.grupo, col.etiqueta, actual_txt, COINCIDE,
                distintos, lookup=col.lookup, nota=col.nota,
                motivo="el documento confirma lo que ya tenía el APM"))
        else:
            salida.append(Propuesta(
                col.clave, col.grupo, col.etiqueta, actual_txt, CONFLICTO_APM,
                distintos, lookup=col.lookup, nota=col.nota,
                motivo="el APM y el documento no dicen lo mismo"))

    return salida


def aplicar_decisiones(propuestas: list[Propuesta], decisiones: dict[str, str],
                       aceptar_propuestos: bool = True) -> list[Propuesta]:
    """Registra lo que la persona escogio. `decisiones` = {clave: valor elegido}.

    Un valor vacio significa "no cambiar nada aqui", y tambien cuenta como
    decidido: decir que no es decidir.
    """
    for p in propuestas:
        if p.clave in decisiones:
            p.decision = str(decisiones[p.clave])
            p.decidido_por_persona = True
        elif p.estado == PROPUESTO and not aceptar_propuestos:
            p.decision = ""
    return propuestas


def pendientes(propuestas: list[Propuesta]) -> list[Propuesta]:
    """Las que todavia bloquean el guardado."""
    return [p for p in propuestas if not p.resuelta]


def cambios_para_escribir(propuestas: list[Propuesta], fila: int,
                          libro: LibroAPM) -> tuple[list[dict], list[dict]]:
    """Traduce las propuestas resueltas a cambios de celda.

    Devuelve (cambios, descartados). Se valida contra el catalogo AQUI ademas de
    en el escritor: mas vale rechazarlo mientras la persona sigue en la pantalla
    que despues, cuando ya cree que guardo.
    """
    cambios, descartados = [], []
    for p in propuestas:
        if p.estado == BLOQUEADO:
            continue
        if not p.resuelta:
            descartados.append({"clave": p.clave, "etiqueta": p.etiqueta,
                                "motivo": "quedó sin decidir"})
            continue
        valor = p.valor_final
        if not valor or _iguales(valor, p.valor_actual):
            continue
        ok, motivo = libro.valida_para(p.clave, valor)
        if not ok:
            descartados.append({"clave": p.clave, "etiqueta": p.etiqueta,
                                "valor": valor, "motivo": motivo})
            continue
        cambios.append({"fila": fila, "clave": p.clave, "valor": valor})
    return cambios, descartados


def resumen(propuestas: list[Propuesta]) -> dict:
    cuenta: dict[str, int] = {}
    for p in propuestas:
        cuenta[p.estado] = cuenta.get(p.estado, 0) + 1
    return {
        "total": len(propuestas),
        "por_estado": cuenta,
        "exigen_decision": sum(1 for p in propuestas if p.exige_decision),
        "pendientes": len(pendientes(propuestas)),
        "listo_para_guardar": not pendientes(propuestas),
    }


# ---------------------------------------------------------------------------
# APM -> TDD
# ---------------------------------------------------------------------------
# La segunda mitad del flujo, y la direccion es de un solo sentido.
#
# El mapa amarra por TEXTO DE LA ETIQUETA en el TDD, no por numero de tabla: la
# plantilla existe en dos versiones (19 y 16 tablas) y los indices no coinciden
# entre ellas. Buscar la etiqueta funciona en las dos.
#
# Es un mapa CORTO a proposito. Solo estan los campos donde una celda del TDD
# significa exactamente lo mismo que una columna del APM. Las tablas de
# estructura -- stack por componente, integraciones origen/destino, horarios --
# se dejan fuera: meterle un valor suelto del APM a una tabla de varias filas
# produce un documento que se ve lleno y esta mal, y eso es peor que el hueco.

# Los patrones van ANCLADOS con ^...$ a proposito. Un patron suelto como
# `hosting|on prem` engancha el encabezado «ON PREM / NUBE» de la tabla de
# datacenter, que tiene ocho columnas y donde la celda de al lado no es el
# hosting sino una direccion IP. Escribir ahi produce un documento que se ve
# lleno y dice mentiras. Mejor perder una coincidencia que inventar una.
MAPA_APM_A_TDD = [
    # (patron ANCLADO de la etiqueta en el TDD, sufijo de la clave APM, descripcion)
    (r"^apm\b.*habilitador",                    "id_id_habilitador",                    "ID Habilitador"),
    (r"^nombre del proyecto$",                  "identidad_de_la_aplicacion_habilitador_aplicacion", "Nombre"),
    (r"^responsable(\s+t[eé]cnico)?\s*\*?$",    "identidad_de_la_aplicacion_responsable_tecnico", "Responsable técnico"),
    (r"^proveedor\s*\*?$",                      "identidad_de_la_aplicacion_proveedor",  "Proveedor"),
    (r"^due[nñ]o\b.*negocio",                   "identidad_de_la_aplicacion_dueno_negocio_product_owner", "Dueño de negocio"),
    (r"^hosting\s*\*?$",                        "perfil_tecnico_hosting",                "Hosting"),
    (r"^(usuarios activos|n[uú]mero de usuarios)\s*\*?$", "ciclo_de_vida_usuarios_activos", "Usuarios activos"),
    (r"^clasificaci[oó]n de datos\s*\*?$",      "riesgo_y_cumplimiento_clasificacion_de_datos", "Clasificación de datos"),
]


def mapear_apm_a_tdd(libro: LibroAPM, aplicacion, doc_tdd, celdas) -> list[dict]:
    """Propone celdas del TDD a llenar con el APM YA ACTUALIZADO.

    `celdas` = [{tabla, fila, columna, etiqueta, texto}] del documento.
    Solo se propone donde la celda esta VACIA: lo que el TDD ya trae se respeta,
    y si contradice al APM se levanta como conflicto para que lo vea una persona.
    """
    propuestas = []
    for celda in celdas:
        etiqueta = _norm(celda.get("etiqueta", ""))
        if not etiqueta:
            continue
        for patron, sufijo, descripcion in MAPA_APM_A_TDD:
            if not re.search(patron, etiqueta):
                continue
            col = next((c for c in libro.columnas if c.clave.endswith(sufijo)), None)
            if not col:
                continue
            valor = aplicacion.valores.get(col.clave)
            valor = "" if valor is None else str(valor).strip()
            if es_vacio(valor):
                break

            texto = str(celda.get("texto", "") or "").strip()
            from .tdd import celda_vacia
            if celda_vacia(texto):
                estado, motivo = PROPUESTO, f"del APM · {col.etiqueta}"
            elif _iguales(texto, valor):
                estado, motivo = COINCIDE, "el TDD ya coincide con el APM"
            else:
                estado, motivo = CONFLICTO_APM, (
                    "el TDD dice una cosa y el APM otra; el TDD no se pisa solo")
            propuestas.append({
                "tabla": celda["tabla"], "fila": celda["fila"],
                "columna": celda["columna"], "etiqueta": celda.get("etiqueta", ""),
                "descripcion": descripcion, "columna_apm": col.etiqueta,
                "texto_actual": texto, "valor": valor,
                "estado": estado, "motivo": motivo,
                "exige_decision": estado in EXIGEN_DECISION,
            })
            break
    return propuestas
