"""
identificacion.py
-----------------
Decide DOS cosas antes de que un archivo pueda aportar un solo dato:

  1. ¿Es un documento fuente, o es un destino?
     El libro de APM y los TDD son destinos. Si entran como materia prima, la
     aplicacion termina copiando el APM sobre el APM y dandose la razon sola: el
     dato se veria "confirmado por dos fuentes" cuando en realidad se leyo dos
     veces el mismo archivo. Por eso se detectan por su ESTRUCTURA y se
     descartan, sin importar como se llame el archivo.

  2. ¿De que aplicativo habla?
     Un documento que no se puede amarrar a uno de los habilitadores del
     inventario NO se usa. Nada de repartir su contenido "a lo que se parezca":
     un manual de un sistema escrito en la ficha de otro es peor que un hueco,
     porque el hueco se ve.

El orden de las señales va de exacta a floja, y cada una dice de donde salio para
que quien revisa pueda juzgarla:

     id_habilitador  el codigo 0606-HTI-001-TRXC. Es unico, no se repite.
     numero_apm      "APM #3". Exacto contra la columna '#'.
     nombre_exacto   el nombre del habilitador tal cual esta en la hoja.
     nombre_en_texto el nombre aparece dentro del documento o del archivo.

Debajo de `nombre_en_texto` no hay nada: si solo hay parecido, se declara NO
identificado y el documento espera a que una persona lo asigne.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import apm as mod_apm
from . import tdd as mod_tdd
from . import tdd_nivel2 as mod_tdd2

# Un nombre demasiado corto o demasiado generico produce coincidencias falsas:
# "SAP" aparece dentro de "SAPI", y "Portal" esta en media docena de documentos
# que no hablan del Portal Unificado. Por debajo de este largo se exige que el
# nombre venga delimitado por frontera de palabra y aun asi baja de confianza.
LARGO_NOMBRE_SEGURO = 5

RE_IDH = re.compile(r"\b([0-9]{3,5}-[A-Za-z]{2,4}-[0-9]{3}-[A-Za-z]{3,4})\b")
RE_APM = re.compile(r"\bapm\s*#\s*(\d+)\b", re.I)


def _norm(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


@dataclass
class Papel:
    """Que es este archivo para el proceso."""
    ruta: str
    es_fuente: bool
    tipo: str          # "fuente" | "apm" | "tdd" | "tdd2" | "ilegible"
    motivo: str = ""


def clasificar_archivo(ruta: str | Path) -> Papel:
    """Fuente, o destino. Se revisa el contenido, no la extension ni el nombre:
    alguien puede renombrar un archivo, pero no puede quitarle la hoja Inventory
    a un libro de APM ni la tabla de identificacion a un TDD."""
    ruta = Path(ruta)
    try:
        if mod_apm.es_libro_apm(ruta):
            return Papel(str(ruta), False, "apm",
                         "es el libro de APM: es destino, no materia prima")
        # El TDD Nivel 2 se revisa ANTES que el TDD_V3: un archivo de la
        # plantilla nueva no debe caer en el reconocimiento viejo solo porque
        # comparta alguna palabra -- se distinguen por estructura real
        # (la escala C1-C4 y las 17 secciones), no por el nombre.
        if mod_tdd2.es_documento_tdd_nivel2(ruta):
            return Papel(str(ruta), False, "tdd2",
                         "es un TDD Nivel 2: es destino, no materia prima")
        if mod_tdd.es_documento_tdd(ruta):
            return Papel(str(ruta), False, "tdd",
                         "es un documento TDD: es destino, no materia prima")
    except Exception as exc:
        return Papel(str(ruta), False, "ilegible", f"no se pudo abrir: {exc}")
    return Papel(str(ruta), True, "fuente")


@dataclass
class Amarre:
    """A que aplicativo pertenece un documento, y por que se cree eso."""
    identificado: bool
    numero: str = ""
    id_habilitador: str = ""
    nombre: str = ""
    senal: str = ""            # id_habilitador | numero_apm | nombre_exacto | nombre_en_texto
    evidencia: str = ""
    candidatos: list = None    # cuando hay empate, para que una persona escoja

    def __post_init__(self):
        if self.candidatos is None:
            self.candidatos = []


def identificar(texto: str, nombre_archivo: str, libro: mod_apm.LibroAPM) -> Amarre:
    """Amarra un documento fuente a un habilitador del inventario.

    `texto` es el contenido ya extraido por el parser; `nombre_archivo` es el
    respaldo. Se prueban las señales en orden de fuerza y se corta en la primera
    que da, porque una señal exacta no se mejora con una floja.
    """
    plano = f"{texto}\n{nombre_archivo}"
    n_plano = _norm(plano)

    # 1. El codigo del habilitador. Es la señal mas fuerte que existe.
    for codigo in RE_IDH.findall(plano):
        app = libro.aplicacion(id_habilitador=codigo)
        if app:
            return Amarre(True, app.numero, app.id_habilitador, app.nombre,
                          "id_habilitador", f"aparece el código {codigo}")

    # 2. "APM #N".
    for numero in RE_APM.findall(plano):
        app = libro.aplicacion(numero=numero)
        if app:
            return Amarre(True, app.numero, app.id_habilitador, app.nombre,
                          "numero_apm", f"aparece «APM #{numero}»")

    # 3. y 4. Por nombre. Se juntan TODAS las coincidencias antes de decidir:
    # si dos habilitadores distintos aparecen en el mismo documento, no hay
    # identificacion, hay que preguntar.
    golpes = []
    for app in libro.aplicaciones:
        n_nombre = _norm(app.nombre)
        if not n_nombre or len(n_nombre) < 3:
            continue
        if len(n_nombre) >= LARGO_NOMBRE_SEGURO:
            hay = n_nombre in n_plano
        else:
            hay = re.search(rf"\b{re.escape(n_nombre)}\b", n_plano) is not None
        if hay:
            exacto = _norm(nombre_archivo) == n_nombre or n_nombre in _norm(nombre_archivo)
            golpes.append((app, exacto))

    if not golpes:
        return Amarre(False)

    # El nombre mas largo gana sobre el mas corto cuando uno contiene al otro:
    # "Portal Unificado" le gana a "Portal", que es el nombre de otra fila.
    golpes.sort(key=lambda g: (g[1], len(g[0].nombre)), reverse=True)
    mejor, exacto = golpes[0]

    reales = [g for g in golpes
              if not (_norm(g[0].nombre) in _norm(mejor.nombre) and g[0] is not mejor)]
    if len(reales) > 1:
        return Amarre(
            False, candidatos=[{"numero": a.numero, "nombre": a.nombre,
                                "id_habilitador": a.id_habilitador} for a, _ in reales[:6]],
            evidencia=("el documento menciona más de un aplicativo; "
                       "hay que decir cuál es el suyo"))

    return Amarre(True, mejor.numero, mejor.id_habilitador, mejor.nombre,
                  "nombre_exacto" if exacto else "nombre_en_texto",
                  f"aparece el nombre «{mejor.nombre}»"
                  + (" en el nombre del archivo" if exacto else " en el contenido"))
