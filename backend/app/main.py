"""
main.py -- v2
-------------
POC "TEC | Clasificador de Activos de Conocimiento IA-Ready", version 2.

Que cambia respecto a la v1:
  - multiformato: Word, PDF, PowerPoint, Excel, texto e imagenes
  - dos modos de entrada: un archivo o una carpeta completa
  - los diagramas se convierten a texto indexable
  - exporta .md con frontmatter, ademas del .json

Sobre el almacenamiento. La v1 presumia "no storage" y era cierto: subias un
archivo, se escribia un temporal y se borraba. La v2 lee rutas del disco y
escribe resultados, asi que ese principio ya no aplica igual y seria deshonesto
seguir afirmandolo. La regla ahora es explicita:
  - los documentos originales NUNCA se modifican ni se copian
  - lo unico que se escribe son los .md y .json en la subcarpeta _ia-ready
  - los archivos subidos por el navegador si siguen el ciclo temporal de la v1
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import (almacen, apm, campos, claude_service, conciliacion,
               configuracion, deteccion, exportador, extraccion, fuentes,
               identificacion, llenado, lotes, metadata_validator,
               ollama_service, parsers, progreso_vivo, sesion, taxonomy, tdd,
               tdd_nivel2)
from .models import RespuestaValidacion, SolicitudValidacion
from .parsers.base import DocumentoIlegible, FormatoNoSoportado

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CARPETA_DATOS = BASE_DIR / "datos"
# Los archivos que se suben por el navegador viven aqui mientras dura la
# sesion de trabajo. Es carpeta desechable: se puede borrar entera sin perder
# nada, porque lo que importa de cada documento ya quedo en el almacen.
CARPETA_SUBIDOS = BASE_DIR / "_subidos"
# La "referencia activa": una copia interna del APM y de cada TDD, con nombre
# FIJO que nunca cambia (a diferencia de las versiones numeradas que "Hacer
# nueva version" deja en datos/salidas/ para que alguien se las lleve). Vive
# adentro del portal, nunca junto al archivo original del usuario. Que tan al
# dia esta no se sabe por el nombre -- se sabe por las fechas que guarda
# almacen.referencia (creado_en / actualizado_en).
CARPETA_REFERENCIA_APM = CARPETA_DATOS / "referencia" / "apm"
CARPETA_REFERENCIA_TDD = CARPETA_DATOS / "referencia" / "TDD"
# TDD Nivel 2 -- la plantilla nueva, que reemplaza al TDD_V3 de arriba.
# CARPETA_REFERENCIA_TDD2 es donde viven los TDD Nivel 2 reales tal como se
# cargaron (67 archivos, uno por aplicativo); su subcarpeta `_estable` guarda
# la copia de nombre FIJO por numero (`{numero}.docx`) contra la que de
# verdad se compara -- igual que CARPETA_REFERENCIA_TDD, pero separada para
# no mezclar los archivos originales con las copias que la app mantiene.
CARPETA_REFERENCIA_TDD2 = CARPETA_DATOS / "referencia" / "tdd_nivel2"
CARPETA_REFERENCIA_TDD2_ESTABLE = CARPETA_REFERENCIA_TDD2 / "_estable"
# El front (static/ y templates/) vive en su propia carpeta hermana de
# backend/, no dentro de ella -- separa lo que es interfaz de lo que es
# logica de servidor. BASE_DIR ya es backend/ (padre de app/), asi que solo
# hay que subir un nivel mas para llegar a la raiz del repo.
FRONTEND_DIR = BASE_DIR.parent / "frontend"
MAX_MB = 60
MAX_BYTES = MAX_MB * 1024 * 1024

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("poc-ia-ready-v2")

app = FastAPI(
    title="TEC | Clasificador de Activos IA-Ready v2",
    docs_url="/api/docs",  # "/docs" ahora es la pantalla de referencia APM y TDD
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


# ---------------------------------------------------------------------------
# SELECTOR DE PROVEEDOR
# ---------------------------------------------------------------------------
MODOS_LOCALES = {"local", "gratis", "ollama", "offline"}
MODOS_API = {"claude", "anthropic", "api"}


def _proveedor():
    modo = (os.getenv("AI_MODO") or "").strip().lower()
    if modo in MODOS_LOCALES:
        return "ollama", ollama_service.clasificar
    if modo in MODOS_API:
        return "claude", claude_service.clasificar
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude", claude_service.clasificar
    return "ollama", ollama_service.clasificar


log.info("proveedor de clasificacion: %s", _proveedor()[0])

# El almacen se abre una vez. SQLite aguanta varias conexiones, y cada
# operacion abre y cierra la suya dentro del modulo.
#
# Y se abre DENTRO de un try: la base es una mejora, no un requisito. Si la
# carpeta fuera de solo lectura o el disco estuviera lleno, sin esto la
# aplicacion entera no arrancaria -- incluida la clasificacion de documentos,
# que no tiene nada que ver con el almacen. Mejor perder la memoria que perder
# el programa, y decirlo en el log en vez de fallar en silencio.
try:
    BASE = almacen.Almacen(CARPETA_DATOS)
    log.info("almacen: %s", BASE.ruta)
except Exception as exc:
    BASE = None
    log.error("no se pudo abrir el almacen en %s (%s). La aplicacion sigue, "
              "pero sin memoria entre corridas.", CARPETA_DATOS, exc)


def _base():
    """El almacen, o un error claro. Las rutas que lo necesitan pasan por aqui;
    las que no, siguen funcionando aunque la base no exista."""
    if BASE is None:
        raise HTTPException(
            503, "La base interna no se pudo abrir, así que no hay memoria entre "
                 "corridas. Revisa los permisos de la carpeta «datos» junto a la "
                 "aplicación. Todo lo demás sigue funcionando.")
    return BASE


def _actualizar_referencia_apm(libro, origen_actual: str) -> dict | None:
    """Copia el libro de APM que se acaba de sembrar a la copia interna de
    nombre fijo (`datos/referencia/APM/APM_referencia.xlsx`), y registra en
    el almacen cuando se creo esa copia por primera vez y cuando se
    actualizo por ultima. No se usa para nada mas que mostrar esas dos
    fechas -- lo que de verdad se compara sigue siendo la base sembrada."""
    try:
        CARPETA_REFERENCIA_APM.mkdir(parents=True, exist_ok=True)
        destino = CARPETA_REFERENCIA_APM / f"apm_referencia{Path(libro.ruta).suffix}"
        shutil.copy2(libro.ruta, destino)
        return _base().actualizar_referencia("apm", "", str(destino), origen_actual)
    except Exception:
        log.exception("no se pudo actualizar la copia de referencia del APM")
        return None


def _actualizar_referencia_tdd(numero: str, ruta_tdd, origen_actual: str) -> dict | None:
    """Igual que `_actualizar_referencia_apm`, pero un TDD por aplicativo
    (`datos/referencia/TDD/<numero>.docx`). Sin numero de aplicativo no hay
    con que aparejar el archivo, asi que no se hace nada."""
    if not numero:
        return None
    try:
        CARPETA_REFERENCIA_TDD.mkdir(parents=True, exist_ok=True)
        destino = CARPETA_REFERENCIA_TDD / f"{numero}{Path(ruta_tdd).suffix}"
        shutil.copy2(ruta_tdd, destino)
        return _base().actualizar_referencia("tdd", numero, str(destino), origen_actual)
    except Exception:
        log.exception("no se pudo actualizar la copia de referencia del TDD #%s", numero)
        return None


# ---------------------------------------------------------------------------
# Paso 2 · Parte A: subir el propio APM o un TDD desde Inicio siembra la
# referencia directamente, sin pasar por la pantalla aparte de "Revisión
# Manual APM y TDD". `_clasificar_ruta` ya detecta esto (por estructura) y
# corta con `DestinoExcluido` antes de gastar una llamada a IA; estas dos
# funciones son lo que `_responder_uno` corre en ese momento en vez de
# limitarse a decir "esto no se revisa".
# ---------------------------------------------------------------------------

def _sembrar_apm_desde_subida(ruta_temporal: str, nombre_origen: str) -> dict:
    """El archivo subido (temporal, se borra al terminar la peticion) SI es el
    libro de APM. Se copia primero a la ubicacion estable de referencia y
    LUEGO se siembra desde esa copia -- para que lo que quede registrado como
    origen sea la copia interna, no un archivo que esta a punto de desaparecer."""
    try:
        libro_temp = apm.LibroAPM(Path(ruta_temporal))
    except Exception as exc:
        return {"ok": False, "motivo": f"no se pudo leer el libro subido: {exc}"}

    try:
        CARPETA_REFERENCIA_APM.mkdir(parents=True, exist_ok=True)
        destino = CARPETA_REFERENCIA_APM / f"apm_referencia{Path(ruta_temporal).suffix}"
        shutil.copy2(ruta_temporal, destino)
        libro_estable = apm.LibroAPM(destino)
    except Exception as exc:
        return {"ok": False, "motivo": f"no se pudo guardar la copia de referencia: {exc}"}

    resultado = _base().sembrar_apm(libro_estable)
    fechas = _base().actualizar_referencia("apm", "", str(destino), nombre_origen) or {}
    return {"ok": True, "aplicativos": resultado.get("aplicativos"),
            "ruta_estable": str(destino), **fechas}


def _sembrar_tdd_desde_subida(ruta_temporal: str, nombre_origen: str,
                              ruta_apm_actual: str) -> dict:
    """El archivo subido SI es un TDD. Para saber a que aplicativo pertenece
    hace falta el libro de APM ya sembrado (`ruta_apm_actual`, lo que la
    pantalla ya trae en `S.rutaApmAuto`) -- sin eso no hay con que aparejarlo."""
    try:
        doc_tdd = tdd.leer(Path(ruta_temporal))
    except Exception as exc:
        return {"ok": False, "motivo": f"no se pudo leer el TDD subido: {exc}"}

    numero, nombre_app = "", ""
    if ruta_apm_actual:
        try:
            libro_actual = _libro(ruta_apm_actual)
            aplicacion = libro_actual.aplicacion(
                numero=doc_tdd.numero_apm, id_habilitador=doc_tdd.id_habilitador,
                nombre=doc_tdd.nombre_archivo_pista)
            if aplicacion:
                numero, nombre_app = aplicacion.numero, aplicacion.nombre
        except Exception:
            pass

    if not numero:
        return {"ok": False, "motivo": "no se pudo identificar a qué aplicativo "
                "pertenece este TDD (hace falta tener primero el APM sembrado)"}

    try:
        CARPETA_REFERENCIA_TDD.mkdir(parents=True, exist_ok=True)
        destino = CARPETA_REFERENCIA_TDD / f"{numero}{Path(ruta_temporal).suffix}"
        shutil.copy2(ruta_temporal, destino)
    except Exception as exc:
        return {"ok": False, "motivo": f"no se pudo guardar la copia de referencia: {exc}"}

    _base().sembrar_tdd(destino, doc_tdd, tdd.celdas_etiquetadas(Path(ruta_temporal)), numero)
    fechas = _base().actualizar_referencia("tdd", numero, str(destino), nombre_origen) or {}
    return {"ok": True, "numero": numero, "aplicativo": nombre_app,
            "ruta_estable": str(destino), **fechas}


def _sembrar_tdd2_desde_subida(ruta_temporal: str, nombre_origen: str,
                               ruta_apm_actual: str) -> dict:
    """El archivo subido SI es un TDD Nivel 2 -- mismo criterio que
    `_sembrar_tdd_desde_subida`, pero con el amarre y el guardado propios de
    la plantilla nueva (`tdd_nivel2.identificar` / `Almacen.sembrar_tdd2`).
    La plantilla en blanco se descarta aparte: no es el TDD de ningun
    aplicativo real."""
    try:
        doc_tdd2 = tdd_nivel2.leer(Path(ruta_temporal))
    except Exception as exc:
        return {"ok": False, "motivo": f"no se pudo leer el TDD Nivel 2 subido: {exc}"}

    if tdd_nivel2.es_plantilla_en_blanco(doc_tdd2):
        return {"ok": False, "motivo": "es la plantilla en blanco del TDD Nivel 2, "
                "no el TDD de ningún aplicativo real"}

    numero, nombre_app = "", ""
    if ruta_apm_actual:
        try:
            libro_actual = _libro(ruta_apm_actual)
            amarre = tdd_nivel2.identificar(doc_tdd2, libro_actual)
            if amarre.identificado:
                numero, nombre_app = amarre.numero, amarre.nombre
        except Exception:
            pass

    if not numero:
        return {"ok": False, "motivo": "no se pudo identificar a qué aplicativo "
                "pertenece este TDD Nivel 2 (hace falta tener primero el APM sembrado)"}

    try:
        CARPETA_REFERENCIA_TDD2_ESTABLE.mkdir(parents=True, exist_ok=True)
        destino = CARPETA_REFERENCIA_TDD2_ESTABLE / f"{numero}.docx"
        shutil.copy2(ruta_temporal, destino)
        doc_estable = tdd_nivel2.leer(destino)
    except Exception as exc:
        return {"ok": False, "motivo": f"no se pudo guardar la copia de referencia: {exc}"}

    _base().sembrar_tdd2(destino, doc_estable, numero)
    fechas = _base().actualizar_referencia("tdd2", numero, str(destino), nombre_origen) or {}
    return {"ok": True, "numero": numero, "aplicativo": nombre_app,
            "ruta_estable": str(destino), **fechas}


def _sembrar_tdd2_todos(libro) -> dict:
    """Recorre CARPETA_REFERENCIA_TDD2 -- los TDD Nivel 2 reales que ya se
    cargaron ahi, uno por aplicativo -- y los siembra como la referencia
    inicial. La plantilla en blanco se salta sola: no es el TDD de ningun
    aplicativo real.

    Por cada uno que SI se identifica, se adopta una copia de nombre fijo por
    numero en `_estable/` -- esa es la que de verdad se compara despues,
    nunca el archivo original con el nombre que traia."""
    CARPETA_REFERENCIA_TDD2.mkdir(parents=True, exist_ok=True)
    CARPETA_REFERENCIA_TDD2_ESTABLE.mkdir(parents=True, exist_ok=True)
    identificados, sin_identificar, colisiones = [], [], {}
    usados: dict[str, str] = {}

    for ruta in sorted(CARPETA_REFERENCIA_TDD2.glob("*.docx")):
        try:
            if not tdd_nivel2.es_documento_tdd_nivel2(ruta):
                continue
            doc = tdd_nivel2.leer(ruta)
            if tdd_nivel2.es_plantilla_en_blanco(doc):
                continue
        except Exception as exc:
            sin_identificar.append({"nombre": ruta.name, "motivo": f"no se pudo leer: {exc}"})
            continue

        amarre = tdd_nivel2.identificar(doc, libro)
        if not amarre.identificado:
            sin_identificar.append({"nombre": ruta.name,
                                    "motivo": amarre.evidencia or "no se pudo identificar"})
            continue

        if amarre.numero in usados:
            colisiones.setdefault(amarre.numero, [usados[amarre.numero]]).append(ruta.name)
            continue
        usados[amarre.numero] = ruta.name

        destino = CARPETA_REFERENCIA_TDD2_ESTABLE / f"{amarre.numero}.docx"
        shutil.copy2(ruta, destino)
        doc_estable = tdd_nivel2.leer(destino)
        _base().sembrar_tdd2(destino, doc_estable, amarre.numero)
        _base().actualizar_referencia("tdd2", amarre.numero, str(destino), str(ruta))
        identificados.append({"numero": amarre.numero, "nombre": amarre.nombre,
                              "archivo": ruta.name})

    return {"identificados": identificados, "sin_identificar": sin_identificar,
            "colisiones": colisiones}


# ---------------------------------------------------------------------------
# NUCLEO: un archivo -> un activo validado
# ---------------------------------------------------------------------------

class DestinoExcluido(Exception):
    """Se lanza cuando la ruta que se iba a clasificar resulta ser el propio
    libro de APM o un TDD: son destino, no materia prima, y no se procesan
    como si fueran un documento fuente mas."""
    def __init__(self, motivo: str, tipo: str):
        super().__init__(motivo)
        self.motivo = motivo
        self.tipo = tipo


class FalloAnalisis(Exception):
    """Fallo durante el pipeline de analisis (extraccion / reglas / modelo /
    validacion), con el estado de CADA etapa hasta donde se alcanzo a llegar.

    Antes, cualquier fallo en cualquier parte de `_clasificar_ruta` se perdia
    en un solo mensaje generico y la pantalla no tenia forma de saber cual de
    las 4 etapas fue la que de verdad trueno -- terminaba pintando de rojo
    las que alcanzaron a marcarse "activa" del lado del navegador, sin
    relacion con la etapa real. Con esto, cada etapa reporta su propio
    resultado (bien u mal) y la pantalla pinta exactamente lo que paso."""
    def __init__(self, etapa: str, mensaje: str, etapas: dict, status_code: int = 502):
        super().__init__(mensaje)
        self.etapa = etapa
        self.etapas = etapas
        self.status_code = status_code


def _valores_iguales(a: str, b: str) -> bool:
    """Mismo criterio que usa conciliacion.py para no marcar como "diferente"
    lo que solo cambia de acentos, mayusculas o puntuacion."""
    def norm(t):
        import unicodedata
        t = unicodedata.normalize("NFD", str(t or ""))
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
        return re.sub(r"[\s.,;]+", " ", t).strip().lower()
    return norm(a) == norm(b)


# ---------------------------------------------------------------------------
# Resolver por fecha, no por bandeja de revision
# ---------------------------------------------------------------------------
# Regla del proyecto: cuando un documento nuevo contradice lo que ya esta en
# la referencia (el APM o el TDD sembrados), NO se marca "diferente" para que
# alguien lo decida despues -- se decide aqui mismo, comparando la fecha de
# creacion del documento contra la fecha en que se sembro/actualizo la
# referencia. Gana el mas reciente, y no se pregunta.
#
# Solo cuando falta alguna de las dos fechas (documento sin propiedades de
# fecha legibles, o referencia sin sembrar todavia) se cae al modo seguro de
# antes: se marca "diferente" y queda para revisarse a mano en "Comparar APM
# y TDD" -- decidir sin fecha de ninguno de los dos lados si adivinaria, no
# decidiria.

def _fecha_doc(doc: dict | None) -> "datetime | None":
    """La fecha de creacion del documento fuente (o de modificacion, si el
    formato no trae creacion). None si no se pudo leer ninguna de las dos."""
    from datetime import datetime
    props = (doc or {}).get("propiedades") or {}
    for clave in ("creado", "modificado"):
        crudo = str(props.get(clave) or "").strip()
        if not crudo:
            continue
        try:  # Word/Excel/PowerPoint ya entregan ISO 8601
            return datetime.fromisoformat(crudo.replace("Z", "+00:00"))
        except ValueError:
            pass
        m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", crudo)
        if m:  # PDF: "D:20230115120000+00'00'"
            g = [int(x) if x else 0 for x in m.groups()]
            try:
                return datetime(g[0], g[1] or 1, g[2] or 1, g[3], g[4], g[5])
            except ValueError:
                pass
    return None


def _fecha_referencia(tipo: str, numero: str = "") -> "datetime | None":
    """Cuando se sembro (o se actualizo por ultima vez) la copia de
    referencia contra la que se compara: el libro de APM entero, o el TDD de
    este aplicativo. Es el otro lado de la comparacion de `_fecha_doc`."""
    from datetime import datetime
    if BASE is None:
        return None
    try:
        ref = BASE.referencia_de(tipo, numero)
    except Exception:
        ref = None
    if not ref:
        return None
    crudo = str(ref.get("actualizado_en") or ref.get("creado_en") or "").strip()
    try:
        return datetime.fromisoformat(crudo)
    except ValueError:
        return None


def _resolver_conflicto(fecha_doc, fecha_ref, valor_actual: str,
                        valor_propuesto: str, evidencia_propuesto: str,
                        de_donde: str) -> tuple[str, str, str, str]:
    """Decide que hacer con un campo donde la referencia YA tiene un valor y
    el documento dice otra cosa. Devuelve (estado, valor, evidencia, origen).

    Con las dos fechas: gana la mas reciente, sin marcar diferencia -- si es
    el documento, se propone su valor (como si fuera un dato nuevo, para que
    "Llenar documento" y "Hacer nueva version" lo puedan escribir); si es la
    referencia, se deja tal cual, con nota de que se comparo y gano ella.
    Sin las dos fechas, modo seguro: se marca "diferente" para decidirse a
    mano en "Comparar APM y TDD", igual que antes de esta regla.

    La nota de la comparacion viaja en `evidencia` (no solo en `origen`)
    porque es lo que la pantalla de verdad pinta junto a cada campo -- puesta
    solo en `origen` se quedaba invisible para quien revisa."""
    if fecha_doc and fecha_ref:
        if fecha_doc > fecha_ref:
            nota = (f"más reciente que la referencia ({fecha_ref:%d/%m/%Y} → "
                    f"{fecha_doc:%d/%m/%Y}) · reemplaza «{valor_actual}»")
            return ("extraido",
                    valor_propuesto,
                    f"{evidencia_propuesto} · {nota}" if evidencia_propuesto else nota,
                    de_donde)
        return ("heredado", valor_actual,
                f"el documento ({fecha_doc:%d/%m/%Y}) dice «{valor_propuesto}», "
                f"pero es más viejo que la referencia ({fecha_ref:%d/%m/%Y}); "
                "no se toma",
                "ya está en la referencia; gana por ser más reciente")
    return ("diferente", valor_actual, f"el documento dice: {valor_propuesto}",
            "ya está en la referencia; el documento dice otra cosa "
            "(sin fecha de alguno de los dos para decidir solo)")


def _ficha_apm_real(libro: apm.LibroAPM, aplicacion: apm.Aplicacion,
                    hallazgos: dict, doc: dict | None = None) -> dict:
    """La ficha de llenado del paso 5, pero con las columnas REALES del libro
    de APM de este aplicativo -- no la plantilla de 40 campos inventada de
    campos.py. Compara tres cosas por columna escribible:

      - si el libro YA tiene un valor ahi, se muestra tal cual (heredado):
        no hay nada que proponer, ya se sabe.
      - si el libro la tiene vacia y el documento trajo algo, se propone
        (extraido): eso es lo unico que "Llenar documento" aplica.
      - si el libro YA tiene un valor y el documento dice algo distinto, se
        resuelve por fecha (`_resolver_conflicto`): gana el mas reciente
        entre el documento y la referencia, sin preguntar. Solo si a alguno
        de los dos le falta la fecha, se marca (diferente) para decidirse a
        mano en "Comparar APM y TDD".
    """
    grupos_map: dict[str, list] = {}
    conteo = {"extraido": 0, "heredado": 0, "diferente": 0, "faltante": 0}
    fecha_doc = _fecha_doc(doc)
    fecha_ref = _fecha_referencia("apm")

    for col in libro.escribibles:
        actual = str(aplicacion.valores.get(col.clave, "") or "")
        vacio_actual = apm.es_vacio(actual)
        candidatos = hallazgos.get(col.clave) or []
        propuesto = candidatos[0] if candidatos else None

        if propuesto and vacio_actual:
            estado = "extraido"
            valor, evidencia = propuesto.valor, propuesto.evidencia
            origen = f"documento · {propuesto.documento}"
        elif propuesto and not vacio_actual and not _valores_iguales(propuesto.valor, actual):
            estado, valor, evidencia, origen = _resolver_conflicto(
                fecha_doc, fecha_ref, actual, propuesto.valor,
                propuesto.evidencia, f"documento · {propuesto.documento}")
        elif not vacio_actual:
            estado, valor, evidencia, origen = "heredado", actual, "", "ya está en el APM"
        else:
            estado, valor, evidencia, origen = "faltante", "", "", ""

        conteo[estado] += 1
        grupos_map.setdefault(col.grupo or "General", []).append({
            "clave": col.clave, "etiqueta": col.etiqueta, "valor": valor,
            "estado": estado, "origen": origen, "evidencia": evidencia,
        })

    # Las columnas de formula/calculadas (las 2 que `libro.bloqueadas` deja
    # fuera de `escribibles`) se muestran tambien, pero solo de referencia: el
    # valor que el libro YA trae calculado, sin poder editarse ni compararse
    # contra el documento -- por eso llevan su propio estado "calculado" en
    # vez de meterse en el conteo de extraido/heredado/diferente/faltante, que
    # es el que decide el porcentaje de avance del llenado.
    for col in libro.bloqueadas:
        crudo = aplicacion.valores.get(col.clave)
        valor_calc = "" if crudo is None else str(crudo)
        grupos_map.setdefault(col.grupo or "General", []).append({
            "clave": col.clave, "etiqueta": col.etiqueta, "valor": valor_calc,
            "estado": "calculado", "origen": f"columna calculada del libro ({col.motivo})",
            "evidencia": "",
        })

    # `total` incluye las columnas calculadas (libro.bloqueadas), igual que
    # `grupos_map` de arriba -- si no, el resumen dice 40 mientras el grid de
    # campos que se ve en pantalla ya trae 42, y esa es la inconsistencia que
    # se estaba reportando como "solo aparecen 38/40 campos".
    total = sum(conteo.values()) + len(libro.bloqueadas)
    llenos = conteo["extraido"] + conteo["heredado"]
    return {
        "grupos": [{"grupo": g, "campos": c} for g, c in grupos_map.items()],
        "resumen": {
            "total": total, "llenos": llenos,
            "extraidos": conteo["extraido"], "heredados": conteo["heredado"],
            "diferentes": conteo["diferente"], "faltantes": conteo["faltante"],
            "porcentaje": round(llenos * 100 / total) if total else 0,
            "calculados": len(libro.bloqueadas),
        },
    }


def _ficha_apm_nueva(libro: apm.LibroAPM, hallazgos: dict) -> dict:
    """La misma idea que `_ficha_apm_real`, pero para un documento que NO se
    identificó con ningún aplicativo del inventario y aun así trae forma de
    ficha de aplicación (lo que `extraccion.extraer` pudo sacarle). No hay una
    fila existente contra la cual comparar, así que no hay "heredado" ni
    "diferente" -- solo lo que el documento trae (extraído) y lo que falta.
    Esto es una PROPUESTA de aplicación nueva para el inventario, no un
    aplicativo ya dado de alta; no se escribe en el libro real de APM."""
    grupos_map: dict[str, list] = {}
    conteo = {"extraido": 0, "faltante": 0}

    for col in libro.escribibles:
        candidatos = hallazgos.get(col.clave) or []
        propuesto = candidatos[0] if candidatos else None

        if propuesto:
            estado = "extraido"
            valor, evidencia = propuesto.valor, propuesto.evidencia
            origen = f"documento · {propuesto.documento}"
        else:
            estado, valor, evidencia, origen = "faltante", "", "", ""

        conteo[estado] += 1
        grupos_map.setdefault(col.grupo or "General", []).append({
            "clave": col.clave, "etiqueta": col.etiqueta, "valor": valor,
            "estado": estado, "origen": origen, "evidencia": evidencia,
        })

    # Las columnas de formula/calculadas tambien se listan aqui, igual que en
    # `_ficha_apm_real` -- si no, esta vista (aplicacion nueva) se queda corta
    # frente a los campos reales del libro (hoy 45) mientras la otra
    # (aplicativo ya identificado) los muestra todos. Sin una fila real que
    # las calcule no hay valor que mostrar, asi que van vacias y con estado
    # "calculado" (no cuentan para el porcentaje de avance, igual que alla).
    for col in libro.bloqueadas:
        grupos_map.setdefault(col.grupo or "General", []).append({
            "clave": col.clave, "etiqueta": col.etiqueta, "valor": "",
            "estado": "calculado",
            "origen": f"columna calculada del libro ({col.motivo}); "
                      "no hay fila real todavia para calcularla",
            "evidencia": "",
        })

    total = sum(conteo.values()) + len(libro.bloqueadas)
    llenos = conteo["extraido"]
    return {
        "grupos": [{"grupo": g, "campos": c} for g, c in grupos_map.items()],
        "resumen": {
            "total": total, "llenos": llenos,
            "extraidos": conteo["extraido"], "heredados": 0,
            "diferentes": 0, "faltantes": conteo["faltante"],
            "porcentaje": round(llenos * 100 / total) if total else 0,
            "calculados": len(libro.bloqueadas),
        },
    }


def _ficha_tdd_real(ruta_tdd, doc: dict, numero: str = "") -> dict:
    """La ficha del paso 6, pero contra el archivo TDD REAL de este aplicativo
    -- no una plantilla generica: cada uno de los TDD reales trae sus propias
    tablas, asi que no hay un esquema unico como el de las columnas del APM.
    Mismo criterio que `_ficha_apm_real` (extraido / heredado / resuelto por
    fecha / faltante), pero la comparacion es celda-del-TDD contra lo que
    ESTE documento fuente trae (`extraccion.indice_de`), porque el TDD no
    comparte columnas con el APM y cada aplicativo tiene el suyo.
    """
    doc_tdd = tdd.leer(ruta_tdd)
    celdas = tdd.celdas_etiquetadas(ruta_tdd)
    titulos = {t.indice: t.titulo for t in doc_tdd.tablas}

    # Indice etiqueta-normalizada -> (valor, evidencia) de ESTE documento. Se
    # reusa `extraccion.indice_de`, que ya normaliza igual que aqui hace falta
    # (sin acentos, sin mayusculas, sin puntuacion) y respeta "gana la primera".
    pares_doc: dict[str, tuple[str, str]] = {}
    for etiqueta_norm, valor, evidencia in extraccion.indice_de(doc):
        pares_doc.setdefault(etiqueta_norm, (valor, evidencia))

    grupos_map: dict[str, list] = {}
    conteo = {"extraido": 0, "heredado": 0, "diferente": 0, "faltante": 0}
    fecha_doc = _fecha_doc(doc)
    fecha_ref = _fecha_referencia("tdd", numero)

    for celda in celdas:
        etiqueta_tdd = str(celda.get("etiqueta") or "").strip()
        if not etiqueta_tdd:
            continue
        clave = f"t{celda['tabla']}_f{celda['fila']}_c{celda['columna']}"
        actual = str(celda.get("texto") or "").strip()
        vacio_actual = tdd.celda_vacia(actual)

        etiqueta_norm = extraccion._norm(etiqueta_tdd)
        candidato = pares_doc.get(etiqueta_norm)
        if not candidato:
            for clave_doc, val in pares_doc.items():
                if len(etiqueta_norm) >= 5 and re.search(
                        rf"\b{re.escape(etiqueta_norm)}\b", clave_doc):
                    candidato = val
                    break

        if candidato and vacio_actual:
            estado = "extraido"
            valor, evidencia = candidato[0], candidato[1]
            origen = "documento"
        elif candidato and not vacio_actual and not _valores_iguales(candidato[0], actual):
            estado, valor, evidencia, origen = _resolver_conflicto(
                fecha_doc, fecha_ref, actual, candidato[0], candidato[1], "documento")
        elif not vacio_actual:
            estado, valor, evidencia, origen = "heredado", actual, "", "ya está en el TDD"
        else:
            estado, valor, evidencia, origen = "faltante", "", "", ""

        conteo[estado] += 1
        grupo = titulos.get(celda["tabla"], f"Tabla {celda['tabla']}")
        grupos_map.setdefault(grupo, []).append({
            "clave": clave, "etiqueta": etiqueta_tdd, "valor": valor,
            "estado": estado, "origen": origen, "evidencia": evidencia,
        })

    total = sum(conteo.values())
    llenos = conteo["extraido"] + conteo["heredado"]
    return {
        "grupos": [{"grupo": g, "campos": c} for g, c in grupos_map.items()],
        "resumen": {
            "total": total, "llenos": llenos,
            "extraidos": conteo["extraido"], "heredados": conteo["heredado"],
            "diferentes": conteo["diferente"], "faltantes": conteo["faltante"],
            "porcentaje": round(llenos * 100 / total) if total else 0,
        },
        "documento_origen": Path(ruta_tdd).name,
        "es_propuesta": False,
    }


def _extraer_generico(doc: dict, campos_lista: list[dict],
                      nombre_documento: str) -> dict[str, tuple[str, str]]:
    """Como `extraccion.extraer`, pero sin necesitar un libro de APM real
    abierto: en vez de las columnas de un Excel, usa el catalogo ESTATICO de
    `campos.py` (grupo/clave/etiqueta/pistas). Se usa solo cuando no hay
    ningun libro sembrado en la base -- si lo hay, `extraccion.extraer()` ya
    hace este mismo trabajo con las columnas reales, que es mejor fuente."""
    pares = extraccion.indice_de(doc)
    salida: dict[str, tuple[str, str]] = {}

    for campo in campos_lista:
        etiquetas = {extraccion._norm(campo["etiqueta"])}
        etiquetas.update(extraccion._norm(p) for p in campo.get("pistas") or [])
        etiquetas.discard("")

        encontrado = None
        for clave, valor, ev in pares:
            if clave in etiquetas:
                encontrado = (valor, ev)
                break
        if not encontrado:
            for clave, valor, ev in pares:
                for e in etiquetas:
                    if len(e) >= 5 and re.search(rf"\b{re.escape(e)}\b", clave):
                        encontrado = (valor, ev)
                        break
                if encontrado:
                    break
        if encontrado:
            salida[campo["clave"]] = encontrado

    return salida


def _ficha_generica(campos_lista: list[dict], hallazgos: dict[str, tuple[str, str]],
                    nombre_documento: str) -> dict:
    """El PISO de paso 5 y 6: cuando no hay ningun libro de APM sembrado en la
    base (o la vinculacion fallo), esto es lo que se muestra en vez de nada.
    Usa el catalogo ESTANDAR de campos.py (40 de APM / 34 de TDD) en vez de
    columnas reales, asi que todo viaja como "extraido" (lo que el documento
    trae) o "faltante" -- no hay "heredado" ni "diferente" porque no hay
    ninguna fila real con la cual comparar, ni "calculado" porque no hay
    formulas de un Excel abierto que proteger. Misma regla de siempre: nada
    se inventa, lo que el documento no dice se queda vacio y marcado."""
    grupos_map: dict[str, list] = {}
    conteo = {"extraido": 0, "faltante": 0}

    for campo in campos_lista:
        par = hallazgos.get(campo["clave"])
        if par:
            estado, valor, evidencia = "extraido", par[0], par[1]
            origen = f"documento · {nombre_documento}"
        else:
            estado, valor, evidencia, origen = "faltante", "", "", ""

        conteo[estado] += 1
        grupos_map.setdefault(campo["grupo"], []).append({
            "clave": campo["clave"], "etiqueta": campo["etiqueta"], "valor": valor,
            "estado": estado, "origen": origen, "evidencia": evidencia,
        })

    total = sum(conteo.values())
    llenos = conteo["extraido"]
    return {
        "grupos": [{"grupo": g, "campos": c} for g, c in grupos_map.items()],
        "resumen": {
            "total": total, "llenos": llenos, "extraidos": conteo["extraido"],
            "heredados": 0, "diferentes": 0, "faltantes": conteo["faltante"],
            "porcentaje": round(llenos * 100 / total) if total else 0,
            "calculados": 0,
        },
        "sin_libro": True,
    }


def _ficha_tdd_propuesta(doc: dict) -> dict | None:
    """No hay un TDD real con el cual comparar: ni el aplicativo lo tiene
    sembrado de los 17 que ya se leyeron, ni el documento se identificó con
    ninguno (aplicación nueva). Sin un TDD real no hay tabla ni etiquetas
    contra las cuales comparar -- no hay "heredado", "diferente" ni "falta"
    que reportar con sentido, porque el TDD no tiene un esquema unico como el
    APM. Lo unico honesto es mostrar tal cual lo que ESTE documento trae en
    forma de ficha (etiqueta: valor), como una PROPUESTA para cuando exista un
    TDD real que llenar -- nunca como si ya se hubiera comparado contra algo.

    Si el documento no trae nada reconocible, no hay nada que mostrar: se
    devuelve None y el paso 6 no pinta ninguna ficha ("si no hay información
    no pongas nada")."""
    pares = extraccion.indice_de(doc)
    if not pares:
        return None

    # Si una etiqueta se repite (p.ej. la misma tabla vista por la lectura
    # ancha y otra vez por la generica), gana la PRIMERA -- mismo criterio
    # que `indice_de` ya documenta y que `_ficha_tdd_real` ya aplica; sin
    # esto, la misma etiqueta aparecia dos veces en la ficha.
    vistos: dict[str, tuple[str, str]] = {}
    for etiqueta_norm, valor, evidencia in pares:
        vistos.setdefault(etiqueta_norm, (valor, evidencia))

    grupo_nombre = "Del documento (sin TDD real con el cual comparar)"
    campos = [{
        "clave": etiqueta_norm, "etiqueta": etiqueta_norm.capitalize(),
        "valor": valor, "estado": "extraido", "origen": "documento",
        "evidencia": evidencia,
    } for etiqueta_norm, (valor, evidencia) in vistos.items()]

    total = llenos = len(campos)
    return {
        "grupos": [{"grupo": grupo_nombre, "campos": campos}],
        "resumen": {
            "total": total, "llenos": llenos,
            "extraidos": total, "heredados": 0, "diferentes": 0, "faltantes": 0,
            "porcentaje": 100 if total else 0,
        },
        "documento_origen": "",
        "es_propuesta": True,
    }


def _ficha_tdd2_real(ruta_tdd2, ruta_subido: Path | None, doc: dict,
                     numero: str = "") -> dict:
    """La ficha del paso 6, contra el TDD NIVEL 2 real de este aplicativo (la
    referencia ya sembrada en base_tdd2) -- reemplaza a `_ficha_tdd_real`,
    que comparaba contra el TDD_V3 viejo.

    El TDD Nivel 2 nunca se llena citando al APM ni con texto adivinado por
    palabra clave (regla del proyecto, ver tdd_nivel2.py): por eso aqui solo
    se propone un valor NUEVO para un campo cuando el documento que se acaba
    de subir es, el mismo, un TDD Nivel 2 real (`ruta_subido` pasa
    `es_documento_tdd_nivel2`) -- nunca buscando la etiqueta del campo dentro
    de un documento cualquiera. Si lo que se subio no es un TDD Nivel 2, la
    ficha muestra tal cual lo que la referencia YA tiene (heredado), sin
    proponer nada nuevo: es la unica forma honesta, porque no hay de donde
    mas sacar un dato real de este formulario."""
    referencia = tdd_nivel2.leer(ruta_tdd2)

    nuevo = None
    if ruta_subido is not None:
        try:
            if ruta_subido.exists() and tdd_nivel2.es_documento_tdd_nivel2(ruta_subido):
                candidato = tdd_nivel2.leer(ruta_subido)
                if not tdd_nivel2.es_plantilla_en_blanco(candidato):
                    nuevo = candidato
        except Exception:
            log.exception("no se pudo leer el TDD Nivel 2 subido para compararlo")

    campos_nuevo = {c.llave: c for c in nuevo.campos} if nuevo else {}
    grupos_map: dict[str, list] = {}
    conteo = {"extraido": 0, "heredado": 0, "diferente": 0, "faltante": 0}

    for campo_ref in referencia.campos:
        actual = campo_ref.valor if not campo_ref.vacio else ""
        candidato = campos_nuevo.get(campo_ref.llave)
        cand_vacio = (candidato is None) or candidato.vacio

        if candidato and not cand_vacio and not actual:
            estado = "extraido"
            valor = candidato.valor
            evidencia = f"confianza declarada: {candidato.confianza}" if candidato.confianza else ""
            origen = "documento"
        elif candidato and not cand_vacio and actual and not _valores_iguales(candidato.valor, actual):
            estado, valor = "diferente", actual
            evidencia, origen = "la referencia y el documento no dicen lo mismo", "documento"
        elif actual:
            estado, valor, evidencia, origen = "heredado", actual, "", "ya está en el TDD"
        else:
            estado, valor, evidencia, origen = "faltante", "", "", ""

        conteo[estado] += 1
        grupo = campo_ref.seccion_titulo or campo_ref.seccion
        grupos_map.setdefault(grupo, []).append({
            "clave": campo_ref.llave, "etiqueta": campo_ref.campo, "valor": valor,
            "estado": estado, "origen": origen, "evidencia": evidencia,
            "tabla_indice": campo_ref.tabla_indice, "fila_indice": campo_ref.fila_indice,
        })

    total = sum(conteo.values())
    llenos = conteo["extraido"] + conteo["heredado"]
    return {
        "grupos": [{"grupo": g, "campos": c} for g, c in grupos_map.items()],
        "resumen": {
            "total": total, "llenos": llenos,
            "extraidos": conteo["extraido"], "heredados": conteo["heredado"],
            "diferentes": conteo["diferente"], "faltantes": conteo["faltante"],
            "porcentaje": round(llenos * 100 / total) if total else 0,
        },
        "documento_origen": Path(ruta_tdd2).name,
        "es_propuesta": False,
    }


def _ficha_tdd2_propuesta(ruta_subido: Path | None, doc: dict) -> dict | None:
    """Como `_ficha_tdd_propuesta`, pero para TDD Nivel 2: no hay todavia un
    TDD Nivel 2 real sembrado para este aplicativo con el cual comparar. Si
    lo que se subio ES, el mismo, un TDD Nivel 2 real (no la plantilla en
    blanco), se propone tal cual lo que ese documento trae -- por seccion,
    con su propia confianza declarada. Si lo que se subio no es un TDD Nivel
    2, no hay nada honesto que proponer (no se llena por palabra clave desde
    un documento cualquiera): se devuelve None, igual que antes."""
    if ruta_subido is None or not ruta_subido.exists():
        return None
    try:
        if not tdd_nivel2.es_documento_tdd_nivel2(ruta_subido):
            return None
        candidato = tdd_nivel2.leer(ruta_subido)
    except Exception:
        return None
    if tdd_nivel2.es_plantilla_en_blanco(candidato):
        return None

    grupos_map: dict[str, list] = {}
    for c in candidato.campos:
        if c.vacio:
            continue
        grupo = c.seccion_titulo or c.seccion
        grupos_map.setdefault(grupo, []).append({
            "clave": c.llave, "etiqueta": c.campo, "valor": c.valor,
            "estado": "extraido", "origen": "documento",
            "evidencia": f"confianza declarada: {c.confianza}" if c.confianza else "",
            "tabla_indice": c.tabla_indice, "fila_indice": c.fila_indice,
        })
    if not grupos_map:
        return None

    total = llenos = sum(len(v) for v in grupos_map.values())
    return {
        "grupos": [{"grupo": g, "campos": c} for g, c in grupos_map.items()],
        "resumen": {
            "total": total, "llenos": llenos,
            "extraidos": total, "heredados": 0, "diferentes": 0, "faltantes": 0,
            "porcentaje": 100 if total else 0,
        },
        "documento_origen": "",
        "es_propuesta": True,
    }


def _ficha_tdd_para_numero(numero: str, doc: dict, ruta: Path | None = None) -> dict | None:
    """Ficha de TDD Nivel 2 para un aplicativo YA identificado (numero
    conocido, sea por amarre automatico o elegido a mano): real si tiene un
    TDD Nivel 2 sembrado de los que ya se leyeron de CARPETA_REFERENCIA_TDD2,
    propuesta si no. Reemplaza la version que comparaba contra el TDD_V3
    viejo (`BASE.tdd_de`) -- el TDD Nivel 2 es la plantilla vigente. Funcion
    compartida para que las dos vias construyan la ficha exactamente igual."""
    if BASE is not None:
        try:
            tdds2 = BASE.tdd2_de(numero)
        except Exception:
            tdds2 = []
        if tdds2:
            try:
                return _ficha_tdd2_real(tdds2[0]["ruta"], ruta, doc, numero)
            except Exception:
                log.exception("no se pudo construir la ficha de TDD Nivel 2 real")
    return _ficha_tdd2_propuesta(ruta, doc)


def _vincular_aplicativo(ruta: Path, nombre: str, doc: dict, texto: str,
                         ruta_apm: str) -> dict:
    """Amarra el documento a uno de los aplicativos reales del APM, y dice si
    lo que trae es util o no. Es la pieza que hasta la v7 no existia en el
    asistente de 6 pasos: un documento podia clasificarse sin que nadie supiera
    a que aplicativo, o a que TDD, correspondia.

    Tres preguntas, en orden:
      1. ¿A que aplicativo pertenece? (identificacion.identificar)
      2. ¿Trae algun dato que sirva para un campo real del APM o del TDD?
         (extraccion.extraer, contra las columnas REALES del libro -- no la
         plantilla generica de campos.py)
      3. ¿Ya se habia leido este mismo contenido antes? (huella en el almacen)

    El resultado viaja en `activo["_apm"]` y es lo que la pantalla de Revision
    usa para mostrar «este documento se identificó como #12 · Portal
    Unificado» en vez de dejarlo sin ninguna referencia.
    """
    resultado: dict = {"disponible": False}
    try:
        libro = _libro(ruta_apm)
    except HTTPException as exc:
        resultado["error"] = exc.detail
        return resultado

    resultado["disponible"] = True
    amarre = identificacion.identificar(texto[:20_000], nombre, libro)
    resultado.update({
        "identificado": amarre.identificado, "numero": amarre.numero,
        "nombre_aplicativo": amarre.nombre, "id_habilitador": amarre.id_habilitador,
        "senal": amarre.senal, "evidencia": amarre.evidencia,
        "candidatos": amarre.candidatos,
    })

    # La extraccion ya no depende de estar identificado: las etiquetas que
    # busca salen de las columnas del libro (iguales para cualquier fila), asi
    # que sirven tanto para comparar contra un aplicativo YA en el inventario
    # como para notar que un documento no identificado trae, de todos modos,
    # forma de ficha de aplicacion -- la señal de "aplicacion nueva" de abajo.
    hallazgos = extraccion.extraer(doc, libro, nombre)
    resultado["campos_encontrados"] = len(hallazgos)

    # La ficha del paso 5. Dos casos, nunca "llenar por llenar":
    #   identificado         -> se compara contra la fila real de ese
    #                           aplicativo (heredado/extraido/diferente/falta)
    #   no identificado
    #   pero con hallazgos    -> no hay fila contra la cual comparar, pero el
    #                           documento SI trae pinta de ficha de aplicacion:
    #                           se propone como aplicacion nueva para el
    #                           inventario (todo extraido o falta, nada que
    #                           heredar ni con que discrepar todavia)
    #   no identificado
    #   y sin hallazgos       -> no hay ficha. Esto sigue siendo "no llenar
    #                           por llenar": nada que decir, nada que mostrar.
    if amarre.identificado:
        app_real = libro.aplicacion(numero=amarre.numero)
        if app_real is not None:
            resultado["ficha_apm"] = _ficha_apm_real(libro, app_real, hallazgos, doc)
    else:
        # Sin identificar -- con hallazgos o sin ellos, se muestra la ficha
        # de todos los campos del libro siempre: con hallazgos, es una
        # propuesta real de aplicacion nueva (extraido/falta); sin hallazgos,
        # son los mismos campos pero todos en "falta". La estructura se ve
        # siempre; nunca se esconde la pantalla completa solo porque no hubo nada que proponer
        # -- eso era justo lo que se veia "vacio" y confundia. `aplicacion_
        # nueva` distingue el caso con datos del caso realmente vacio, para
        # que la cabecera diga el mensaje correcto.
        resultado["aplicacion_nueva"] = bool(hallazgos)
        resultado["ficha_apm"] = _ficha_apm_nueva(libro, hallazgos)
        # Sin aplicativo identificado tampoco hay un TDD real (ni siquiera
        # sembrado) contra el cual comparar: se propone con lo que el
        # documento trae, igual criterio que con el APM de arriba. No se usa
        # la plantilla generica del principio del proyecto: esa solo aplica
        # aqui si mas adelante se confirma su ubicación real. Si el documento
        # no trae nada reconocible tampoco, `_ficha_tdd_propuesta` devuelve
        # None y el modulo 6 simplemente no tiene nada que pintar (el TDD no
        # tiene un esquema fijo como el APM, asi que ahi si puede no haber
        # nada que mostrar).
        resultado["ficha_tdd"] = _ficha_tdd2_propuesta(ruta, doc)

    ya_conocido, trae_novedad, huella = False, bool(hallazgos), None
    try:
        huella = almacen.huella_de(ruta)
    except OSError:
        huella = None

    if BASE is not None and huella:
        previo = BASE.documento_conocido(huella)
        if previo:
            ya_conocido = True
            previos = {h["clave"]: h["valor"] for h in previo.get("hallazgos", [])}
            actuales = {k: v[0].valor for k, v in hallazgos.items()}
            trae_novedad = bool(actuales) and actuales != previos
        resultado["ya_conocido"] = ya_conocido
        resultado["trae_novedad"] = trae_novedad
        resultado["veces_visto"] = previo["veces_visto"] if previo else 0
        resultado["leido_en_antes"] = previo["leido_en"] if previo else ""

        # Se registra siempre que haya numero -- identificado y con o sin
        # hallazgos -- para no volver a leerlo. Si no trae novedad sobre lo
        # que ya se sabia, no hay nada que reescribir en la base.
        if amarre.identificado and (not previo or trae_novedad):
            try:
                BASE.registrar_documento(
                    huella, nombre, str(ruta), "ruta",
                    ruta.stat().st_size if ruta.exists() else 0,
                    amarre.numero, amarre.senal, amarre.evidencia,
                    {k: (v[0].valor, v[0].evidencia) for k, v in hallazgos.items()})
            except Exception:
                log.exception("no se pudo registrar el documento en el almacen")

        if amarre.identificado:
            try:
                resultado["tdd"] = BASE.tdd2_de(amarre.numero)
            except Exception:
                resultado["tdd"] = []
            resultado["ficha_tdd"] = _ficha_tdd_para_numero(amarre.numero, doc, ruta)
    else:
        resultado["ya_conocido"] = False

    # Red de seguridad: si por lo que sea (base no disponible, sin huella) el
    # bloque de arriba no llego a decidir la ficha de TDD para un aplicativo
    # identificado, se cae en la propuesta antes que dejarlo sin nada.
    if amarre.identificado and "ficha_tdd" not in resultado:
        resultado["ficha_tdd"] = _ficha_tdd2_propuesta(ruta, doc)

    # `valido`/`motivo` ya NO ocultan nada en la pantalla de un solo documento
    # (paso 1): ese flujo siempre pasa a Revision con su ficha completa
    # (todos los campos, llenos o en falta) y estos dos campos solo alimentan
    # la leyenda que explica por que. Donde SI siguen filtrando es en el
    # escaneo por carpeta (lote): con los aplicativos de por medio, forzar a revisar
    # uno por uno los que no aportan nada inundaria la lista -- ahi se quedan
    # agrupados en "omitidos", con el mismo motivo visible.
    #   no se identifico Y tampoco trae pinta de ficha de aplicacion ->
    #       no hay ninguna relacion, ni con un aplicativo existente ni con uno
    #       nuevo
    #   ya se habia visto y no trae nada nuevo -> ya se sabia lo que dice
    if not amarre.identificado and not hallazgos:
        resultado["valido"] = False
        resultado["motivo"] = ("No se pudo identificar a qué aplicativo del "
                               "inventario pertenece este documento, y tampoco "
                               "trae ningún dato reconocible de una ficha de "
                               "aplicación.")
    elif ya_conocido and not trae_novedad:
        resultado["valido"] = False
        resultado["motivo"] = ("Ya se había escaneado este documento antes y no "
                               "trae información nueva.")
    else:
        resultado["valido"] = True
        resultado["motivo"] = ""
    return resultado


def _clasificar_ruta(ruta: str, nombre: str,
                     ruta_apm: str = "", forzar: bool = False,
                     on_etapa=None) -> tuple[dict, dict, str, dict]:
    """Devuelve (activo_validado, doc_parseado, proveedor, etapas).

    `etapas` trae el resultado de cada una de las 4 etapas del pipeline
    (extraccion, reglas, modelo, validacion) con datos reales -- nombre del
    archivo, extension, cuanto texto/cuantas imagenes se leyeron, etc. -- para
    que la pantalla no tenga que fingir que sabe que paso adentro.

    Antes que nada, sin importar si ya hay un `ruta_apm` sembrado o no: si la
    ruta ES el libro de APM o un TDD (por estructura, no por nombre), se corta
    aqui con `DestinoExcluido` -- son destino, no se clasifican como fuente.
    Esto es lo que permite subir el propio libro de APM o un TDD desde Inicio,
    incluso la primerísima vez que no hay nada sembrado todavía: quien llama
    (`_responder_uno`) usa esa excepcion para sembrar la referencia en vez de
    tratarlo como un documento a clasificar.

    Si `ruta_apm` esta dado y es un documento fuente, se amarra a un
    aplicativo real del inventario y el resultado viaja en `activo["_apm"]`.

    Si cualquier etapa truena, se lanza `FalloAnalisis` con el estado de las
    etapas alcanzadas hasta ese punto, para que quien llame pueda reportar
    con precision cual fue la que fallo.
    """
    etapas: dict[str, dict] = {}

    papel = identificacion.clasificar_archivo(Path(ruta))
    if on_etapa:
        on_etapa("identificacion", {"estado": "ok", "tipo": papel.tipo,
                                     "es_fuente": papel.es_fuente, "motivo": papel.motivo})
    if not papel.es_fuente and not forzar:
        raise DestinoExcluido(papel.motivo, papel.tipo)

    # --- 1) Extraccion del contenido ---------------------------------------
    extension = Path(nombre).suffix.lower()
    try:
        doc = parsers.parse(ruta, nombre)
    except (FormatoNoSoportado, DocumentoIlegible) as exc:
        etapas["extraccion"] = {
            "estado": "fallida", "archivo": nombre, "extension": extension,
            "detalle": str(exc),
        }
        if on_etapa:
            on_etapa("extraccion", etapas["extraccion"])
        raise FalloAnalisis("extraccion", str(exc), etapas, status_code=400) from exc
    etapas["extraccion"] = {
        "estado": "ok", "archivo": nombre, "extension": extension,
        "formato": doc["formato"], "paginas": doc["n_paginas"],
    }
    if on_etapa:
        on_etapa("extraccion", etapas["extraccion"])

    # --- 2) Deteccion determinista ------------------------------------------
    try:
        candidatos = deteccion.detectar_candidatos(doc)
        texto = deteccion.bloque_para_modelo(doc)
    except Exception as exc:
        etapas["reglas"] = {
            "estado": "fallida", "extension": extension, "detalle": str(exc),
        }
        if on_etapa:
            on_etapa("reglas", etapas["reglas"])
        raise FalloAnalisis("reglas", str(exc), etapas) from exc
    etapas["reglas"] = {
        "estado": "ok", "extension": extension, "cumple_criterios": True,
        "candidatos_detectados": len(candidatos), "caracteres_leidos": len(texto),
        "contenido_truncado": "contenido intermedio truncado" in texto,
        # Lo que de verdad detectaron las reglas (version, fecha, responsable,
        # estado, confidencialidad) -- antes solo se mandaba el CONTEO, y la
        # pantalla de avance en vivo no tenia nada real que mostrar mientras
        # corria esta etapa.
        "campos_detectados": {clave: c["valor"] for clave, c in candidatos.items()},
    }
    if on_etapa:
        on_etapa("reglas", etapas["reglas"])

    # --- 3) Clasificacion con IA --------------------------------------------
    proveedor, clasificar = _proveedor()
    n_imagenes = len(doc.get("imagenes") or [])
    try:
        crudo = clasificar(texto, candidatos, doc["imagenes"])
    except Exception as exc:
        etapas["modelo"] = {
            "estado": "fallida", "proveedor": proveedor,
            "caracteres_texto": len(texto), "imagenes_encontradas": n_imagenes,
            "detalle": str(exc),
        }
        if on_etapa:
            on_etapa("modelo", etapas["modelo"])
        raise FalloAnalisis("modelo", str(exc), etapas) from exc
    etapas["modelo"] = {
        "estado": "ok", "proveedor": proveedor,
        "caracteres_texto": len(texto), "imagenes_encontradas": n_imagenes,
        "uso": crudo.get("_uso"),
    }
    if on_etapa:
        on_etapa("modelo", etapas["modelo"])

    # --- 4) Validacion y arbitraje -------------------------------------------
    try:
        activo = metadata_validator.validar(crudo, candidatos, doc)
    except Exception as exc:
        etapas["validacion"] = {"estado": "fallida", "detalle": str(exc)}
        if on_etapa:
            on_etapa("validacion", etapas["validacion"])
        raise FalloAnalisis("validacion", str(exc), etapas) from exc
    etapas["validacion"] = {
        "estado": "ok",
        "campos_por_revisar": len(activo.get("requiere_revision") or []),
    }
    if on_etapa:
        on_etapa("validacion", etapas["validacion"])

    # El titulo no es un campo del modelo: sale del documento, que es mas fiable.
    activo["titulo"] = doc["titulo_probable"] or Path(nombre).stem

    # Propuesta de llenado de paso 5/6. Cuando hay un libro de APM sembrado
    # (`ruta_apm`) y el documento se amarra a un aplicativo real, son las
    # columnas REALES de ese aplicativo, comparadas contra lo que el libro ya
    # tiene -- eso vive en `_vincular_aplicativo` y no cambia aqui.
    #
    # PERO paso 5 y 6 NUNCA deben quedarse sin nada que mostrar, tenga o no
    # tenga la base un libro sembrado: si no hay `ruta_apm`, o el amarre
    # fallo, no hay ninguna razon para dejar la pantalla vacia -- se cae al
    # catalogo ESTANDAR de campos.py (40 de APM / 34 de TDD) como piso. Esto
    # es justo lo que separa "Revision Manual APM y TDD" (que siembra el
    # libro real y permite comparar contra un aplicativo real) de paso 5/6
    # (que siempre funcionan, con o sin libro sembrado): son dos cosas
    # independientes a proposito, y una no deberia bloquear a la otra.
    if ruta_apm:
        try:
            activo["_apm"] = _vincular_aplicativo(Path(ruta), nombre, doc, texto, ruta_apm)
        except Exception:
            log.exception("no se pudo vincular el documento a un aplicativo")
            activo["_apm"] = {
                "disponible": False, "identificado": False, "aplicacion_nueva": False,
                "motivo": "no se pudo completar la vinculación",
            }
    else:
        activo["_apm"] = {
            "disponible": False, "identificado": False, "aplicacion_nueva": False,
            "sin_libro": True,
            "motivo": "no hay ningún libro de APM sembrado en esta base",
        }
    if on_etapa:
        on_etapa("vinculacion", activo["_apm"])

    ficha_apm = activo["_apm"].get("ficha_apm")
    ficha_tdd = activo["_apm"].get("ficha_tdd")

    if not ficha_apm:
        hallazgos_apm = _extraer_generico(doc, campos.de("apm"), nombre)
        ficha_apm = _ficha_generica(campos.de("apm"), hallazgos_apm, nombre)
    if not ficha_tdd:
        hallazgos_tdd = _extraer_generico(doc, campos.de("tdd"), nombre)
        ficha_tdd = _ficha_generica(campos.de("tdd"), hallazgos_tdd, nombre)

    activo["_llenado"] = {"apm": ficha_apm, "tdd": ficha_tdd}

    # Diagramas del documento, para modulo 6 ("ventana aparte"). Las imagenes
    # NUNCA se guardan en disco (ver parsers/imagenes.py): viven en memoria
    # solo durante esta peticion y viajan tal cual al navegador dentro de esta
    # misma respuesta JSON -- no se persisten en el almacen ni en ningun
    # archivo. Se omite "bytes" (es solo un contador interno, no le sirve al
    # navegador) y se manda origen + el base64 que el navegador ya puede
    # pintar directo en un <img src="data:...">.
    activo["_imagenes"] = [
        {"media_type": im.get("media_type", ""), "base64": im.get("base64", ""),
         "origen": im.get("origen", "")}
        for im in (doc.get("imagenes") or [])
        if im.get("base64")
    ]

    # Instantanea del documento ya parseado, para que el selector manual de
    # modulo 5/6 pueda volver a comparar contra OTRO aplicativo sin tener que
    # releer el archivo del disco. Sin esto, un documento subido desde el
    # navegador (su temporal ya se borro cuando termina esta peticion) se
    # quedaba sin poder usar el selector manual -- "Comparar contra" aparecia
    # pero apagado, con la nota de que solo funciona con documentos abiertos
    # por ruta. Con la instantanea, funciona igual hayan subido el archivo o
    # pegado su ruta. Solo se guardan los tres campos que `extraccion.extraer`
    # y `extraccion.indice_de` de verdad leen (tablas, parrafos, propiedades)
    # -- ni las imagenes (ya viajan aparte arriba) ni el resto, para no doblar
    # el peso de la respuesta con datos que nadie vuelve a usar.
    activo["_doc_snapshot"] = {
        "tablas": doc.get("tablas") or [],
        "parrafos": doc.get("parrafos") or [],
        "propiedades": doc.get("propiedades") or {},
    }

    return activo, doc, proveedor, etapas


def _texto_para_markdown(doc: dict, limite: int = 40_000) -> str:
    """El cuerpo que se guarda en el .md. Son los chunks del indice, asi que
    se conserva la estructura de secciones y tablas, no un chorro plano."""
    partes = []
    if doc["encabezados"]:
        partes.append("### Secciones\n\n" +
                      "\n".join(f"- {t}" for t in doc["encabezados"][:80]))
    if doc["parrafos"]:
        partes.append("### Texto\n\n" + "\n\n".join(doc["parrafos"]))
    for i, tabla in enumerate(doc["tablas"][:15], start=1):
        etiqueta = f"Tabla {i}"
        if tabla.get("hoja"):
            etiqueta += f" (hoja '{tabla['hoja']}')"
        filas = tabla["filas"][:30]
        if not filas:
            continue
        md = ["| " + " | ".join(filas[0]) + " |",
              "|" + "---|" * len(filas[0])]
        md += ["| " + " | ".join(f) + " |" for f in filas[1:]]
        partes.append(f"### {etiqueta}\n\n" + "\n".join(md))
    texto = "\n\n".join(partes)
    return texto[:limite] + ("\n\n[... contenido truncado ...]"
                             if len(texto) > limite else "")


# ---------------------------------------------------------------------------
# PANTALLA Y CATALOGOS
# ---------------------------------------------------------------------------

# v10: el front que antes era un solo index.html con 11 secciones que se
# mostraban/escondian con JavaScript (ver el index.html viejo en v9) ahora es
# de verdad 11 paginas -- una por pantalla, cada una con su propio .js -- para
# que cambiar una no obligue a leer ni tocar las otras diez. Lo unico que
# siguen compartiendo es el esqueleto (cabecera, sellos de navegacion, franja
# de pasos) y la hoja de estilos: viven en _layout.html y comun.css, y esta
# funcion es la unica que arma la pagina final, igual de simple que la
# version anterior (nada de un motor de plantillas nuevo, solo remplazos de
# texto).
_LAYOUT = (FRONTEND_DIR / "templates" / "_layout.html").read_text(encoding="utf-8")

_PASOS_NAV = """
<nav class="pasos-nav contenedor" id="pasos-nav">
  <a class="paso-chip" data-ir="1" href="/"><b>1</b> Origen</a>
  <a class="paso-chip" data-ir="2" href="/paso/2"><b>2</b> Alcance</a>
  <a class="paso-chip" data-ir="3" href="/paso/3"><b>3</b> Análisis - IA Ready</a>
  <a class="paso-chip" data-ir="4" href="/paso/4"><b>4</b> Revisión y Vectorización</a>
  <a class="paso-chip" data-ir="5" href="/paso/5"><b>5</b> Llenado de APM</a>
  <a class="paso-chip" data-ir="6" href="/paso/6"><b>6</b> Llenado de TDD</a>
  <a class="paso-chip" data-ir="7" href="/paso/7"><b>7</b> Exportación de Vectorización</a>
</nav>
""".strip()


def _con_version(url: str) -> str:
    """Cache-busting igual que en la v9: se le pega la fecha de modificacion
    del archivo como querystring, para que el navegador no se quede con una
    copia vieja en cache tras un cambio."""
    ruta = FRONTEND_DIR / url.replace("/static/", "static/", 1)
    version = int(ruta.stat().st_mtime) if ruta.exists() else 0
    return f"{url}?v={version}"


def _pantalla(nombre_archivo: str, js_pantalla: str | None,
              paso: int | None = None) -> str:
    """Arma una pagina completa: el layout comun + el fragmento propio de esa
    pantalla (frontend/templates/pantallas/<nombre_archivo>) + su propio
    script. `paso` solo se pone en las 7 del asistente -- pinta la franja de
    chips de arriba y le dice a comun.js en cual va (para marcar el chip
    activo y bloquear los que todavia no se alcanzan)."""
    contenido = (FRONTEND_DIR / "templates" / "pantallas" / nombre_archivo
                 ).read_text(encoding="utf-8")
    html = _LAYOUT
    html = html.replace("{{CONTENIDO}}", contenido)
    html = html.replace("{{PASO}}", str(paso) if paso else "")
    html = html.replace("{{NAV_PASOS}}", _PASOS_NAV if paso else "")
    js_tag = (f'<script src="{_con_version(f"/static/pantallas/{js_pantalla}")}"></script>'
              if js_pantalla else "")
    html = html.replace("{{JS_PANTALLA}}", js_tag)
    html = html.replace('href="/static/comun/comun.css"',
                         f'href="{_con_version("/static/comun/comun.css")}"')
    html = html.replace('src="/static/comun/comun.js"',
                         f'src="{_con_version("/static/comun/comun.js")}"')
    return html


@app.get("/", response_class=HTMLResponse)
def pantalla_paso_1():
    return _pantalla("paso-1.html", "paso1.js", paso=1)


@app.get("/paso/{n}", response_class=HTMLResponse)
def pantalla_paso(n: int):
    if n not in range(2, 8):
        raise HTTPException(404, "Paso no valido.")
    return _pantalla(f"paso-{n}.html", f"paso{n}.js", paso=n)


@app.get("/conciliar", response_class=HTMLResponse)
def pantalla_conciliar():
    return _pantalla("conciliar.html", "conciliar.js")


@app.get("/tdd2", response_class=HTMLResponse)
def pantalla_tdd2():
    return _pantalla("tdd2.html", "tdd2.js")


@app.get("/docs", response_class=HTMLResponse)
def pantalla_docs():
    return _pantalla("docs.html", "docs.js")


@app.get("/config", response_class=HTMLResponse)
def pantalla_config():
    return _pantalla("config.html", "config.js")


# ---------------------------------------------------------------------------
# SESION DEL ASISTENTE (v10)
# ---------------------------------------------------------------------------
# Antes todo esto vivia en el objeto `S` de app.js, en memoria del navegador,
# porque las 7 pantallas del asistente eran en realidad una sola pagina que
# nunca se recargaba. Al volverse 7 paginas de verdad (una por paso), navegar
# de una a otra recarga el navegador y ese `S` se pierde -- asi que el
# documento que se esta revisando (y la vista previa del paso 2) ahora vive
# aqui, del lado del servidor, con el mismo criterio que ya tenia lotes.py:
# en memoria del proceso, sin persistir a disco. Ver sesion.py.

@app.get("/api/sesion/{clave}")
def sesion_leer(clave: str):
    valor = sesion.obtener(clave)
    if valor is None:
        raise HTTPException(404, f"No hay '{clave}' guardado en esta sesión.")
    return valor


@app.post("/api/sesion/{clave}")
def sesion_guardar(clave: str, payload: dict = Body(...)):
    sesion.guardar(clave, payload)
    return {"ok": True}


@app.get("/api/sesion/lote/{lote_id}")
def sesion_leer_editados_lote(lote_id: str):
    """Que indices del lote ya tienen una edicion guardada -- usado por el
    panel fijo de habilitadores del paso 4 para pintar quien va "revisado"
    sin pedir cada documento uno por uno."""
    return {"editados": sesion.obtener_indices_editados(lote_id)}


@app.get("/api/sesion/lote/{lote_id}/{indice}")
def sesion_leer_item_lote(lote_id: str, indice: int):
    item = sesion.obtener_item_lote(lote_id, indice)
    if item is None:
        raise HTTPException(404, "Sin ediciones guardadas para ese documento del lote.")
    return item


@app.post("/api/sesion/lote/{lote_id}/{indice}")
def sesion_guardar_item_lote(lote_id: str, indice: int, payload: dict = Body(...)):
    sesion.guardar_item_lote(lote_id, indice, payload)
    return {"ok": True}


@app.post("/api/sesion-limpiar")
def sesion_limpiar():
    """Lo dispara "Inicio": reinicia el recorrido del asistente (ruta, archivo,
    resultados de analisis). Lo ya sembrado en almacen.db -- APM, TDD Nivel 2,
    lo que ve el panel "Comparar APM y TDD" -- no se toca, igual que antes."""
    sesion.limpiar()
    return {"ok": True}


# El navegador pide /favicon.ico solo. Sin esta ruta deja un 404 rojo en la
# consola cada vez que se abre la app, y en una demo eso se lee como una falla
# que no existe. Se responde un SVG con las letras del Tec.
FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="10" fill="#003da5"/>'
    '<text x="32" y="43" font-family="Arial,Helvetica,sans-serif" font-size="26" '
    'font-weight="bold" fill="#fff" text-anchor="middle">TEC</text></svg>'
).encode("utf-8")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(FAVICON, media_type="image/svg+xml")


# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------
# La API key se administra desde la pantalla, pero NUNCA viaja de vuelta al
# navegador ni aparece en los logs. Solo sale enmascarada.

@app.get("/api/config")
def config_leer():
    return configuracion.estado()


@app.post("/api/config")
def config_guardar(payload: dict = Body(...)):
    try:
        resultado = configuracion.guardar(payload)
    except OSError as exc:
        raise HTTPException(400, f"No se pudo escribir el .env: {exc}")
    # Se registran los NOMBRES de lo que cambio, nunca los valores secretos.
    log.info("config actualizada | %s", "; ".join(resultado["cambios"]) or "sin cambios")
    return {"ok": True, **resultado, "estado": configuracion.estado(),
            "proveedor_activo": _proveedor()[0]}


@app.post("/api/config/borrar-llave")
def config_borrar_llave():
    configuracion.borrar_llave()
    log.info("API key eliminada del .env")
    return {"ok": True, "estado": configuracion.estado()}


@app.post("/api/config/probar")
def config_probar(payload: dict = Body(...)):
    """Comprueba que el proveedor elegido responde, ANTES de gastar minutos
    en un lote. Devuelve un diagnostico accionable, no solo ok/error."""
    proveedor = str(payload.get("proveedor") or "").strip().lower()
    if proveedor in MODOS_LOCALES or (not proveedor and not os.getenv("ANTHROPIC_API_KEY")):
        ok, motivo = ollama_service.disponible()
        return {"ok": ok, "proveedor": "ollama",
                "mensaje": "Ollama responde y el modelo esta descargado." if ok else motivo}

    # --- prueba real contra la API de Anthropic ---
    if not os.getenv("ANTHROPIC_API_KEY"):
        return {"ok": False, "proveedor": "claude",
                "mensaje": "No hay API key guardada. Pegala arriba y guarda antes de probar."}
    try:
        import anthropic
        workspace = (os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip()
        cabeceras = {"anthropic-workspace-id": workspace} if workspace else None
        cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"),
                                      default_headers=cabeceras)
        modelo = (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5").strip()
        cliente.messages.create(model=modelo, max_tokens=8,
                                messages=[{"role": "user", "content": "ok"}])
        return {"ok": True, "proveedor": "claude",
                "mensaje": f"La API respondio correctamente con {modelo}."}
    except Exception as exc:
        texto = str(exc)
        # Traducir los dos errores que de verdad ocurren, en vez de volcar el stack.
        if "workspace" in texto.lower():
            ayuda = ("Tu token esta ligado a una identidad de organizacion y la API "
                     "necesita saber en que workspace actua. Agrega el Workspace ID "
                     "(console.anthropic.com > Settings > Workspaces, empieza con "
                     "'wrkspc_') y vuelve a probar.")
        elif "authentication" in texto.lower() or "401" in texto or "unauthorized" in texto.lower():
            ayuda = ("La API rechazo la llave. Revisa que este completa y vigente en "
                     "console.anthropic.com > Settings > API keys.")
        elif "credit" in texto.lower() or "billing" in texto.lower():
            ayuda = "La cuenta no tiene credito disponible."
        elif "not_found" in texto.lower() or "model" in texto.lower():
            ayuda = f"El modelo no esta disponible para esta cuenta. Prueba con otro."
        else:
            ayuda = texto[:300]
        log.warning("prueba de conexion fallida | %s", type(exc).__name__)
        return {"ok": False, "proveedor": "claude", "mensaje": ayuda}


# ---------------------------------------------------------------------------
# CONCILIACION APM / TDD
# ---------------------------------------------------------------------------
# El orden es fijo y no es un detalle de interfaz: PRIMERO el APM, DESPUES el
# TDD. El APM es el registro autoritativo del portafolio; el TDD es un documento
# de trabajo de un proyecto. La informacion baja del inventario al documento,
# nunca al reves. Si el TDD pudiera escribir en el APM, el caso particular
# terminaria reescribiendo el registro general y nadie sabria cuando paso.
#
# Los libros abiertos se guardan en memoria del proceso: leer un .xlsx de 170 KB
# con dos pasadas cuesta cerca de un segundo, y la pantalla lo consulta en cada
# paso. Es cache de proceso, no persistencia: si el servidor se reinicia se
# vuelve a leer del disco, que es la unica fuente de verdad.

_LIBROS: dict[str, apm.LibroAPM] = {}


def _nombre_libre(carpeta: Path, nombre: str) -> Path:
    """Un destino que no pise nada. Dos documentos distintos pueden llamarse
    igual, y perder uno en silencio es peor que tener dos con sufijo."""
    nombre = os.path.basename(nombre) or "descarga"
    nombre = "".join(c for c in nombre if c.isalnum() or c in " ._-()").strip()
    destino = carpeta / nombre
    n = 2
    while destino.exists():
        destino = carpeta / f"{Path(nombre).stem}-{n}{Path(nombre).suffix}"
        n += 1
    return destino


def _libro(ruta: str) -> apm.LibroAPM:
    ruta = str(ruta).strip().strip('"')
    if not ruta:
        raise HTTPException(400, "Falta la ruta del libro de APM.")
    p = Path(ruta)
    if not p.exists():
        raise HTTPException(404, f"No existe: {p}")
    # La marca de tiempo va en la clave: si alguien edita el .xlsx mientras la
    # sesion esta abierta, la entrada vieja deja de servir sola y se relee. Un
    # cache que devuelve un libro que ya no existe en disco es peor que no tener
    # cache, porque lo que se guarda al final no corresponde a lo que se revisó.
    clave = f"{p}|{p.stat().st_mtime_ns}"
    libro = _LIBROS.get(clave)
    if libro is None:
        try:
            libro = apm.LibroAPM(p)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(400, f"No se pudo leer el libro: {exc}")
        if len(_LIBROS) >= 6:
            _LIBROS.pop(next(iter(_LIBROS)))
        _LIBROS[clave] = libro
    return libro


@app.post("/api/apm/abrir")
def apm_abrir(payload: dict = Body(...)):
    """Abre el libro y devuelve su estructura REAL: columnas, cuales se pueden
    escribir y por que no las otras, catalogos, y las aplicaciones."""
    libro = _libro(payload.get("ruta", ""))
    return {
        "ok": True,
        "resumen": libro.resumen(),
        "columnas": [{"clave": c.clave, "grupo": c.grupo, "etiqueta": c.etiqueta,
                      "escribible": c.escribible, "motivo": c.motivo,
                      "nota": c.nota, "lookup": c.lookup} for c in libro.columnas],
        "aplicaciones": [{"numero": a.numero, "id_habilitador": a.id_habilitador,
                          "nombre": a.nombre, "fila": a.fila,
                          "vacios": len(a.vacios(libro.columnas))}
                         for a in libro.aplicaciones],
    }


# ---------------------------------------------------------------------------
# ALMACEN
# ---------------------------------------------------------------------------
# La base arranca con lo que YA dicen el APM y los TDD. Esa es la referencia
# contra la que se compara todo lo que llegue despues; sin ella cada escaneo
# empieza de cero y la aplicacion no puede distinguir "esto es nuevo" de "esto
# ya lo sabiamos" ni de "esto contradice lo que hay".

@app.post("/api/almacen/sembrar")
def almacen_sembrar(payload: dict = Body(...)):
    """Vuelca el estado actual del APM y de la carpeta de TDD a la base.

    Es idempotente: se vuelve a correr cada vez que cambie el libro, y reemplaza
    la linea base anterior. No borra ni los documentos leidos ni las decisiones,
    que son historia y no linea base.
    """
    libro = _libro(payload.get("ruta_apm", ""))
    resultado = {"apm": _base().sembrar_apm(libro), "tdd": [], "tdd_sin_amarrar": []}
    resultado["referencia_apm"] = _actualizar_referencia_apm(libro, str(libro.ruta))

    carpeta = str(payload.get("carpeta_tdd", "")).strip().strip('"')
    if carpeta:
        raiz = Path(carpeta)
        if not raiz.is_dir():
            raise HTTPException(400, f"No es una carpeta: {raiz}")
        for archivo in sorted(raiz.glob("*.docx")):
            if archivo.name.startswith(("~$", ".")):
                continue
            # Solo nombres con pinta de TDD real (mismo patron que ya usa
            # `docs_referencia`: "TDD_V3_Nombre.docx" o "TDD_Tec__Nombre.docx").
            # Sin este filtro, una plantilla en blanco (p.ej. Plantilla_TDD_V3.docx)
            # pasa el sniffing de contenido de `es_documento_tdd` -- comparte el
            # mismo lenguaje estructural que un TDD real -- y termina como ruido
            # en "tdd_sin_amarrar" sin aportar ningun dato. No se toca el
            # contenido de ningun documento por esto, solo se decide cuales
            # carpeta escanea.
            if not (_RE_DOC_CON_VERSION.match(archivo.stem) or _RE_DOC_SIN_VERSION.match(archivo.stem)):
                continue
            try:
                if not tdd.es_documento_tdd(archivo):
                    continue
                doc = tdd.leer(archivo)
                aplicacion = libro.aplicacion(
                    numero=doc.numero_apm, id_habilitador=doc.id_habilitador,
                    nombre=doc.nombre_archivo_pista)
                numero = aplicacion.numero if aplicacion else ""
                _base().sembrar_tdd(archivo, doc, tdd.celdas_etiquetadas(archivo), numero)
                if numero:
                    _actualizar_referencia_tdd(numero, archivo, str(archivo))
                fila = {"nombre": archivo.name, "numero": numero,
                        "aplicativo": aplicacion.nombre if aplicacion else "",
                        "tablas": doc.total_tablas, "completitud": doc.completitud,
                        "faltantes": len(doc.faltantes())}
                resultado["tdd"].append(fila)
                if not numero:
                    resultado["tdd_sin_amarrar"].append(archivo.name)
            except Exception as exc:
                log.warning("no se pudo sembrar %s: %s", archivo.name, exc)

    log.info("almacen sembrado | %s aplicativos | %s TDD",
             resultado["apm"]["aplicativos"], len(resultado["tdd"]))
    return {"ok": True, **resultado, "resumen": _base().resumen()}


@app.get("/api/almacen/resumen")
def almacen_resumen():
    return {"ok": True, "resumen": _base().resumen(), "cobertura": _base().cobertura()}


@app.post("/api/almacen/reporte")
def almacen_reporte():
    """Reporte de avance: por aplicativo, cuanto tiene lleno el APM y cuantos
    TDD ya se sembraron. Se escribe a disco (para poder bajarlo) ademas de
    devolverse en la respuesta."""
    cobertura = _base().cobertura()
    total_llenos = sum(c["llenos"] for c in cobertura)
    total_campos = sum(c["total"] for c in cobertura)
    pct_total = round(total_llenos * 100 / total_campos) if total_campos else 0

    lineas = [
        "# Reporte de avance · APM y TDD", "",
        f"Generado: {almacen.ahora()}", "",
        f"**Total: {total_llenos}/{total_campos} campos APM llenos ({pct_total}%) · "
        f"{sum(c['tdds'] for c in cobertura)} TDD en la base · "
        f"{sum(c['docs'] for c in cobertura)} documentos fuente leídos.**", "",
        "| # | Aplicativo | APM lleno | % | TDD | Documentos | Decisiones |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in cobertura:
        pct = round(c["llenos"] * 100 / c["total"]) if c["total"] else 0
        lineas.append(
            f"| {c['numero']} | {c['nombre']} | {c['llenos']}/{c['total']} | {pct}% "
            f"| {c['tdds']} | {c['docs']} | {c['decisiones']} |")
    texto = "\n".join(lineas)

    carpeta = CARPETA_DATOS / "salidas"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "reporte_avance.md"
    try:
        destino.write_text(texto, encoding="utf-8")
    except OSError as exc:
        log.warning("no se pudo escribir el reporte a disco: %s", exc)
        destino = None

    return {"ok": True, "markdown": texto, "cobertura": cobertura,
            "archivo": str(destino) if destino else ""}


@app.get("/api/descargar")
def descargar_archivo(ruta: str):
    """Baja un archivo que la aplicación escribió: una versión nueva de APM o
    TDD, una exportación de la base, el reporte de avance. Restringido a la
    carpeta `datos/` de la aplicación -- esto no es un explorador de archivos
    general, es la puerta de salida de lo que la app ya produjo."""
    try:
        p = Path(ruta).resolve()
        p.relative_to(CARPETA_DATOS.resolve())
    except (ValueError, OSError):
        raise HTTPException(400, "Esa ruta no se puede descargar desde aquí.")
    if not p.is_file():
        raise HTTPException(404, "El archivo ya no existe.")
    return FileResponse(str(p), filename=p.name)


@app.post("/api/almacen/exportar")
def almacen_exportar(payload: dict = Body(default={})):
    """Saca la base completa a JSON y a un CSV por tabla, para poder moverla."""
    destino = str((payload or {}).get("carpeta", "")).strip().strip('"')
    carpeta = Path(destino) if destino else (CARPETA_DATOS / "export")
    try:
        resultado = _base().exportar(carpeta)
    except OSError as exc:
        raise HTTPException(400, f"No se pudo exportar: {exc}")
    log.info("almacen exportado a %s", carpeta)
    return {"ok": True, **resultado}


# ---------------------------------------------------------------------------
# SUBIDA DE ARCHIVOS Y CARPETAS
# ---------------------------------------------------------------------------
# Por que existe esto ademas del campo de ruta: el navegador NO entrega la ruta
# real de un archivo, por seguridad la esconde. Asi que "subir" y "escribir la
# ruta" no son dos formas de lo mismo, son dos mecanismos distintos, y los dos
# sirven: subir es comodo y funciona con archivos de cualquier maquina; la ruta
# no copia nada, que con un TDD de 3 MB es notablemente mas rapido.

@app.post("/api/conciliar/subir")
async def conciliar_subir(files: list[UploadFile] = File(...)):
    """Recibe uno o varios archivos (o una carpeta completa) y los deja en
    disco. Devuelve las rutas para que el resto del flujo siga igual."""
    if not files:
        raise HTTPException(400, "No llego ningun archivo.")

    CARPETA_SUBIDOS.mkdir(parents=True, exist_ok=True)
    guardados, rechazados = [], []

    for archivo in files:
        nombre = os.path.basename(archivo.filename or "documento")
        if not nombre:
            continue
        contenido = await archivo.read()
        if not contenido:
            rechazados.append({"nombre": nombre, "motivo": "llegó vacío"})
            continue
        if len(contenido) > MAX_BYTES:
            rechazados.append({"nombre": nombre,
                               "motivo": f"pesa {len(contenido)//1024//1024} MB "
                                         f"y el límite es {MAX_MB} MB"})
            continue
        if not parsers.soportado(nombre):
            rechazados.append({"nombre": nombre,
                               "motivo": f"formato no soportado "
                                         f"({Path(nombre).suffix or 'sin extensión'})"})
            continue

        destino = _nombre_libre(CARPETA_SUBIDOS, nombre)
        destino.write_bytes(contenido)
        guardados.append({"nombre": nombre, "ruta": str(destino),
                          "bytes": len(contenido),
                          "huella": almacen.huella_bytes(contenido)})

    log.info("subida | %s guardados | %s rechazados", len(guardados), len(rechazados))
    return {"ok": True, "archivos": guardados, "rechazados": rechazados}

@app.post("/api/conciliar/fuentes")
def conciliar_fuentes(payload: dict = Body(...)):
    """Clasifica los archivos que se le señalen y dice de que aplicativo habla
    cada uno. Los que SON el APM o un TDD se descartan aqui: son destino."""
    libro = _libro(payload.get("ruta_apm", ""))
    rutas = payload.get("rutas") or []
    carpeta = str(payload.get("carpeta", "")).strip().strip('"')

    if carpeta:
        raiz = Path(carpeta)
        if not raiz.is_dir():
            raise HTTPException(400, f"No es una carpeta: {raiz}")
        it = raiz.rglob("*") if payload.get("recursivo", True) else raiz.glob("*")
        rutas = [str(r) for r in sorted(it)
                 if r.is_file() and parsers.soportado(r.name)
                 and not r.name.startswith(("~$", "."))][:200]
    if not rutas:
        raise HTTPException(400, "No se indicó ningún documento fuente.")

    aceptados, descartados = [], []
    reusados = 0

    for ruta in rutas:
        crudo = str(ruta).strip().strip('"')
        tipo_origen = "ruta"

        # Una URL se baja a un temporal y de ahi sigue el mismo camino que un
        # archivo local. `_descargar` es quien detecta la pantalla de login de
        # SharePoint y el tope de tamaño.
        if crudo.lower().startswith(("http://", "https://")):
            try:
                temporal, nombre = _descargar(crudo)
            except HTTPException as exc:
                descartados.append({"nombre": crudo[:70], "tipo": "url",
                                    "motivo": exc.detail})
                continue
            if not parsers.soportado(nombre):
                os.remove(temporal)
                descartados.append({"nombre": nombre, "tipo": "url",
                                    "motivo": "esa URL no devuelve un formato legible"})
                continue
            # Se mueve a _subidos con su nombre real: una ruta /tmp/tmpk3n9
            # en pantalla no le dice nada a nadie, y el paso siguiente necesita
            # que el archivo siga existiendo.
            CARPETA_SUBIDOS.mkdir(parents=True, exist_ok=True)
            destino_url = _nombre_libre(CARPETA_SUBIDOS, nombre)
            shutil.move(temporal, destino_url)
            p, tipo_origen = destino_url, "url"
        else:
            p = Path(crudo)

        if not p.exists():
            descartados.append({"nombre": p.name, "tipo": "inexistente",
                                "motivo": "no existe esa ruta"})
            continue

        papel = identificacion.clasificar_archivo(p)
        if not papel.es_fuente:
            descartados.append({"nombre": p.name, "tipo": papel.tipo,
                                "motivo": papel.motivo})
            continue

        # La huella del CONTENIDO se calcula antes de parsear. Si ya leimos este
        # documento -- aunque venga con otro nombre o de otra carpeta -- no hay
        # nada que volver a hacer: lo que aporto ya esta en el almacen.
        huella = almacen.huella_de(p)
        previo = _base().documento_conocido(huella)
        if previo and previo.get("numero"):
            hallazgos_previos = previo.get("hallazgos") or []
            aceptados.append({
                "ruta": str(p), "nombre": p.name, "huella": huella,
                "identificado": True, "numero": previo["numero"],
                "nombre_aplicativo": next(
                    (a.nombre for a in libro.aplicaciones
                     if a.numero == previo["numero"]), ""),
                "id_habilitador": "", "senal": previo.get("senal", ""),
                "evidencia": previo.get("evidencia", ""),
                "candidatos": [], "de_memoria": True,
                "leido_en": previo.get("leido_en", ""),
                "campos_recordados": len(hallazgos_previos),
                # Ya se leyo antes y en su momento no aporto ningun dato: se
                # reconoce por la huella y no se vuelve a abrir, pero se marca
                # igual que la primera vez para que no parezca un aporte nuevo.
                "aporta_informacion": bool(hallazgos_previos),
            })
            reusados += 1
            continue
        if previo is not None:
            # Ya se leyo este contenido y en su momento NO se pudo amarrar a
            # ningun aplicativo. No hay nada nuevo que sacarle a los mismos
            # bytes, asi que ni se vuelve a abrir: se reporta con lo que ya se
            # sabia de el, para no repetir el trabajo cada vez que reaparece.
            aceptados.append({
                "ruta": str(p), "nombre": p.name, "huella": huella,
                "identificado": False, "numero": "", "nombre_aplicativo": "",
                "id_habilitador": "", "senal": previo.get("senal", ""),
                "evidencia": previo.get("evidencia", "ya se revisó antes y "
                             "no se pudo identificar a qué aplicativo pertenece"),
                "candidatos": [], "de_memoria": True,
                "leido_en": previo.get("leido_en", ""),
                "campos_recordados": 0, "aporta_informacion": False,
            })
            reusados += 1
            continue

        try:
            doc = parsers.parse(str(p), p.name)
        except Exception as exc:
            descartados.append({"nombre": p.name, "tipo": "ilegible",
                                "motivo": f"no se pudo leer: {exc}"})
            continue

        texto = deteccion.bloque_para_modelo(doc)[:20_000]
        amarre = identificacion.identificar(texto, p.name, libro)
        hallazgos = extraccion.extraer(doc, libro, p.name) if amarre.identificado else {}

        # Se guarda SIEMPRE un registro de lo que se leyo -- identificado o no,
        # con datos o sin ellos -- para nunca volver a abrir el mismo archivo.
        # Cuando no aporto nada, lo que se archiva es precisamente eso: que ya
        # se reviso y que fue basura. Es la memoria chica de la que se cotejan
        # las siguientes veces, no una copia del documento.
        _base().registrar_documento(
            huella, p.name, str(p), tipo_origen, p.stat().st_size,
            amarre.numero if amarre.identificado else "",
            amarre.senal, amarre.evidencia,
            {k: (v[0].valor, v[0].evidencia) for k, v in hallazgos.items()})

        aceptados.append({
            "ruta": str(p), "nombre": p.name, "huella": huella,
            "identificado": amarre.identificado,
            "numero": amarre.numero, "nombre_aplicativo": amarre.nombre,
            "id_habilitador": amarre.id_habilitador,
            "senal": amarre.senal, "evidencia": amarre.evidencia,
            "candidatos": amarre.candidatos, "de_memoria": False,
            # La compuerta: identificado no es lo mismo que util. Un documento
            # puede amarrarse a un aplicativo real y aun asi no decir nada que
            # corresponda a un campo del APM o del TDD -- eso tambien es un
            # documento invalido para este proceso, y se marca como tal en vez
            # de dejarlo mezclado con los que si aportaron algo.
            "aporta_informacion": bool(hallazgos),
            "campos_encontrados": len(hallazgos),
        })

    log.info("fuentes | %s aceptadas (%s de memoria) | %s descartadas",
             len(aceptados), reusados, len(descartados))
    return {"ok": True, "fuentes": aceptados, "descartados": descartados,
            "reusados": reusados,
            "sin_identificar": [f for f in aceptados if not f["identificado"]]}


@app.post("/api/conciliar/aplicativo")
def conciliar_aplicativo(payload: dict = Body(...)):
    """PASO APM. Lee los documentos de un aplicativo y devuelve las propuestas,
    con los conflictos marcados. No escribe nada."""
    libro = _libro(payload.get("ruta_apm", ""))
    numero = str(payload.get("numero", "")).strip()
    aplicacion = libro.aplicacion(numero=numero)
    if not aplicacion:
        raise HTTPException(404, f"No hay un aplicativo #{numero} en el inventario.")

    por_documento = []
    leidos, de_memoria, fallidos = [], [], []

    for ruta in (payload.get("rutas") or []):
        p = Path(str(ruta).strip().strip('"'))
        try:
            # Primero la memoria. Si el contenido ya se leyo, sus hallazgos
            # estan guardados y abrir el archivo otra vez no aporta nada: un
            # .docx de 3 MB tarda segundos en parsearse y el resultado seria
            # identico, byte por byte.
            huella = almacen.huella_de(p)
            previo = _base().documento_conocido(huella)
            if previo and previo.get("hallazgos"):
                por_documento.append({
                    h["clave"]: [conciliacion.Candidato(
                        h["valor"], previo["nombre"], h["evidencia"])]
                    for h in previo["hallazgos"]})
                de_memoria.append({"nombre": previo["nombre"],
                                   "leido_en": previo["leido_en"],
                                   "campos": len(previo["hallazgos"])})
                continue

            doc = parsers.parse(str(p), p.name)
            hallazgos = extraccion.extraer(doc, libro, p.name)
            por_documento.append(hallazgos)
            leidos.append(p.name)
            _base().registrar_documento(
                huella, p.name, str(p), "ruta", p.stat().st_size,
                aplicacion.numero, "", "",
                {k: (v[0].valor, v[0].evidencia) for k, v in hallazgos.items()})
        except Exception as exc:
            fallidos.append({"nombre": p.name, "motivo": str(exc)})

    propuestas = conciliacion.conciliar_apm(
        libro, aplicacion, extraccion.fusionar(por_documento))

    # Decisiones que esta misma persona ya tomo antes sobre este aplicativo.
    # Se reaplican SOLO si el conflicto es identico: si un documento nuevo trajo
    # una opcion que antes no existia, la decision vieja no responde la pregunta
    # nueva, y volver a preguntarla es lo correcto.
    previas = _base().decisiones_de(aplicacion.numero)
    salida = []
    repetidas = 0
    for prop in propuestas:
        d = prop.a_dict()
        anterior = previas.get(prop.clave)
        if anterior and prop.exige_decision:
            try:
                antes = {c.get("valor") for c in json.loads(anterior["candidatos"] or "[]")}
            except (ValueError, TypeError):
                antes = set()
            ahora_cands = {c.valor for c in prop.candidatos}
            if antes == ahora_cands:
                d["decision_previa"] = anterior["valor"]
                d["decidido_en"] = anterior["decidido_en"]
                repetidas += 1
            else:
                d["cambio_el_conflicto"] = True
        salida.append(d)

    resumen = conciliacion.resumen(propuestas)
    resumen["con_decision_previa"] = repetidas

    return {
        "ok": True,
        "aplicativo": {"numero": aplicacion.numero, "nombre": aplicacion.nombre,
                       "id_habilitador": aplicacion.id_habilitador,
                       "fila": aplicacion.fila},
        "documentos_leidos": leidos, "documentos_de_memoria": de_memoria,
        "documentos_fallidos": fallidos,
        "propuestas": salida,
        "resumen": resumen,
    }


@app.post("/api/conciliar/guardar-apm")
def conciliar_guardar_apm(payload: dict = Body(...)):
    """Escribe una version NUEVA del libro. Se niega si queda una sola propuesta
    sin decidir: esa es la compuerta, y no tiene forma de saltarse desde aqui."""
    libro = _libro(payload.get("ruta_apm", ""))
    numero = str(payload.get("numero", "")).strip()
    aplicacion = libro.aplicacion(numero=numero)
    if not aplicacion:
        raise HTTPException(404, f"No hay un aplicativo #{numero}.")

    propuestas = [conciliacion.Propuesta(
        clave=d["clave"], grupo=d.get("grupo", ""), etiqueta=d.get("etiqueta", ""),
        valor_actual=d.get("valor_actual", ""), estado=d["estado"],
        candidatos=[conciliacion.Candidato(c["valor"], c.get("documento", ""),
                                           c.get("evidencia", ""))
                    for c in d.get("candidatos", [])],
        motivo=d.get("motivo", ""), lookup=d.get("lookup", []),
    ) for d in (payload.get("propuestas") or [])]

    conciliacion.aplicar_decisiones(propuestas, payload.get("decisiones") or {})

    faltan = conciliacion.pendientes(propuestas)
    if faltan:
        raise HTTPException(400,
            f"Faltan {len(faltan)} campos por revisar: "
            + ", ".join(p.etiqueta for p in faltan[:6])
            + ". Nada se guarda hasta que estén decididos.")

    cambios, descartados = conciliacion.cambios_para_escribir(
        propuestas, aplicacion.fila, libro)
    if not cambios:
        return {"ok": True, "sin_cambios": True, "descartados": descartados,
                "mensaje": "No quedó ningún cambio que escribir."}

    # Las versiones nuevas se juntan en su propia carpeta -- separada de TDD y
    # del original -- para que "¿donde quedo lo que se guardo?" tenga una
    # respuesta sola en vez de estar mezclado con la carpeta de origen.
    destino = apm.siguiente_version(libro.ruta, carpeta_destino=CARPETA_DATOS / "salidas" / "APM")
    resultado = libro.escribir_version(cambios, destino)

    # Lo que la persona decidio se guarda para no volver a preguntarselo, y la
    # escritura queda con su rastro: que archivo, cuando, cuantas celdas.
    guardadas = _base().guardar_decisiones(
        aplicacion.numero, payload.get("propuestas") or [],
        payload.get("decisiones") or {})
    _base().registrar_escritura("apm", aplicacion.numero, str(libro.ruta),
                             str(destino), resultado["aplicados"])
    log.info("APM guardado | %s | %s celdas | %s decisiones recordadas",
             Path(destino).name, len(resultado["aplicados"]), guardadas)
    return {"ok": True, "archivo": resultado["destino"],
            "nombre": Path(destino).name,
            "aplicados": resultado["aplicados"],
            "rechazados": resultado["rechazados"] + descartados,
            "decisiones_recordadas": guardadas,
            "original_intacto": str(libro.ruta)}


@app.post("/api/conciliar/tdd")
def conciliar_tdd(payload: dict = Body(...)):
    """PASO TDD, siempre despues del APM. Lee el documento, dice a que aplicativo
    pertenece y que le falta, y propone lo que el APM puede llenarle."""
    libro = _libro(payload.get("ruta_apm", ""))
    ruta = Path(str(payload.get("ruta_tdd", "")).strip().strip('"'))
    if not ruta.exists():
        raise HTTPException(404, f"No existe: {ruta}")
    if not tdd.es_documento_tdd(ruta):
        raise HTTPException(400, f"«{ruta.name}» no parece un TDD.")

    doc = tdd.leer(ruta)
    aplicacion = libro.aplicacion(numero=doc.numero_apm,
                                  id_habilitador=doc.id_habilitador,
                                  nombre=doc.nombre_archivo_pista)
    if not aplicacion:
        return {"ok": True, "identificado": False,
                "documento": {"nombre": ruta.name, "tablas": doc.total_tablas,
                              "completitud": doc.completitud,
                              "numero_apm": doc.numero_apm,
                              "id_habilitador": doc.id_habilitador,
                              "pista": doc.nombre_archivo_pista},
                "faltantes": doc.faltantes(),
                "mensaje": ("Este TDD no se pudo amarrar a ningún aplicativo del "
                            "inventario. Hay que decirle cuál es antes de llenarlo.")}

    propuestas = conciliacion.mapear_apm_a_tdd(
        libro, aplicacion, doc, tdd.celdas_etiquetadas(ruta))

    return {
        "ok": True, "identificado": True,
        "aplicativo": {"numero": aplicacion.numero, "nombre": aplicacion.nombre,
                       "id_habilitador": aplicacion.id_habilitador},
        "documento": {"nombre": ruta.name, "ruta": str(ruta),
                      "tablas": doc.total_tablas, "completitud": doc.completitud,
                      "celdas_llenas": doc.celdas_llenas,
                      "celdas_totales": doc.celdas_totales},
        "faltantes": doc.faltantes(),
        "propuestas": propuestas,
        "exigen_decision": sum(1 for p in propuestas if p["exige_decision"]),
    }


@app.post("/api/conciliar/guardar-tdd")
def conciliar_guardar_tdd(payload: dict = Body(...)):
    """Escribe una version NUEVA del TDD. Igual que el APM: sin decidir, no pasa,
    y una celda que ya tiene contenido no se pisa jamas."""
    ruta = Path(str(payload.get("ruta_tdd", "")).strip().strip('"'))
    if not ruta.exists():
        raise HTTPException(404, f"No existe: {ruta}")

    propuestas = payload.get("propuestas") or []
    decisiones = payload.get("decisiones") or {}

    sin_decidir = [p for p in propuestas if p.get("exige_decision")
                   and str(p.get("tabla")) + ":" + str(p.get("fila")) not in decisiones]
    if sin_decidir:
        raise HTTPException(400,
            f"Faltan {len(sin_decidir)} celdas por revisar en el TDD. "
            "Nada se guarda hasta que estén decididas.")

    cambios = []
    for p in propuestas:
        llave = f"{p.get('tabla')}:{p.get('fila')}"
        decidido = p.get("exige_decision")
        if decidido:
            valor = decisiones.get(llave, "")
        else:
            valor = p.get("valor", "") if p.get("estado") == conciliacion.PROPUESTO else ""
        if not valor:
            continue
        # `sobrescribir` solo se enciende cuando una PERSONA resolvio ese
        # conflicto. El llenado automatico nunca pisa lo que el TDD ya trae.
        cambios.append({"tabla": p["tabla"], "fila": p["fila"],
                        "columna": p["columna"], "valor": valor,
                        "sobrescribir": bool(decidido)})

    if not cambios:
        return {"ok": True, "sin_cambios": True,
                "mensaje": "No quedó ninguna celda que llenar en el TDD."}

    destino = tdd.siguiente_version(ruta, carpeta_destino=CARPETA_DATOS / "salidas" / "TDD")
    resultado = tdd.escribir_version(ruta, cambios, destino)
    _base().registrar_escritura("tdd", str(payload.get("numero", "")), str(ruta),
                             str(destino), resultado["aplicados"])
    log.info("TDD guardado | %s | %s celdas | %s rechazadas",
             destino.name, len(resultado["aplicados"]), len(resultado["rechazados"]))
    return {"ok": True, "archivo": resultado["destino"], "nombre": destino.name,
            "aplicados": resultado["aplicados"], "rechazados": resultado["rechazados"],
            # Si no se escribio nada, se dice. Un "guardado" sobre cero celdas
            # hace creer que el trabajo quedo hecho cuando no cambio nada.
            "escribio_algo": bool(resultado["aplicados"]),
            "original_intacto": str(ruta)}

# ---------------------------------------------------------------------------
# TDD NIVEL 2 -- reemplaza al TDD_V3 de arriba (/api/conciliar/tdd y
# /api/conciliar/guardar-tdd ya no se usan desde el front, se dejan sin
# borrar por si hace falta consultar el historial).
#
# La diferencia de fondo con el flujo de APM: aqui NO se llena nada desde el
# APM ni desde una version anterior -- se comparan DOS documentos que una
# persona ya lleno bajo las reglas del TDD Nivel 2 (el que se sube, contra el
# que ya esta sembrado como referencia), campo por campo, y toda diferencia
# queda como conflicto abierto. Igual que "Comparar APM": la aplicacion
# nunca resuelve un desacuerdo sola.
# ---------------------------------------------------------------------------

@app.post("/api/tdd2/sembrar")
def tdd2_sembrar(payload: dict = Body(...)):
    """Siembra (o vuelve a sembrar) los TDD Nivel 2 reales de
    CARPETA_REFERENCIA_TDD2 como la linea base inicial. Es idempotente."""
    libro = _libro(payload.get("ruta_apm", ""))
    resultado = _sembrar_tdd2_todos(libro)
    log.info("TDD2 sembrado | %s identificados | %s sin identificar | %s colisiones",
             len(resultado["identificados"]), len(resultado["sin_identificar"]),
             len(resultado["colisiones"]))
    return {"ok": True, **resultado}


@app.post("/api/tdd2/sembrar-subidos")
def tdd2_sembrar_subidos(payload: dict = Body(...)):
    """Siembra la referencia con TDD Nivel 2 subidos desde el navegador.

    Sirve cuando el portal corre en un servidor (Render) donde no estan los
    TDD Nivel 2 reales en CARPETA_REFERENCIA_TDD2: la persona los sube, se
    copian a esa carpeta y se siembran igual que con «Sembrar». Solo acepta
    archivos que ya pasaron por /api/conciliar/subir (dentro de
    CARPETA_SUBIDOS); cualquier otra ruta se rechaza."""
    libro = _libro(payload.get("ruta_apm", ""))
    rutas = payload.get("rutas") or []
    if not isinstance(rutas, list) or not rutas:
        raise HTTPException(400, "No llego ningun TDD Nivel 2 para sembrar.")

    base_subidos = CARPETA_SUBIDOS.resolve()
    CARPETA_REFERENCIA_TDD2.mkdir(parents=True, exist_ok=True)
    copiados: list[str] = []
    rechazados: list[dict] = []
    for r in rutas:
        # Cada elemento puede ser la ruta sola o {"ruta", "nombre"}; el nombre
        # original evita que se siembre "TDD_X-2.docx" (el sufijo que pone la
        # subida si el archivo ya existia) como si fuera otro documento.
        nombre_original = ""
        if isinstance(r, dict):
            nombre_original = os.path.basename(str(r.get("nombre") or ""))
            r = r.get("ruta") or ""
        origen = Path(str(r).strip().strip('"')).resolve()
        try:
            origen.relative_to(base_subidos)
        except ValueError:
            rechazados.append({"nombre": origen.name, "motivo": "no es un archivo subido"})
            continue
        if not origen.is_file() or origen.suffix.lower() != ".docx":
            rechazados.append({"nombre": origen.name, "motivo": "no es un .docx"})
            continue
        try:
            es_tdd2 = tdd_nivel2.es_documento_tdd_nivel2(origen)
        except Exception:
            es_tdd2 = False
        if not es_tdd2:
            rechazados.append({"nombre": origen.name, "motivo": "no parece un TDD Nivel 2"})
            continue
        destino_nombre = (nombre_original
                          if nombre_original.lower().endswith(".docx") else origen.name)
        shutil.copy2(origen, CARPETA_REFERENCIA_TDD2 / destino_nombre)
        copiados.append(destino_nombre)

    if not copiados:
        return {"ok": True, "copiados": [], "rechazados": rechazados,
                "identificados": [], "sin_identificar": [], "colisiones": {}}

    resultado = _sembrar_tdd2_todos(libro)
    log.info("TDD2 sembrado desde subidos | %s copiados | %s rechazados | %s identificados",
             len(copiados), len(rechazados), len(resultado["identificados"]))
    return {"ok": True, "copiados": copiados, "rechazados": rechazados, **resultado}


@app.get("/api/tdd2/referencia")
def tdd2_referencia():
    """Los aplicativos que ya tienen un TDD Nivel 2 sembrado como referencia,
    con que tan completo esta cada uno -- el equivalente de
    `/api/docs-referencia` pero para la plantilla nueva."""
    tarjetas: list[dict] = []
    if BASE is not None:
        try:
            cobertura = BASE.cobertura_tdd2()
        except Exception:
            cobertura = []
        for f in cobertura:
            ref = None
            try:
                ref = BASE.referencia_de("tdd2", f["numero"])
            except Exception:
                pass
            tarjetas.append({
                "numero": f["numero"], "id_habilitador": f.get("id_habilitador") or "",
                "habilitador": f["nombre"],
                "tdd2_nombre": (Path(ref["ruta_estable"]).stem + ".docx")
                    if ref and ref.get("ruta_estable") else None,
                "campos_llenos": f.get("campos_llenos"),
                "campos_totales": f.get("campos_totales"),
                "completitud": f.get("completitud"),
                "actualizado_en": ref.get("actualizado_en") if ref else None,
            })
    tarjetas.sort(key=lambda t: (t["habilitador"] or "").lower())
    return {"ok": True, "total": sum(1 for t in tarjetas if t["tdd2_nombre"]),
            "habilitadores": tarjetas}


@app.post("/api/tdd2/comparar")
def tdd2_comparar(payload: dict = Body(...)):
    """Identifica el TDD Nivel 2 subido y lo compara campo por campo contra
    la referencia ya sembrada de ese aplicativo (si la hay). Nunca escribe
    nada -- eso lo hace /api/tdd2/guardar, y solo despues de que una persona
    decida cada conflicto."""
    libro = _libro(payload.get("ruta_apm", ""))
    ruta = Path(str(payload.get("ruta_tdd2", "")).strip().strip('"'))
    if not ruta.exists():
        raise HTTPException(404, f"No existe: {ruta}")
    if not tdd_nivel2.es_documento_tdd_nivel2(ruta):
        raise HTTPException(400, f"«{ruta.name}» no parece un TDD Nivel 2.")

    nuevo = tdd_nivel2.leer(ruta)
    if tdd_nivel2.es_plantilla_en_blanco(nuevo):
        raise HTTPException(400, "Ese archivo es la plantilla en blanco, no un TDD lleno.")

    amarre = tdd_nivel2.identificar(nuevo, libro)
    if not amarre.identificado:
        return {"ok": True, "identificado": False,
                "documento": {"nombre": ruta.name, "ruta": str(ruta),
                              "campos_con_dato": len(nuevo.campos_con_dato),
                              "campos_totales": len(nuevo.campos)},
                "candidatos": amarre.candidatos,
                "mensaje": amarre.evidencia or
                    "Este TDD Nivel 2 no se pudo amarrar a ningún aplicativo del inventario."}

    numero = amarre.numero
    ref = _base().referencia_de("tdd2", numero)
    referencia_doc = None
    if ref and Path(ref.get("ruta_estable", "")).exists():
        try:
            referencia_doc = tdd_nivel2.leer(Path(ref["ruta_estable"]))
        except Exception:
            referencia_doc = None

    propuestas = tdd_nivel2.conciliar_tdd2(referencia_doc, nuevo)
    salida = [p.a_dict() for p in propuestas]

    return {
        "ok": True, "identificado": True,
        "aplicativo": {"numero": numero, "nombre": amarre.nombre,
                       "id_habilitador": amarre.id_habilitador,
                       "senal": amarre.senal, "evidencia": amarre.evidencia},
        "documento": {"nombre": ruta.name, "ruta": str(ruta),
                      "campos_con_dato": len(nuevo.campos_con_dato),
                      "campos_totales": len(nuevo.campos)},
        "hay_referencia_previa": referencia_doc is not None,
        "referencia": ({"nombre": Path(ref["ruta_estable"]).name,
                        "actualizado_en": ref.get("actualizado_en")}
                       if referencia_doc is not None else None),
        "propuestas": salida,
        "resumen": conciliacion.resumen(propuestas),
    }


@app.post("/api/tdd2/guardar")
def tdd2_guardar(payload: dict = Body(...)):
    """Escribe lo que la persona decidio como la version NUEVA de la
    referencia de este aplicativo. Igual que el APM: sin decidir, no pasa, y
    una celda que ya tiene contenido no se pisa jamas sin una decision
    explicita sobre ESE conflicto."""
    ruta_nuevo = Path(str(payload.get("ruta_tdd2", "")).strip().strip('"'))
    if not ruta_nuevo.exists():
        raise HTTPException(404, f"No existe: {ruta_nuevo}")
    numero = str(payload.get("numero", "")).strip()
    if not numero:
        raise HTTPException(400, "Falta el número de aplicativo.")

    propuestas = [conciliacion.Propuesta(
        clave=d["clave"], grupo=d.get("grupo", ""), etiqueta=d.get("etiqueta", ""),
        valor_actual=d.get("valor_actual", ""), estado=d["estado"],
        candidatos=[conciliacion.Candidato(c["valor"], c.get("documento", ""),
                                           c.get("evidencia", ""))
                    for c in d.get("candidatos", [])],
        motivo=d.get("motivo", ""),
    ) for d in (payload.get("propuestas") or [])]

    conciliacion.aplicar_decisiones(propuestas, payload.get("decisiones") or {})
    faltan = conciliacion.pendientes(propuestas)
    if faltan:
        raise HTTPException(400,
            f"Faltan {len(faltan)} campos por revisar: "
            + ", ".join(p.etiqueta for p in faltan[:6])
            + ". Nada se guarda hasta que estén decididos.")

    ref = _base().referencia_de("tdd2", numero)
    tiene_referencia = bool(ref and Path(ref.get("ruta_estable", "")).exists())
    CARPETA_REFERENCIA_TDD2_ESTABLE.mkdir(parents=True, exist_ok=True)
    destino_estable = CARPETA_REFERENCIA_TDD2_ESTABLE / f"{numero}.docx"

    if not tiene_referencia:
        # Primera siembra de este aplicativo: no hay contra que comparar
        # celda por celda, asi que el documento subido se adopta completo.
        shutil.copy2(ruta_nuevo, destino_estable)
        doc_final = tdd_nivel2.leer(destino_estable)
        _base().sembrar_tdd2(destino_estable, doc_final, numero)
        fechas = _base().actualizar_referencia("tdd2", numero, str(destino_estable),
                                               str(ruta_nuevo)) or {}
        log.info("TDD2 sembrado por primera vez | #%s | %s", numero, ruta_nuevo.name)
        return {"ok": True, "primera_siembra": True,
                "archivo": str(destino_estable), "nombre": destino_estable.name,
                "aplicados": [], "rechazados": [], "escribio_algo": True,
                "original_intacto": str(ruta_nuevo), **fechas}

    nuevo = tdd_nivel2.leer(ruta_nuevo)
    campos_por_llave = {c.llave: c for c in nuevo.campos}

    cambios = []
    for p in propuestas:
        valor = p.valor_final
        if not valor:
            continue
        campo = campos_por_llave.get(p.clave)
        if not campo:
            continue
        cambio = {"tabla": campo.tabla_indice, "fila": campo.fila_indice,
                  "valor": valor, "sobrescribir": p.exige_decision}
        if valor == campo.valor and campo.confianza:
            cambio["confianza"] = campo.confianza
        cambios.append(cambio)

    if not cambios:
        return {"ok": True, "sin_cambios": True, "primera_siembra": False,
                "mensaje": "No quedó ningún cambio que escribir en la referencia."}

    # Se escribe primero una version nueva en datos/salidas/ (para llevarse,
    # igual que "Hacer nueva version" en todo el resto de la app) y LUEGO se
    # copia ese resultado ya terminado sobre la copia estable -- nunca se
    # copia un archivo sobre si mismo.
    destino_salida = tdd_nivel2.siguiente_version(
        ruta_nuevo, carpeta_destino=CARPETA_DATOS / "salidas" / "tdd_nivel2")
    resultado = tdd_nivel2.escribir_valores(Path(ref["ruta_estable"]), cambios, destino_salida)
    shutil.copy2(destino_salida, destino_estable)

    doc_final = tdd_nivel2.leer(destino_estable)
    _base().sembrar_tdd2(destino_estable, doc_final, numero)
    fechas = _base().actualizar_referencia("tdd2", numero, str(destino_estable),
                                           str(ruta_nuevo)) or {}
    _base().registrar_escritura("tdd2", numero, str(ref["ruta_estable"]),
                             str(destino_salida), resultado["aplicados"])
    log.info("TDD2 guardado | #%s | %s celdas | %s rechazadas",
             numero, len(resultado["aplicados"]), len(resultado["rechazados"]))
    return {"ok": True, "primera_siembra": False,
            "archivo": resultado["destino"], "nombre": Path(resultado["destino"]).name,
            "aplicados": resultado["aplicados"], "rechazados": resultado["rechazados"],
            "escribio_algo": bool(resultado["aplicados"]),
            "original_intacto": str(ref["ruta_estable"]), **fechas}


@app.get("/api/taxonomy")
def taxonomia():
    return {
        "tipos": taxonomy.TIPOS,
        "estados": taxonomy.ESTADOS,
        "confidencialidad": taxonomy.CONFIDENCIALIDAD,
        "tipos_relacion": taxonomy.TIPOS_RELACION,
        "tipos_diagrama": taxonomy.TIPOS_DIAGRAMA,
        "ejes_contexto": taxonomy.EJES_CONTEXTO,
        "campos_con_evidencia": taxonomy.CAMPOS_CON_EVIDENCIA_OBLIGATORIA,
        "proveedor": _proveedor()[0],
        "formatos": parsers.catalogo(),
        "extensiones": parsers.EXTENSIONES_SOPORTADAS,
        "carpeta_salida": exportador.CARPETA_SALIDA,
        "config": configuracion.estado(),
        "fuentes": fuentes.FUENTES,
        "coberturas": fuentes.COBERTURAS,
        "campos_apm": campos.de("apm"),
        "campos_tdd": campos.de("tdd"),
        "totales_declarados": fuentes.TOTALES_DECLARADOS,
    }


# Respaldo para el TDD de un habilitador que todavia no paso por el asistente
# (por eso no tiene fila en base_tdd) pero que YA tiene un documento de
# ejemplo guardado en la carpeta docs/ del proyecto -- el repositorio de
# TDD que se cargo de origen. Sin esto, la mayoria de los habilitadores
# aparecian como "sin TDD" aunque su TDD si estuviera ahi, solo que nadie lo
# habia subido todavia dentro del asistente.
_RE_DOC_TDD_CON_VERSION = re.compile(r"^TDD_V(\d+)_(.+)$", re.IGNORECASE)
_RE_DOC_TDD_SIN_VERSION = re.compile(r"^TDD_Tec__(.+)$", re.IGNORECASE)


def _docs_tdd_normalizado(nombre: str) -> str:
    """Normalizacion floja para emparejar el nombre de un habilitador contra
    el nombre de archivo de un TDD en docs/: sin parentesis (traen notas como
    "(verificar con...)" que el archivo no tiene), sin acentos, en minusculas,
    y cualquier separador que no sea letra o numero (guion, guion bajo,
    punto, diagonal...) se vuelve espacio -- "TEC.bot" y "TECbot", o
    "Rúbricas / Perfilador" y "Rubricas Perfilador", deben poder emparejar."""
    n = re.sub(r"\([^)]*\)", " ", str(nombre or ""))
    n = identificacion._norm(n)
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _docs_tdd_disponibles() -> dict[str, str]:
    """Los TDD que hay en la carpeta docs/ del proyecto, como
    {nombre_normalizado: nombre_de_archivo}."""
    carpeta = BASE_DIR.parent / "docs"
    disponibles: dict[str, str] = {}
    if not carpeta.is_dir():
        return disponibles
    for ruta in carpeta.iterdir():
        if not ruta.is_file():
            continue
        m = _RE_DOC_TDD_CON_VERSION.match(ruta.stem) or _RE_DOC_TDD_SIN_VERSION.match(ruta.stem)
        if not m:
            continue
        clave = _docs_tdd_normalizado(m.group(m.lastindex))
        if clave:
            disponibles[clave] = ruta.name
    return disponibles


def _tdd_en_docs(nombre_habilitador: str, disponibles: dict[str, str]) -> str | None:
    n = _docs_tdd_normalizado(nombre_habilitador)
    if not n:
        return None
    if n in disponibles:
        return disponibles[n]
    # Un nombre puede traer texto de mas (o de menos) que el archivo -- se
    # acepta si uno esta completamente contenido en el otro.
    for n_doc, archivo in disponibles.items():
        if n_doc and (n_doc in n or n in n_doc):
            return archivo
    # Ultimo respaldo: comparar sin espacios, para nombres pegados en el
    # archivo (p. ej. "LookerStudio") contra el nombre real ("Looker Studio").
    compacto = n.replace(" ", "")
    for n_doc, archivo in disponibles.items():
        n_doc_c = n_doc.replace(" ", "")
        if n_doc_c and (n_doc_c in compacto or compacto in n_doc_c):
            return archivo
    return None


@app.get("/api/docs-referencia")
def docs_referencia():
    """Los habilitadores que ya se tienen como referencia, con el TDD Nivel 2
    que le corresponde a cada uno (la plantilla vigente) -- para verlo de un
    vistazo.

    Unica fuente: el TDD Nivel 2 sembrado en almacen.db. El TDD_V3 (carpeta
    docs/ del proyecto) ya no se consulta aqui -- quedo retirado junto con
    el resto del TDD_V3 del asistente. Si un habilitador todavia no tiene su
    TDD Nivel 2 sembrado, se marca como pendiente. No se muestran rutas --
    solo el nombre del habilitador y el nombre del archivo del TDD Nivel 2.
    """
    tarjetas: list[dict] = []
    if BASE is not None:
        try:
            cobertura = BASE.cobertura()
        except Exception:
            cobertura = []
        for fila in cobertura:
            numero = fila["numero"]
            tdd_nombre = None
            try:
                ref_tdd2 = BASE.referencia_de("tdd2", numero)
            except Exception:
                ref_tdd2 = None
            if ref_tdd2 and ref_tdd2.get("origen_actual"):
                tdd_nombre = Path(ref_tdd2["origen_actual"]).name
            elif ref_tdd2 and ref_tdd2.get("ruta_estable"):
                tdd_nombre = Path(ref_tdd2["ruta_estable"]).stem + ".docx"
            try:
                progreso = BASE.progreso_tdd2(numero)
            except Exception:
                progreso = ["rojo"] * 6
            try:
                historial_tdd2 = BASE.tdd2_de(numero)
            except Exception:
                historial_tdd2 = []
            # -1 = sin ningun TDD Nivel 2 sembrado -- va hasta el fondo,
            # por debajo incluso de uno sembrado pero con 0% de llenado.
            completitud = historial_tdd2[0]["completitud"] if historial_tdd2 else -1
            tarjetas.append({
                "numero": numero,
                "id_habilitador": fila.get("id_habilitador") or "",
                "habilitador": fila["nombre"],
                "tdd_nombre": tdd_nombre,
                "progreso": progreso,
                "_completitud": completitud,
            })

    # Los mas llenos arriba, los que no tienen nada hasta el fondo.
    tarjetas.sort(key=lambda t: (-t["_completitud"], (t["habilitador"] or "").lower()))
    for t in tarjetas:
        del t["_completitud"]

    apm_nombre = None
    if BASE is not None:
        try:
            ref_apm = BASE.referencia_de("apm", "")
        except Exception:
            ref_apm = None
        if ref_apm and ref_apm.get("origen_actual"):
            apm_nombre = Path(ref_apm["origen_actual"]).name

    return {"ok": True, "apm_nombre": apm_nombre, "habilitadores": tarjetas}


@app.post("/api/llenado/aplicar")
def llenado_aplicar(payload: dict = Body(...)):
    """Aplica la propuesta sobre las fichas y devuelve el antes/despues.

    La fusion vive en el servidor y no en el navegador a proposito: es la misma
    regla que usara un llenado por lote de 49 aplicaciones, y dos
    implementaciones de la misma regla se separan al primer cambio.
    """
    activo = payload.get("activo") or {}
    propuesta = activo.get("_llenado") or payload.get("propuesta")
    if not propuesta:
        raise HTTPException(400, "Este documento no trae propuesta de llenado.")

    salida = {"ok": True, "fichas": {}, "cambios": {}}
    for fuente in ("apm", "tdd"):
        previa = activo.get(f"ficha_{fuente}") or {}
        nueva, cambios = llenado.aplicar(previa, propuesta, fuente)
        salida["fichas"][fuente] = nueva
        salida["cambios"][fuente] = cambios

    log.info("llenado aplicado | apm=%s campos | tdd=%s campos",
             len(salida["cambios"]["apm"]), len(salida["cambios"]["tdd"]))
    return salida


# ---------------------------------------------------------------------------
# "Hacer nueva versión" de paso 5 y paso 6
# ---------------------------------------------------------------------------
# A proposito NO usa el modelo de `conciliacion.Propuesta` (decisiones por
# celda con candidatos) que usan /api/conciliar/guardar-apm y guardar-tdd: eso
# mantendria acoplado paso 5/6 con "Revision Manual APM y TDD", justo lo que
# el proyecto pide mantener separado. Aqui la regla es mas simple y mas
# conservadora, a proposito, para no necesitar ninguna decision explicita:
#
#   Solo se escribe un campo cuando la celda REAL del libro/TDD estaba VACIA
#   (estado original "faltante" o "extraido"). Un campo "heredado" o
#   "diferente" significa que el libro/TDD YA trae contenido ahi -- eso nunca
#   se toca desde aqui, ni siquiera si la persona escribio algo distinto en la
#   casilla: resolver esos casos sigue siendo trabajo exclusivo de "Revision
#   Manual APM y TDD", con su propia pantalla de decision. Por eso el estado
#   que importa es el ORIGINAL de la ficha (`campo["estado"]`, calculado una
#   sola vez al vincular el aplicativo), no el estado "vivo" que ya cambia de
#   color en pantalla con cada tecla -- ese vivo no distingue "hueco vacio que
#   se lleno" de "encima de algo que ya estaba".

_ESTADOS_ESCRIBIBLES_NUEVA_VERSION = {"faltante", "extraido"}


@app.post("/api/llenado/nueva-version-apm")
def llenado_nueva_version_apm(payload: dict = Body(...)):
    """Escribe una version NUEVA del libro de APM con los campos que este
    documento llenó y que corresponden a celdas que el libro real tenía
    vacías. No pisa nunca una celda con contenido -- eso es de
    'Revisión Manual APM y TDD', no de aquí."""
    activo = payload.get("activo") or {}
    info_apm = activo.get("_apm") or {}
    numero = str(info_apm.get("numero") or "").strip()
    if not info_apm.get("identificado") or not numero:
        raise HTTPException(400, "Este documento no está identificado con un "
            "aplicativo real del inventario: no hay ninguna fila del libro "
            "contra la cual generar una versión nueva.")

    libro = _libro(payload.get("ruta_apm", ""))
    aplicacion = libro.aplicacion(numero=numero)
    if not aplicacion:
        raise HTTPException(404, f"No hay un aplicativo #{numero} en este libro.")

    p = ((activo.get("_llenado") or {}).get("apm")) or {}
    ficha = activo.get("ficha_apm") or {}

    cambios = []
    for grupo in p.get("grupos") or []:
        for campo in grupo.get("campos") or []:
            if campo.get("estado") not in _ESTADOS_ESCRIBIBLES_NUEVA_VERSION:
                continue
            valor = str(ficha.get(campo.get("clave"), "") or "").strip()
            if not valor:
                continue
            cambios.append({"fila": aplicacion.fila, "clave": campo["clave"],
                            "valor": valor})

    if not cambios:
        return {"ok": True, "sin_cambios": True, "mensaje":
                "No hay campos vacíos del libro con un dato nuevo que escribir."}

    destino = apm.siguiente_version(libro.ruta, carpeta_destino=CARPETA_DATOS / "salidas" / "APM")
    resultado = libro.escribir_version(cambios, destino)
    _base().registrar_escritura("apm", aplicacion.numero, str(libro.ruta),
                             str(destino), resultado["aplicados"])

    # La base sembrada tiene que enterarse de esta version nueva -- si no, la
    # "Revision Manual APM y TDD" y cualquier escaneo posterior seguirian
    # comparando contra el libro viejo aunque este boton ya haya escrito una
    # version mas reciente. Se resiembra desde EL DESTINO (no desde el
    # original): es el mismo libro con las celdas nuevas encima, asi que
    # resembrarlo actualiza todo el aplicativo, no solo la celda que se tocó.
    base_actualizada = False
    try:
        libro_nuevo = _libro(str(destino))
        _base().sembrar_apm(libro_nuevo)
        _actualizar_referencia_apm(libro_nuevo, str(destino))
        base_actualizada = True
    except Exception:
        log.exception("no se pudo actualizar la base sembrada tras la nueva "
                       "version de APM (%s)", destino)

    log.info("nueva version APM (paso 5) | %s | %s celdas | base_actualizada=%s",
             Path(destino).name, len(resultado["aplicados"]), base_actualizada)
    return {"ok": True, "archivo": resultado["destino"], "nombre": Path(destino).name,
            "aplicados": resultado["aplicados"], "rechazados": resultado["rechazados"],
            "claves_escritas": [a["clave"] for a in resultado["aplicados"]],
            "original_intacto": str(libro.ruta),
            "base_actualizada": base_actualizada,
            "actualizado_en": almacen.ahora() if base_actualizada else None}


@app.post("/api/llenado/nueva-version-tdd")
def llenado_nueva_version_tdd(payload: dict = Body(...)):
    """Escribe una version NUEVA del TDD Nivel 2 real con los campos que este
    documento lleno y que corresponden a campos que la referencia tenia
    vacios. Solo aplica cuando SI hay un TDD Nivel 2 real sembrado (no una
    propuesta): sin una referencia real no hay donde escribir.

    Reemplaza la version que escribia sobre el TDD_V3 viejo (`tdd.py`) --
    ahora escribe con `tdd_nivel2.escribir_valores`, igual mecanismo que usa
    `/api/tdd2/guardar`: una version nueva en datos/salidas/ (el original no
    se toca) que despues se adopta como la copia estable interna."""
    activo = payload.get("activo") or {}
    info_apm = activo.get("_apm") or {}

    p = ((activo.get("_llenado") or {}).get("tdd")) or {}
    if not p.get("grupos") or p.get("es_propuesta"):
        raise HTTPException(400, "Este aplicativo no tiene un TDD Nivel 2 real "
            "sembrado en la base (lo de abajo es solo una propuesta): no hay "
            "ningún documento real donde escribir una versión nueva.")

    tdds2 = info_apm.get("tdd") or []
    ruta_tdd2 = tdds2[0].get("ruta") if tdds2 else ""
    if not ruta_tdd2 or not Path(ruta_tdd2).exists():
        raise HTTPException(404, "No se encontró el archivo del TDD Nivel 2 real en el equipo.")

    referencia = tdd_nivel2.leer(Path(ruta_tdd2))
    campo_por_llave = {c.llave: c for c in referencia.campos}

    ficha = activo.get("ficha_tdd") or {}
    cambios = []
    for grupo in p.get("grupos") or []:
        for campo in grupo.get("campos") or []:
            if campo.get("estado") not in _ESTADOS_ESCRIBIBLES_NUEVA_VERSION:
                continue
            valor = str(ficha.get(campo.get("clave"), "") or "").strip()
            if not valor:
                continue
            campo_ref = campo_por_llave.get(str(campo.get("clave") or ""))
            if not campo_ref:
                continue
            cambios.append({"tabla": campo_ref.tabla_indice, "fila": campo_ref.fila_indice,
                            "valor": valor, "sobrescribir": False})

    if not cambios:
        return {"ok": True, "sin_cambios": True, "mensaje":
                "No hay campos vacíos del TDD Nivel 2 con un dato nuevo que escribir."}

    destino = tdd_nivel2.siguiente_version(
        Path(ruta_tdd2), carpeta_destino=CARPETA_DATOS / "salidas" / "tdd_nivel2")
    resultado = tdd_nivel2.escribir_valores(Path(ruta_tdd2), cambios, destino)
    numero = str(info_apm.get("numero") or "")
    _base().registrar_escritura("tdd2", numero, str(ruta_tdd2),
                             str(destino), resultado["aplicados"])

    # Mismo criterio que /api/tdd2/guardar: la version nueva escrita en
    # salidas/ se adopta TAMBIEN como la copia estable interna, y la base se
    # resiembra desde ahi, para que quede como la version mas reciente contra
    # la que se compara de aqui en adelante.
    base_actualizada = False
    try:
        shutil.copy2(destino, Path(ruta_tdd2))
        doc_nuevo = tdd_nivel2.leer(Path(ruta_tdd2))
        _base().sembrar_tdd2(Path(ruta_tdd2), doc_nuevo, numero)
        if numero:
            _base().actualizar_referencia("tdd2", numero, str(ruta_tdd2), str(destino))
        base_actualizada = True
    except Exception:
        log.exception("no se pudo actualizar la base sembrada tras la nueva "
                       "version de TDD Nivel 2 (%s)", destino)

    llave_por_pos = {(c.tabla_indice, c.fila_indice): c.llave for c in referencia.campos}
    log.info("nueva version TDD Nivel 2 (paso 6) | %s | %s celdas | base_actualizada=%s",
             destino.name, len(resultado["aplicados"]), base_actualizada)
    return {"ok": True, "archivo": resultado["destino"], "nombre": destino.name,
            "aplicados": resultado["aplicados"], "rechazados": resultado["rechazados"],
            "claves_escritas": [llave_por_pos.get((a["tabla"], a["fila"]), "")
                                for a in resultado["aplicados"]],
            "original_intacto": str(ruta_tdd2),
            "base_actualizada": base_actualizada,
            "actualizado_en": almacen.ahora() if base_actualizada else None}


@app.post("/api/vincular-manual")
def vincular_manual(payload: dict = Body(...)):
    """Fuerza la comparacion de un documento ya escaneado contra un aplicativo
    elegido A MANO, en vez del que decidio (o no decidio) el amarre
    automatico. Sirve para dos casos: el amarre fallo y la persona sabe a
    cual aplicativo pertenece, o el documento menciona mas de uno (candidatos)
    y hay que decir cual es el suyo.

    A proposito NO escribe nada en el almacen: es una comparacion bajo
    demanda para revisar, no un nuevo registro de "documento visto" -- eso
    solo lo hace el amarre automatico, que es el que corre una vez por
    escaneo real.

    `doc` (opcional): la instantanea del documento ya parseado que
    `_clasificar_ruta` deja en `activo["_doc_snapshot"]`. Si viene, no hace
    falta releer el archivo del disco -- eso es lo que permite usar este
    selector con un documento que se SUBIO desde el navegador, cuyo temporal
    ya se borro despues del analisis original. Sin `doc`, se relee por
    `ruta` como antes (documentos abiertos por ruta o carpeta).
    """
    ruta = str(payload.get("ruta") or "").strip().strip('"')
    ruta_apm = str(payload.get("ruta_apm") or "").strip().strip('"')
    numero = str(payload.get("numero") or "").strip()
    doc_snapshot = payload.get("doc") or None
    if not ruta and not doc_snapshot:
        raise HTTPException(400, "Falta la ruta del documento.")
    if not numero:
        raise HTTPException(400, "Falta el número de aplicativo.")

    nombre = str(payload.get("nombre") or "").strip() or (Path(ruta).name if ruta else "documento")

    if doc_snapshot is not None:
        doc = doc_snapshot
    else:
        # Misma regla que el amarre automatico: el libro de APM y los TDD son
        # destino, no materia prima. Sin este corte, elegir un aplicativo a
        # mano para el propio TDD terminaria comparando el TDD contra si
        # mismo -- el mismo problema que la exclusion de _clasificar_ruta
        # existe para evitar. Solo aplica cuando SI se relee del disco: la
        # instantanea ya paso por esa misma exclusion la primera vez.
        papel = identificacion.clasificar_archivo(Path(ruta))
        if not papel.es_fuente:
            raise HTTPException(
                400, f"Este documento no se puede usar como fuente: {papel.motivo}")
        doc = parsers.parse(ruta, nombre)

    libro = _libro(ruta_apm)
    app_real = libro.aplicacion(numero=numero)
    if app_real is None:
        raise HTTPException(404, f"No existe el aplicativo #{numero} en el libro de APM.")

    hallazgos = extraccion.extraer(doc, libro, nombre)

    apm_info = {
        "disponible": True, "identificado": True, "aplicacion_nueva": False,
        "numero": app_real.numero, "nombre_aplicativo": app_real.nombre,
        "id_habilitador": app_real.id_habilitador, "senal": "manual",
        "evidencia": "elegido a mano por la persona que revisa",
        "candidatos": [], "campos_encontrados": len(hallazgos),
        "ficha_apm": _ficha_apm_real(libro, app_real, hallazgos, doc),
    }
    try:
        apm_info["tdd"] = BASE.tdd2_de(numero) if BASE is not None else []
    except Exception:
        apm_info["tdd"] = []
    ruta_para_tdd2 = Path(ruta) if ruta else None
    apm_info["ficha_tdd"] = _ficha_tdd_para_numero(numero, doc, ruta_para_tdd2)

    ficha_tdd = apm_info["ficha_tdd"]
    llenado_info = {
        "apm": apm_info["ficha_apm"],
        "tdd": ficha_tdd or {"grupos": [], "resumen": {
            "total": 0, "llenos": 0, "extraidos": 0,
            "heredados": 0, "diferentes": 0, "faltantes": 0, "porcentaje": 0}},
    }
    return {"ok": True, "apm": apm_info, "llenado": llenado_info}


# ---------------------------------------------------------------------------
# MODO 1: UN ARCHIVO
# ---------------------------------------------------------------------------

@app.post("/api/analyze")
async def analizar_subido(file: UploadFile = File(...), ruta_apm: str = Form(""),
                          forzar: str = Form("")):
    """Archivo subido por el navegador. Ciclo temporal: se borra en el finally."""
    nombre = os.path.basename(file.filename or "documento")
    nombre = "".join(c for c in nombre if c.isalnum() or c in " ._-()").strip()
    if not parsers.soportado(nombre):
        raise HTTPException(400, f"Formato no soportado. Aceptados: "
                                 f"{', '.join(parsers.EXTENSIONES_SOPORTADAS)}")

    contenido = await file.read()
    if not contenido:
        raise HTTPException(400, "El archivo llego vacio.")
    if len(contenido) > MAX_BYTES:
        raise HTTPException(400, f"El archivo excede {MAX_MB} MB.")

    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
                delete=False, suffix=Path(nombre).suffix) as tmp:
            tmp.write(contenido)
            temporal = tmp.name
        del contenido
        return _responder_uno(temporal, nombre, ruta_origen=nombre,
                              ruta_apm=(ruta_apm or "").strip().strip('"'),
                              forzar=str(forzar or "").strip().lower() in ("1", "true", "si", "sí"))
    finally:
        if temporal and os.path.exists(temporal):
            try:
                os.remove(temporal)
            except OSError:
                log.warning("no se pudo eliminar el temporal")


# ---------------------------------------------------------------------------
# Descarga por URL
# ---------------------------------------------------------------------------
# Lo que hace peligrosa esta funcion no es descargar: es que SharePoint, OneDrive
# y Drive le responden a un cliente sin sesion con la PAGINA DE LOGIN, no con el
# documento. Sin la deteccion de abajo, la aplicacion parsearia ese HTML como si
# fuera el archivo y clasificaria la pantalla de inicio de sesion, con su titulo
# y sus campos. Un dato plausible y falso, que es justo lo que esto existe para
# no producir.

SENALES_LOGIN = ("sign in", "iniciar sesión", "iniciar sesion", "log in",
                 "microsoftonline", "accounts.google.com", "adfs",
                 "authentication required", "office365")


def _descargar(url: str) -> tuple[str, str]:
    """Baja la URL a un temporal. Devuelve (ruta_temporal, nombre_sugerido)."""
    import urllib.parse
    import urllib.request

    if len(url) > 2000:
        raise HTTPException(400, "La URL es absurdamente larga.")

    peticion = urllib.request.Request(url, headers={"User-Agent": "POC-IA-Ready-TEC"})
    try:
        with urllib.request.urlopen(peticion, timeout=45) as resp:
            tipo = (resp.headers.get("Content-Type") or "").lower()
            largo = int(resp.headers.get("Content-Length") or 0)
            if largo and largo > MAX_BYTES:
                raise HTTPException(400,
                    f"El archivo pesa {largo // 1024 // 1024} MB y el límite es "
                    f"{MAX_MB} MB. Bájalo tú y pasa la ruta local.")

            # Nombre: primero el que declare el servidor, luego el de la URL.
            nombre = ""
            disp = resp.headers.get("Content-Disposition") or ""
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disp)
            if m:
                nombre = urllib.parse.unquote(m.group(1)).strip()
            if not nombre:
                nombre = os.path.basename(urllib.parse.urlparse(url).path) or "descarga"

            # La extension decide que parser se usa, asi que si la URL no la trae
            # se deduce del Content-Type. Sin extension no hay parser posible.
            if not Path(nombre).suffix:
                for ext, marca in ((".pdf", "pdf"), (".docx", "wordprocessingml"),
                                   (".xlsx", "spreadsheetml"), (".pptx", "presentationml"),
                                   (".html", "text/html"), (".txt", "text/plain"),
                                   (".png", "image/png"), (".jpg", "image/jpeg")):
                    if marca in tipo:
                        nombre += ext
                        break

            datos = resp.read(MAX_BYTES + 1)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"No se pudo descargar: {exc}")

    if len(datos) > MAX_BYTES:
        raise HTTPException(400,
            f"El archivo excede {MAX_MB} MB. Bájalo tú y pasa la ruta local.")
    if not datos:
        raise HTTPException(400, "La URL respondió vacío.")

    # ¿Es el documento, o la pantalla de login del repositorio?
    if "text/html" in tipo or datos[:200].lstrip()[:15].lower().startswith(b"<!doctype html"):
        muestra = datos[:6000].decode("utf-8", "ignore").lower()
        if any(s in muestra for s in SENALES_LOGIN):
            raise HTTPException(400,
                "Esa liga pide iniciar sesión: lo que se descargó es la pantalla de "
                "login, no el documento. Ábrelo tú, guárdalo, y pasa la ruta local "
                "(o sincroniza la biblioteca de SharePoint en tu equipo).")

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(nombre).suffix) as tmp:
        tmp.write(datos)
        return tmp.name, os.path.basename(nombre)


@app.post("/api/analyze-ruta")
def analizar_ruta(payload: dict = Body(...)):
    """Archivo que ya vive en el disco, o una URL. No se copia ni se modifica."""
    crudo = str(payload.get("ruta", "")).strip().strip('"')
    if not crudo:
        raise HTTPException(400, "Falta la ruta del archivo.")
    ruta_apm = str(payload.get("ruta_apm", "")).strip().strip('"')
    forzar = bool(payload.get("forzar", False))

    if crudo.lower().startswith(("http://", "https://")):
        temporal, nombre = _descargar(crudo)
        if not parsers.soportado(nombre):
            os.remove(temporal)
            raise HTTPException(400,
                f"Lo que hay en esa URL no es un formato que se pueda leer "
                f"({Path(nombre).suffix or 'sin extensión'}).")
        try:
            return _responder_uno(temporal, nombre, ruta_origen=crudo, ruta_apm=ruta_apm,
                                  forzar=forzar)
        finally:
            if os.path.exists(temporal):
                try:
                    os.remove(temporal)
                except OSError:
                    log.warning("no se pudo eliminar el temporal de la descarga")

    ruta = Path(crudo)
    if not ruta.exists():
        raise HTTPException(404, f"No existe: {ruta}")
    if not ruta.is_file():
        raise HTTPException(400, f"La ruta no es un archivo: {ruta}")
    return _responder_uno(str(ruta), ruta.name, ruta_origen=str(ruta), ruta_apm=ruta_apm,
                          forzar=forzar)


def _responder_uno(ruta: str, nombre: str, ruta_origen: str, ruta_apm: str = "",
                   forzar: bool = False, on_etapa=None):
    inicio_t = time.perf_counter()
    try:
        activo, doc, proveedor, etapas = _clasificar_ruta(
            ruta, nombre, ruta_apm=ruta_apm, forzar=forzar, on_etapa=on_etapa)
    except DestinoExcluido as exc:
        # Es el propio APM o un TDD: no es un error, es exactamente lo que se
        # supone que pase. En vez de solo decirlo, se aprovecha para sembrar
        # (o actualizar) la referencia directamente -- Paso 2 · Parte A: ya no
        # hace falta pasar por la pantalla aparte de "Revisión Manual APM y
        # TDD" para fijar el APM o un TDD.
        siembra = None
        try:
            if exc.tipo == "apm":
                siembra = _sembrar_apm_desde_subida(ruta, nombre)
            elif exc.tipo == "tdd2":
                siembra = _sembrar_tdd2_desde_subida(ruta, nombre, ruta_apm)
            elif exc.tipo == "tdd":
                siembra = _sembrar_tdd_desde_subida(ruta, nombre, ruta_apm)
        except Exception:
            log.exception("fallo sembrando la referencia desde Inicio")
            siembra = {"ok": False, "motivo": "ocurrió un error inesperado al sembrar"}

        return JSONResponse({
            "ok": True, "excluido": True, "tipo_excluido": exc.tipo,
            "motivo": exc.motivo, "nombre": nombre,
            "referencia_actualizada": bool(siembra and siembra.get("ok")),
            "referencia": siembra,
        })
    except FalloAnalisis as exc:
        # Se sabe exactamente en cual de las 4 etapas trueno -- se manda tal
        # cual para que la pantalla pinte esa etapa (y solo esa) en rojo, con
        # su propio motivo, en vez de adivinar.
        log.warning("fallo el analisis en la etapa '%s' | %s | %s",
                    exc.etapa, nombre, exc)
        return JSONResponse(status_code=exc.status_code, content={
            "ok": False,
            "detail": f"La clasificacion no se completo: {exc}",
            "etapa_fallida": exc.etapa,
            "etapas": exc.etapas,
        })
    except FormatoNoSoportado as exc:
        raise HTTPException(400, str(exc))
    except DocumentoIlegible as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        log.exception("fallo el analisis")
        raise HTTPException(502, f"La clasificacion no se completo: {exc}")

    duracion = round(time.perf_counter() - inicio_t, 2)
    log.info("analisis ok | %s | %s | %ss | revision=%s",
             proveedor, doc["formato"], duracion, len(activo["requiere_revision"]))

    return JSONResponse({
        "ok": True,
        "duracion_segundos": duracion,
        "proveedor": proveedor,
        "activo": activo,
        "etapas": etapas,
        "markdown": exportador.a_markdown(
            activo, _texto_para_markdown(doc), ruta_origen),
        "nombre_sugerido": exportador.nombre_base(activo),
    })


# ---------------------------------------------------------------------------
# MODO 1 - EN VIVO: UN DOCUMENTO, CON AVANCE REAL POR ETAPA
# ---------------------------------------------------------------------------
# Mismo patron que un lote (ver lotes.py): la peticion HTTP solo arranca el
# trabajo en un hilo aparte y responde un id al instante; el navegador va
# preguntando el avance real -- la MISMA informacion por etapa que ya arma
# _clasificar_ruta, incluida la vinculacion contra el aplicativo real -- en
# vez de fingir un avance con un temporizador.

def _ejecutar_para_vivo(analisis: progreso_vivo.Analisis, ruta: str, nombre: str,
                        ruta_origen: str, ruta_apm: str, forzar: bool) -> None:
    def on_etapa(etapa: str, info: dict) -> None:
        analisis.etapas[etapa] = info
        if etapa == "vinculacion":
            analisis.vinculacion = info

    try:
        respuesta = _responder_uno(ruta, nombre, ruta_origen, ruta_apm, forzar,
                                   on_etapa=on_etapa)
    except HTTPException as exc:
        analisis.error = {"ok": False, "detail": exc.detail}
        analisis.estado = "error"
        return
    except Exception as exc:
        log.exception("fallo el analisis en vivo")
        analisis.error = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        analisis.estado = "error"
        return

    cuerpo = json.loads(bytes(respuesta.body))
    if cuerpo.get("ok") is False:
        analisis.error = cuerpo
        analisis.estado = "error"
    else:
        analisis.resultado = cuerpo
        analisis.estado = "terminado"


@app.post("/api/analizar-vivo")
def analizar_vivo_iniciar(payload: dict = Body(...)):
    """Como /api/analyze-ruta, pero no espera: registra el trabajo y responde
    un id al instante. El avance real se consulta con GET /api/analizar-vivo/{id}."""
    crudo = str(payload.get("ruta", "")).strip().strip('"')
    if not crudo:
        raise HTTPException(400, "Falta la ruta del archivo.")
    ruta_apm = str(payload.get("ruta_apm", "")).strip().strip('"')
    forzar = bool(payload.get("forzar", False))

    borrar_al_final = False
    if crudo.lower().startswith(("http://", "https://")):
        temporal, nombre = _descargar(crudo)
        if not parsers.soportado(nombre):
            os.remove(temporal)
            raise HTTPException(400,
                f"Lo que hay en esa URL no es un formato que se pueda leer "
                f"({Path(nombre).suffix or 'sin extensión'}).")
        ruta_final, nombre_final, origen = temporal, nombre, crudo
        borrar_al_final = True
    else:
        ruta = Path(crudo)
        if not ruta.exists():
            raise HTTPException(404, f"No existe: {ruta}")
        if not ruta.is_file():
            raise HTTPException(400, f"La ruta no es un archivo: {ruta}")
        ruta_final, nombre_final, origen = str(ruta), ruta.name, str(ruta)

    analisis = progreso_vivo.crear()

    def trabajo(a: progreso_vivo.Analisis) -> None:
        try:
            _ejecutar_para_vivo(a, ruta_final, nombre_final, origen, ruta_apm, forzar)
        finally:
            if borrar_al_final and os.path.exists(ruta_final):
                try:
                    os.remove(ruta_final)
                except OSError:
                    log.warning("no se pudo eliminar el temporal de la descarga")

    progreso_vivo.lanzar(analisis, trabajo)
    return {"ok": True, "id": analisis.id}


@app.post("/api/analizar-vivo/subir")
async def analizar_vivo_subir(file: UploadFile = File(...), ruta_apm: str = Form(""),
                              forzar: str = Form("")):
    """Como /api/analyze, pero en segundo plano -- ver analizar_vivo_iniciar."""
    nombre = os.path.basename(file.filename or "documento")
    nombre = "".join(c for c in nombre if c.isalnum() or c in " ._-()").strip()
    if not parsers.soportado(nombre):
        raise HTTPException(400, f"Formato no soportado. Aceptados: "
                                 f"{', '.join(parsers.EXTENSIONES_SOPORTADAS)}")

    contenido = await file.read()
    if not contenido:
        raise HTTPException(400, "El archivo llego vacio.")
    if len(contenido) > MAX_BYTES:
        raise HTTPException(400, f"El archivo excede {MAX_MB} MB.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(nombre).suffix) as tmp:
        tmp.write(contenido)
        temporal = tmp.name
    del contenido

    analisis = progreso_vivo.crear()
    ruta_apm_limpia = (ruta_apm or "").strip().strip('"')
    forzar_bool = str(forzar or "").strip().lower() in ("1", "true", "si", "sí")

    def trabajo(a: progreso_vivo.Analisis) -> None:
        try:
            _ejecutar_para_vivo(a, temporal, nombre, nombre, ruta_apm_limpia, forzar_bool)
        finally:
            if os.path.exists(temporal):
                try:
                    os.remove(temporal)
                except OSError:
                    log.warning("no se pudo eliminar el temporal")

    progreso_vivo.lanzar(analisis, trabajo)
    return {"ok": True, "id": analisis.id}


@app.get("/api/analizar-vivo/{analisis_id}")
def analizar_vivo_estado(analisis_id: str):
    analisis = progreso_vivo.obtener(analisis_id)
    if not analisis:
        raise HTTPException(404, "Ese análisis no existe o ya expiró.")
    return analisis.resumen()


# ---------------------------------------------------------------------------
# MODO 2: UNA CARPETA
# ---------------------------------------------------------------------------

@app.post("/api/explorar")
def explorar_carpeta(payload: dict = Body(...)):
    """Vista previa del alcance. No clasifica nada: solo dice que hay."""
    ruta = str(payload.get("ruta", "")).strip().strip('"')
    if not ruta:
        raise HTTPException(400, "Falta la ruta de la carpeta.")
    try:
        return lotes.explorar(Path(ruta), bool(payload.get("recursivo", True)))
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(404, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Sin permiso para leer: {ruta}")


@app.post("/api/lote")
def iniciar_lote(payload: dict = Body(...)):
    """Arranca el procesamiento en segundo plano y responde el id al instante."""
    ruta = str(payload.get("ruta", "")).strip().strip('"')
    recursivo = bool(payload.get("recursivo", True))
    escribir = bool(payload.get("escribir", True))
    ruta_apm = str(payload.get("ruta_apm", "")).strip().strip('"')

    try:
        exploracion = lotes.explorar(Path(ruta), recursivo)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(404, str(exc))

    archivos = exploracion["aceptados"]
    if not archivos:
        raise HTTPException(400, "No hay archivos procesables en esa carpeta.")

    salida = Path(ruta) / exportador.CARPETA_SALIDA
    lote = lotes.crear(ruta, len(archivos), str(salida) if escribir else "")

    def trabajo(l: lotes.Lote):
        for archivo in archivos:
            if l.cancelar:
                l.estado = "cancelado"
                return
            l.actual = archivo["nombre"]
            try:
                activo, doc, _, _ = _clasificar_ruta(
                    archivo["ruta"], Path(archivo["ruta"]).name, ruta_apm=ruta_apm)
                fila = {
                    "nombre": archivo["nombre"],
                    "ruta": archivo["ruta"],
                    "ok": True,
                    "id": activo["id"],
                    "titulo": activo.get("titulo", ""),
                    "tipo": activo["tipo"],
                    "estado": activo["estado"],
                    "formato": doc["formato"],
                    "requiere_revision": activo["requiere_revision"],
                    "n_diagramas": len(activo.get("diagramas") or []),
                }
                # Referencia al aplicativo, para la tabla de avance del paso 3
                # sin tener que ir a abrir el activo completo.
                apm_info = activo.get("_apm")
                if apm_info and apm_info.get("disponible"):
                    fila["aplicativo"] = {
                        "identificado": apm_info.get("identificado", False),
                        "numero": apm_info.get("numero", ""),
                        "nombre": apm_info.get("nombre_aplicativo", ""),
                        "valido": apm_info.get("valido", True),
                        "ya_conocido": apm_info.get("ya_conocido", False),
                        "motivo": apm_info.get("motivo", ""),
                    }
                texto_md = _texto_para_markdown(doc)
                if escribir:
                    rutas = exportador.escribir(
                        activo, salida, texto_md, archivo["nombre"])
                    fila["archivos"] = rutas
                fila["activo"] = activo
                # Se guarda el texto para que, si el humano corrige un campo en
                # el paso 4, el .md re-exportado siga trayendo el contenido y no
                # solo la ficha. Se recorta para no inflar la memoria del lote.
                fila["texto"] = texto_md[:30_000]
            except DestinoExcluido as exc:
                # Es el propio APM o un TDD: no cuenta como error ni como
                # documento a revisar, se reporta aparte y sigue el lote.
                fila = {"nombre": archivo["nombre"], "ok": True, "excluido": True,
                        "tipo_excluido": exc.tipo, "motivo": exc.motivo}
            except FalloAnalisis as exc:
                # Igual que en el analisis de un solo documento: se sabe en
                # cual etapa trueno. La tabla de avance del lote solo tiene
                # espacio para un mensaje, asi que se antepone la etapa.
                l.con_error += 1
                fila = {"nombre": archivo["nombre"], "ok": False,
                        "error": f"[{exc.etapa}] {exc}"}
            except Exception as exc:
                l.con_error += 1
                fila = {"nombre": archivo["nombre"], "ok": False,
                        "error": f"{type(exc).__name__}: {exc}"}
            l.resultados.append(fila)
            l.procesados += 1

    lotes.lanzar(lote, trabajo)
    log.info("lote %s iniciado | %s archivos | salida=%s",
             lote.id, len(archivos), salida if escribir else "(sin escribir)")
    return {"ok": True, "lote": lote.resumen(),
            "descartados": exploracion["descartados"]}


@app.get("/api/lote/{lote_id}")
def estado_lote(lote_id: str, detalle: bool = False):
    lote = lotes.obtener(lote_id)
    if not lote:
        raise HTTPException(404, "Lote no encontrado o ya expirado.")
    resumen = lote.resumen()
    if not detalle:
        # sin el activo completo: la vista de avance no lo necesita
        resumen["resultados"] = [
            {k: v for k, v in r.items() if k not in ("activo", "texto")}
            for r in resumen["resultados"]]
    return resumen


@app.post("/api/lote/{lote_id}/cancelar")
def cancelar_lote(lote_id: str):
    if not lotes.cancelar(lote_id):
        raise HTTPException(400, "El lote ya termino o no existe.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# EXPORTACION Y VALIDACION
# ---------------------------------------------------------------------------

@app.post("/api/exportar")
def exportar(payload: dict = Body(...)):
    """Escribe el activo editado por el humano. El .md refleja las correcciones,
    que es el punto del human-in-the-loop: lo que se indexa es lo revisado."""
    activo = payload.get("activo") or {}
    if not activo:
        raise HTTPException(400, "Falta el activo.")

    texto = str(payload.get("texto", ""))
    ruta_origen = str(payload.get("ruta_origen", ""))
    markdown = exportador.a_markdown(activo, texto, ruta_origen)

    # Vista previa: se genera con el MISMO formateador que usa el lote, para
    # que lo que el usuario ve en pantalla sea byte por byte lo que se guarda.
    if payload.get("solo_vista"):
        return {"ok": True, "markdown": markdown}

    destino = str(payload.get("carpeta", "")).strip().strip('"')
    if not destino:
        raise HTTPException(400, "Falta la carpeta de destino.")

    carpeta = Path(destino)
    if carpeta.is_file():
        carpeta = carpeta.parent
    carpeta = carpeta / exportador.CARPETA_SALIDA

    try:
        rutas = exportador.escribir(activo, carpeta, texto, ruta_origen)
    except PermissionError:
        raise HTTPException(403, f"Sin permiso de escritura en {carpeta}")
    except OSError as exc:
        raise HTTPException(400, f"No se pudo escribir: {exc}")

    log.info("exportado | %s", rutas["md"])
    return {"ok": True, "archivos": rutas, "carpeta": str(carpeta),
            "markdown": markdown}


@app.post("/api/validate", response_model=RespuestaValidacion)
def validar_activo(payload: SolicitudValidacion):
    activo = payload.activo or {}
    pendientes = [c for c in taxonomy.ATRIBUTOS
                  if isinstance(activo.get(c), str)
                  and activo[c].startswith("No identificad")]
    mensaje = ("Activo marcado como pendiente de informacion."
               if payload.decision == "pendiente"
               else "Activo de conocimiento validado.")
    log.info("validacion | %s | pendientes=%s", payload.decision, len(pendientes))
    return RespuestaValidacion(ok=True, mensaje=mensaje, decision=payload.decision,
                               campos_pendientes=pendientes)
