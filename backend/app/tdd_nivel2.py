"""
tdd_nivel2.py
-------------
TDD Nivel 2 (Gobierno de Aplicativos): la plantilla nueva de TDD, con escala de
confianza C1-C4 por dato. Reemplaza al TDD_V3 (tdd.py) como lo que usa el
portal para comparar TDD -- TDD_V3 ya no se ocupa.

La diferencia que manda todo este archivo: el TDD Nivel 2 JAMAS se llena
citando al APM Portafolio, al inventario, ni a una version anterior del TDD
como fuente -- cada dato lleva su propia ruta real de origen (regla del
proyecto). Por eso esta herramienta no "llena" el TDD Nivel 2 automaticamente
desde el APM, como si hacia tdd.py con el TDD_V3 (`mapear_apm_a_tdd`). En vez
de eso, compara DOS documentos que una persona ya lleno bajo esas reglas --
el que se sube, contra el que ya esta sembrado como referencia -- campo por
campo, seccion por seccion, y deja toda diferencia como conflicto para que
alguien decida. Igual que conciliacion.py: la aplicacion nunca resuelve un
desacuerdo sola.

La plantilla tiene 17 secciones (0 a 16) mas 3 anexos, y CADA tabla de dato
sigue el mismo patron de 3 (o mas) columnas: `Campo | Informacion a
documentar | Confianza`. Eso permite un solo parser generico en vez de un
mapa de campos a mano como el de TDD_V3 -- aqui no hace falta, la plantilla
ya es uniforme.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from . import conciliacion as _conciliacion
from . import identificacion as _identificacion


def _norm(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


def _norm_camel(texto) -> str:
    """Para nombres de archivo tipo `PortalRegistroPago`: separa las palabras
    pegadas antes de normalizar, para poder emparejar contra un nombre real
    escrito con espacios."""
    t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(texto or ""))
    t = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", t)
    return _norm(t)


_STOPWORDS = {"de", "del", "la", "el", "los", "las", "y", "en", "a", "al"}


def _slug(texto) -> str:
    """Forma mas floja de comparar dos nombres del mismo aplicativo: quita
    primero cualquier anotacion entre parentesis -- nombres del APM como
    «SAP (verificar información con Lulu Ayala)» o «FUD (DWH)» traen una nota
    que el archivo del TDD nunca repite, igual que ya hace main.py para el
    TDD_V3 (`_docs_tdd_normalizado`) -- separa las palabras pegadas tipo
    camelCase, quita acentos y mayusculas, quita toda la puntuacion (incluida
    `/`, que aparece en nombres como «Sistema de Rúbricas / Perfilador»),
    quita palabras de relleno («de», «y»...) y junta todo sin espacios. Con
    esto, "Portal de registro y pago" y el archivo "PortalRegistroPago"
    quedan los dos en `portalregistropago`."""
    texto = re.sub(r"\([^)]*\)", " ", str(texto or ""))
    n = _norm_camel(texto)
    n = re.sub(r"[^a-z0-9\s]+", " ", n)
    palabras = [p for p in n.split() if p not in _STOPWORDS]
    return "".join(palabras)


# Igual que tdd.celda_vacia, pero adaptado a como el TDD Nivel 2 escribe "no
# hay dato": "Sin informacion.", "Pendiente de designacion...", vacio, etc.
_VACIOS = {
    "", "-", "--", "n/a", "na", "n.a.", "nd", "n/d", "no aplica", "ninguno",
    "por definir", "tbd", "pendiente", "sin informacion", "sin información",
    "sin información.", "sin informacion.", "completar",
}


def _texto_vacio(texto: str) -> bool:
    n = _norm(texto).rstrip(".")
    if n in _VACIOS or len(n) < 2:
        return True
    return n.startswith("sin informacion") or n.startswith("pendiente de")


def campo_pendiente(valor: str, confianza: str) -> bool:
    """Un campo cuenta como "todavia no hay nada que comparar" cuando su
    texto esta vacio de facto, sin importar la confianza declarada -- una
    celda puede decir C4 y aun asi traer una nota util, o decir C1 y estar
    vacia por error de captura. El texto manda."""
    return _texto_vacio(valor)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _iter_bloques(document):
    """Recorre el documento en el orden real en que aparece cada parrafo y
    cada tabla -- python-docx por separado solo da `.paragraphs` y `.tables`,
    sin su orden relativo, y aqui hace falta saber bajo que seccion cae cada
    tabla."""
    cuerpo = document.element.body
    for hijo in cuerpo.iterchildren():
        if hijo.tag.endswith("}p"):
            yield Paragraph(hijo, document)
        elif hijo.tag.endswith("}tbl"):
            yield Table(hijo, document)


_RE_TITULO_SECCION = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\.?\s+(.+)$")
_RE_CONFIANZA = re.compile(r"\bC([1-4])\b", re.I)


@dataclass
class CampoTDD2:
    seccion: str          # "0.1", "5.2", "Anexo C"...
    seccion_titulo: str   # "0.1 Identificación"
    campo: str             # "ID-habilitador"
    valor: str = ""
    confianza: str = ""    # "C1".."C4" o ""
    tabla_indice: int = 0  # 1-based, por si mas adelante hace falta escribir
    fila_indice: int = 0
    ncols: int = 0          # columnas de la fila -- 3 = un solo dato que escribir

    @property
    def llave(self) -> str:
        return f"{self.seccion}::{_norm(self.campo)}"

    @property
    def vacio(self) -> bool:
        return campo_pendiente(self.valor, self.confianza)


@dataclass
class DocumentoTDD2:
    ruta: Path
    id_habilitador: str = ""
    nombre_aplicativo: str = ""
    campos: list[CampoTDD2] = field(default_factory=list)

    def campo(self, llave: str) -> CampoTDD2 | None:
        return next((c for c in self.campos if c.llave == llave), None)

    @property
    def campos_con_dato(self) -> list[CampoTDD2]:
        return [c for c in self.campos if not c.vacio]


def _es_tabla_de_campos(filas: list[list[str]]) -> bool:
    """Reconoce una tabla `Campo | Información a documentar | Confianza` por
    su encabezado, sin importar cuantas columnas trae en medio (algunas,
    como Usuarios o Integraciones, traen mas de 3)."""
    if len(filas) < 2 or len(filas[0]) < 2:
        return False
    primera = _norm(filas[0][0])
    ultima = _norm(filas[0][-1])
    return primera.startswith("campo") and "conf" in ultima


def leer(ruta: str | Path) -> DocumentoTDD2:
    ruta = Path(ruta)
    d = docx.Document(ruta)
    doc = DocumentoTDD2(ruta=ruta)

    seccion_actual = ""
    titulo_actual = ""
    indice_tabla = 0

    for bloque in _iter_bloques(d):
        if isinstance(bloque, Paragraph):
            estilo = (bloque.style.name or "") if bloque.style else ""
            texto = re.sub(r"\s+", " ", bloque.text or "").strip()
            if not texto:
                continue
            if estilo.startswith("Heading") or estilo.startswith("Título"):
                m = _RE_TITULO_SECCION.match(texto)
                if m:
                    seccion_actual = m.group(1)
                    titulo_actual = texto
                elif _norm(texto).startswith("anexo"):
                    seccion_actual = texto.split(".")[0].strip()
                    titulo_actual = texto
            continue

        # Es una tabla.
        indice_tabla += 1
        filas = [[c.text.strip() for c in r.cells] for r in bloque.rows]
        if not filas:
            continue

        # La tablita de cabecera (Documento/Version/Proposito...) y la de
        # "Nivel de confianza de la informacion" (Codigo/Nivel/Criterio) no
        # son campos de un aplicativo: se saltan porque no calzan el patron.
        if not _es_tabla_de_campos(filas):
            continue

        for ifi, f in enumerate(filas[1:], start=1):
            campo = re.sub(r"\s+", " ", f[0]).strip()
            if not campo:
                continue
            valor = re.sub(r"\s+", " ", " ".join(f[1:-1])).strip() if len(f) > 2 else ""
            conf_txt = f[-1] if len(f) > 1 else ""
            m = _RE_CONFIANZA.search(conf_txt)
            confianza = f"C{m.group(1)}" if m else ""
            doc.campos.append(CampoTDD2(
                seccion=seccion_actual or f"tabla{indice_tabla}",
                seccion_titulo=titulo_actual or f"Tabla {indice_tabla}",
                campo=campo, valor=valor, confianza=confianza,
                tabla_indice=indice_tabla, fila_indice=ifi, ncols=len(f)))

            # De la seccion 0.1 sale la identificacion del aplicativo.
            nc = _norm(campo)
            if nc.startswith("id-habilitador") or nc.startswith("id habilitador"):
                if not _texto_vacio(valor):
                    doc.id_habilitador = re.sub(r"\s*·.*$", "", valor).strip()
            elif nc.startswith("nombre del aplicativo"):
                if not _texto_vacio(valor):
                    doc.nombre_aplicativo = valor

    return doc


def es_documento_tdd_nivel2(ruta: str | Path) -> bool:
    """¿Este archivo ES un TDD Nivel 2? Se reconoce por su estructura -- la
    frase de la plantilla y la escala C1-C4 -- no por el nombre."""
    ruta = Path(ruta)
    if ruta.suffix.lower() != ".docx":
        return False
    try:
        d = docx.Document(ruta)
    except Exception:
        return False
    texto = _norm(" ".join(p.text for p in d.paragraphs[:25]))
    if "gobierno de aplicativos" not in texto and "nivel 2" not in texto:
        return False
    # Y que de verdad traiga la escala de confianza, no solo el titulo.
    vistas = {_norm(c.text) for t in d.tables[:3] for r in t.rows[:6] for c in r.cells}
    return any(v in ("c1", "c2", "c3", "c4") for v in vistas) or \
        any(re.search(r"\bc1\b.*confirmado", v) for v in vistas)


def es_plantilla_en_blanco(doc: DocumentoTDD2) -> bool:
    """La plantilla vacia (`TDD_GobiernoAplicativosNivel_2.docx`) no es el TDD
    de ningun aplicativo real -- no tiene ID-habilitador ni nombre, y todos
    sus campos estan vacios. Sirve para no sembrarla por error junto con los
    67 TDD reales."""
    return not doc.id_habilitador and not doc.nombre_aplicativo


def _nombre_desde_archivo(ruta: Path) -> str:
    """`TDD_PortalRegistroPago_Nivel_2.docx` -> `PortalRegistroPago`."""
    base = ruta.stem
    base = re.sub(r"^tdd[_\s]*", "", base, flags=re.I)
    base = re.sub(r"[_\s]*nivel[_\s]*2$", "", base, flags=re.I)
    return base


def identificar(doc: DocumentoTDD2, libro) -> "_identificacion.Amarre":
    """Amarra un TDD Nivel 2 a un aplicativo del APM. En orden de fuerza:

    1. El ID-habilitador declarado en la seccion 0.1 -- es exacto.
    2. El nombre del archivo, emparejado de forma floja (sin acentos, sin
       importar mayusculas/espacios/guiones) contra el nombre real del
       aplicativo -- es el respaldo mas fuerte que hay, porque estos 67
       archivos ya vinieron nombrados uno por aplicativo.
    3. Que el nombre de algun aplicativo aparezca dentro del texto de
       "Nombre del aplicativo" (una descripcion larga, no el nombre pelado).
    """
    if doc.id_habilitador:
        app = libro.aplicacion(id_habilitador=doc.id_habilitador)
        if app:
            return _identificacion.Amarre(
                True, app.numero, app.id_habilitador, app.nombre,
                "id_habilitador", f"declara ID-habilitador {doc.id_habilitador}")

    slug_archivo = _slug(_nombre_desde_archivo(doc.ruta))
    if slug_archivo:
        # Primero se busca una igualdad EXACTA de slug -- "pase" (el archivo)
        # no debe perder contra "formateadordesemblanzaspase" (que tambien lo
        # contiene) solo por ser mas largo. Un nombre corto como "SEA"
        # tambien podria "contenerse" por accidente dentro de otro ("buSEArch
        # Bar"), asi que la contencion solo se intenta como segundo recurso,
        # y con un largo minimo mas alto que el de una igualdad exacta.
        exactos = [a for a in libro.aplicaciones if _slug(a.nombre) == slug_archivo]
        if len(exactos) == 1:
            app = exactos[0]
            return _identificacion.Amarre(
                True, app.numero, app.id_habilitador, app.nombre,
                "nombre_en_texto", f"el nombre del archivo coincide con «{app.nombre}»")

        if not exactos:
            LARGO_MINIMO_CONTENCION = 6
            mejor, mejor_largo = None, -1
            for app in libro.aplicaciones:
                slug_app = _slug(app.nombre)
                if len(slug_app) < LARGO_MINIMO_CONTENCION or len(slug_archivo) < LARGO_MINIMO_CONTENCION:
                    continue
                if slug_app in slug_archivo or slug_archivo in slug_app:
                    if len(slug_app) > mejor_largo:
                        mejor, mejor_largo = app, len(slug_app)
            if mejor:
                return _identificacion.Amarre(
                    True, mejor.numero, mejor.id_habilitador, mejor.nombre,
                    "nombre_en_texto", f"el nombre del archivo coincide con «{mejor.nombre}»")

    if doc.nombre_aplicativo:
        n_plano = _norm(doc.nombre_aplicativo)
        golpes = [app for app in libro.aplicaciones
                  if _norm(app.nombre) and len(_norm(app.nombre)) >= 3
                  and _norm(app.nombre) in n_plano]
        if len(golpes) == 1:
            app = golpes[0]
            return _identificacion.Amarre(
                True, app.numero, app.id_habilitador, app.nombre,
                "nombre_en_texto", f"aparece «{app.nombre}» en el nombre del aplicativo")

    return _identificacion.Amarre(False)


# ---------------------------------------------------------------------------
# Comparacion contra la referencia sembrada
# ---------------------------------------------------------------------------
# Mismo motor de decisiones que conciliacion.py (Propuesta/Candidato, mismos
# estados COINCIDE/PROPUESTO/CONFLICTO_APM) -- pero aqui el "APM actual" es la
# referencia sembrada (el TDD Nivel 2 ya revisado y adoptado de este
# aplicativo) y el "documento fuente" es el TDD Nivel 2 que se acaba de subir.
# Nunca al reves: la referencia nunca se pisa sola, y solo se propone lo que
# el documento subido trae -- nada se llena desde el APM ni desde una version
# anterior del TDD, por la regla del proyecto.

def conciliar_tdd2(referencia: DocumentoTDD2 | None, nuevo: DocumentoTDD2
                   ) -> list[_conciliacion.Propuesta]:
    """Una propuesta por cada campo del TDD Nivel 2 subido que traiga un dato.

    Si todavia no hay referencia sembrada para este aplicativo, TODO campo con
    dato sale como `propuesto`: es la primera siembra, no hay con que
    comparar todavia.
    """
    salida: list[_conciliacion.Propuesta] = []
    nombre_doc = nuevo.ruta.name

    for campo in nuevo.campos:
        if campo.vacio:
            continue  # nada que proponer: el documento no trae dato aqui

        candidato = _conciliacion.Candidato(
            valor=campo.valor, documento=nombre_doc,
            evidencia=f"confianza declarada: {campo.confianza}" if campo.confianza else "")

        ref_campo = referencia.campo(campo.llave) if referencia else None
        actual_txt = ref_campo.valor if (ref_campo and not ref_campo.vacio) else ""

        if not actual_txt:
            estado = _conciliacion.PROPUESTO
            motivo = "" if referencia else "primera siembra de este aplicativo"
        elif _conciliacion._iguales(actual_txt, campo.valor):
            estado = _conciliacion.COINCIDE
            motivo = "el documento confirma lo que ya tenía la referencia"
        else:
            estado = _conciliacion.CONFLICTO_APM
            motivo = "la referencia y el documento no dicen lo mismo"

        salida.append(_conciliacion.Propuesta(
            clave=campo.llave, grupo=campo.seccion_titulo or campo.seccion,
            etiqueta=campo.campo, valor_actual=actual_txt, estado=estado,
            candidatos=[candidato], motivo=motivo,
            nota=f"confianza declarada: {campo.confianza}" if campo.confianza else ""))

    return salida


def _escribir_celda(celda, valor: str) -> None:
    """Conserva el estilo del parrafo que ya estaba, igual que
    tdd.escribir_version -- si no, el texto nuevo sale con la fuente por
    omision y el documento queda parchado a la vista."""
    parrafo = celda.paragraphs[0]
    if parrafo.runs:
        parrafo.runs[0].text = valor
        for r in parrafo.runs[1:]:
            r.text = ""
    else:
        parrafo.add_run(valor)


def escribir_valores(ruta_origen: str | Path, cambios: list[dict],
                     destino: Path | str) -> dict:
    """Copia el TDD Nivel 2 de referencia y escribe SOLO los campos que una
    persona decidio -- igual que `tdd.escribir_version`: se copia el archivo
    entero con shutil para no perder estilos ni imagenes, y una celda que ya
    trae texto solo se reemplaza si el cambio viene marcado `sobrescribir`,
    que lo pone la decision de la persona sobre un conflicto, nunca el
    automatismo.

    `cambios` = [{tabla, fila, valor, confianza, sobrescribir}], con los
    mismos indices 1-based de `CampoTDD2` (tabla_indice, fila_indice).

    Solo se puede escribir en filas de 3 columnas (Campo | Informacion |
    Confianza): las tablas mas anchas (Usuarios, Integraciones...) traen mas
    de una columna de dato y se reportan como "hay que editarlas a mano" en
    vez de adivinar en cual columna va el valor -- adivinar ahi produce un
    documento que se ve lleno y dice mentiras, igual que advierte tdd.py
    sobre `mapear_apm_a_tdd`.
    """
    ruta_origen, destino = Path(ruta_origen), Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ruta_origen, destino)

    d = docx.Document(destino)
    aplicados, rechazados = [], []

    for cambio in cambios:
        try:
            it = int(cambio["tabla"]) - 1
            ifi = int(cambio["fila"])
            valor = str(cambio.get("valor", ""))
        except (KeyError, ValueError, TypeError):
            rechazados.append({**cambio, "motivo": "cambio mal formado"})
            continue

        if not (0 <= it < len(d.tables)):
            rechazados.append({**cambio, "motivo": "esa tabla no existe en el documento"})
            continue
        tabla = d.tables[it]
        if not (0 <= ifi < len(tabla.rows)):
            rechazados.append({**cambio, "motivo": "esa fila no existe en la tabla"})
            continue

        fila = tabla.rows[ifi]
        if len(fila.cells) != 3:
            rechazados.append({**cambio, "motivo":
                               "esta tabla tiene más de una columna de dato; "
                               "hay que editarla a mano en el documento"})
            continue

        celda_valor = fila.cells[1]
        anterior = celda_valor.text.strip()
        if not _texto_vacio(anterior):
            if not cambio.get("sobrescribir"):
                rechazados.append({**cambio, "motivo":
                                   f"la celda ya dice «{anterior[:50]}»; "
                                   "no se sobrescribe sin decisión explícita"})
                continue
            if _norm(anterior) == _norm(valor):
                continue    # ya dice lo mismo: no es un cambio

        _escribir_celda(celda_valor, valor)

        confianza = cambio.get("confianza")
        if confianza:
            _escribir_celda(fila.cells[2], str(confianza))

        aplicados.append({**cambio, "anterior": anterior})

    d.save(destino)
    return {"destino": str(destino), "aplicados": aplicados, "rechazados": rechazados}


# ---------------------------------------------------------------------------
# Siguiente version (para las copias que guarda "Comparar TDD Nivel 2")
# ---------------------------------------------------------------------------

def siguiente_version(ruta: str | Path, carpeta_destino: Path | None = None) -> Path:
    ruta = Path(ruta)
    carpeta = Path(carpeta_destino) if carpeta_destino else ruta.parent
    m = re.search(r"_V(\d+)_Nivel_2$", ruta.stem, re.I)
    if m:
        base = ruta.stem.replace(m.group(0), f"_V{int(m.group(1)) + 1}_Nivel_2", 1)
    else:
        base = f"{ruta.stem}_V2"
    destino = carpeta / f"{base}{ruta.suffix}"
    n = 2
    while destino.exists():
        destino = carpeta / f"{base}_{n}{ruta.suffix}"
        n += 1
    return destino
