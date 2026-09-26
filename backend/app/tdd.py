"""
tdd.py
------
Lee un Documento de Diseno Tecnico, dice a que aplicativo pertenece, reporta que
le falta, y escribe una version nueva llenada desde el APM.

Lo que hace que esto funcione sin adivinar: **el TDD declara su propio aplicativo**.
La tabla de identificacion trae una celda como `APM #3 / ID Habilitador
0606-HTI-001-TRXC`. Eso es una llave exacta contra la hoja Inventory. El nombre
del archivo queda solo de respaldo, para los TDD viejos que todavia traen el
texto de instrucciones de la plantilla en vez del dato.

Direccion del llenado, y no se negocia: **del APM hacia el TDD, nunca al reves.**
El APM es el registro autoritativo del portafolio. Un TDD es un documento de
trabajo de un proyecto: puede estar a medias, puede tener un dato viejo, y puede
contradecir al inventario. Dejar que escriba en el APM seria dejar que el caso
particular reescriba el registro general.

Y sobre el contenido que el TDD YA tiene: se respeta. Solo se llenan los huecos.
Cuando el TDD dice una cosa y el APM dice otra, eso NO se resuelve aqui: se
levanta como conflicto para que lo decida una persona.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import docx

# Como los TDD escriben "no hay dato". Igual que el "Sin informacion" del APM:
# es una afirmacion, no un vacio.
_VACIOS = {
    "", "-", "--", "n/a", "na", "n.a.", "nd", "n/d", "no aplica", "ninguno",
    "por definir", "tbd", "pendiente", "sin informacion", "sin información",
}
_PATRON_NO_DOCUMENTADO = re.compile(r"^\s*no\s+(documentado|especificado|definido)", re.I)

# El texto de instrucciones que la plantilla trae de fabrica. Si una celda sigue
# diciendo esto, esta VACIA aunque tenga letras: es el instructivo, no el dato.
_INSTRUCTIVOS = (
    "nombre y numeracion de la aplicacion", "pega aqui", "pegar aqui",
    "captura los resultados", "declara los componentes", "muestra la solucion",
    "marca los requerimientos", "si el proyecto", "identificador del system",
    "tiempo objetivo de recuperacion", "describe ", "indica ",
)


def _norm(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def celda_vacia(texto: str) -> bool:
    """Vacia de verdad, o vacia de facto: instructivo, guion, o 'no documentado'."""
    n = _norm(texto)
    if n in _VACIOS or len(n) < 2:
        return True
    if _PATRON_NO_DOCUMENTADO.match(n):
        return True
    return any(n.startswith(i) for i in _INSTRUCTIVOS)


@dataclass
class Tabla:
    indice: int                 # 1-based dentro del documento
    titulo: str                 # encabezado de la primera fila, para reconocerla
    filas: int
    columnas: int
    celdas_totales: int
    celdas_llenas: int

    @property
    def completitud(self) -> int:
        return round(self.celdas_llenas * 100 / self.celdas_totales) if self.celdas_totales else 0


@dataclass
class DocumentoTDD:
    ruta: Path
    numero_apm: str = ""
    id_habilitador: str = ""
    nombre_proyecto: str = ""
    nombre_archivo_pista: str = ""
    tablas: list[Tabla] = field(default_factory=list)

    @property
    def total_tablas(self) -> int:
        return len(self.tablas)

    @property
    def celdas_llenas(self) -> int:
        return sum(t.celdas_llenas for t in self.tablas)

    @property
    def celdas_totales(self) -> int:
        return sum(t.celdas_totales for t in self.tablas)

    @property
    def completitud(self) -> int:
        return round(self.celdas_llenas * 100 / self.celdas_totales) if self.celdas_totales else 0

    @property
    def identificado(self) -> bool:
        return bool(self.numero_apm or (self.id_habilitador and not celda_vacia(self.id_habilitador)))

    def faltantes(self) -> list[dict]:
        """Las tablas con huecos, de la mas vacia a la mas llena. Es el reporte
        de 'que le falta a este TDD'."""
        return sorted(
            ({"tabla": t.indice, "titulo": t.titulo, "completitud": t.completitud,
              "huecos": t.celdas_totales - t.celdas_llenas}
             for t in self.tablas if t.celdas_llenas < t.celdas_totales),
            key=lambda x: x["completitud"])


# Patron del dato que identifica al aplicativo dentro del documento.
_RE_APM = re.compile(r"apm\s*#?\s*(\d+)", re.I)
_RE_IDH = re.compile(r"id\s*habilitador[:\s]*([0-9]{3,5}-[A-Za-z]{2,4}-[0-9]{3}-[A-Za-z]{3,4})", re.I)
_RE_IDH_SUELTO = re.compile(r"\b([0-9]{3,5}-[A-Za-z]{2,4}-[0-9]{3}-[A-Za-z]{3,4})\b")


def leer(ruta: str | Path) -> DocumentoTDD:
    ruta = Path(ruta)
    d = docx.Document(ruta)
    doc = DocumentoTDD(ruta=ruta, nombre_archivo_pista=_pista_de_nombre(ruta))

    for i, t in enumerate(d.tables, start=1):
        filas = [[c.text.strip() for c in r.cells] for r in t.rows]
        if not filas:
            continue
        # El titulo util es el texto no vacio de la primera fila.
        titulo = next((c for c in filas[0] if c), f"tabla {i}")
        titulo = re.sub(r"\s+", " ", titulo)[:70]

        # La primera columna suele ser la etiqueta, no el dato: se cuenta el
        # llenado sobre las columnas de la derecha. En tablas de una sola
        # columna (los recuadros de diagramas) se cuenta esa.
        total = llenas = 0
        for f in filas:
            objetivo = f[1:] if len(f) > 1 else f
            for celda in objetivo:
                total += 1
                if not celda_vacia(celda):
                    llenas += 1

        doc.tablas.append(Tabla(indice=i, titulo=titulo, filas=len(filas),
                                columnas=len(filas[0]), celdas_totales=total,
                                celdas_llenas=llenas))

        # Identificacion: se busca en toda la tabla, no solo en una celda fija,
        # porque la plantilla movio esa tabla de lugar entre versiones.
        for f in filas:
            for celda in f:
                if not doc.numero_apm:
                    m = _RE_APM.search(celda)
                    if m:
                        doc.numero_apm = m.group(1)
                if not doc.id_habilitador:
                    m = _RE_IDH.search(celda) or _RE_IDH_SUELTO.search(celda)
                    if m:
                        doc.id_habilitador = m.group(1)
            if f and _norm(f[0]).startswith("nombre del proyecto") and len(f) > 1:
                if not celda_vacia(f[1]):
                    doc.nombre_proyecto = re.sub(r"\s+", " ", f[1])[:120]

    return doc


def celdas_etiquetadas(ruta: str | Path) -> list[dict]:
    """Las celdas del TDD que son «etiqueta -> valor», con sus coordenadas.

    Solo se devuelven las de tablas donde la primera columna es claramente una
    etiqueta (texto corto, sin ser un encabezado de tabla ancha). Es lo que el
    llenado desde el APM puede tocar con seguridad: una celda bajo un
    encabezado de siete columnas no significa lo mismo que su titulo, y meterle
    ahi un valor suelto llena el documento de basura bien formateada.
    """
    d = docx.Document(Path(ruta))
    salida = []
    for it, t in enumerate(d.tables, start=1):
        filas = [[c.text.strip() for c in r.cells] for r in t.rows]
        if not filas:
            continue
        # Tablas anchas: son matrices, no fichas. Se saltan.
        if len(filas[0]) > 4:
            continue
        for ifi, f in enumerate(filas):
            if len(f) < 2:
                continue
            etiqueta = re.sub(r"\s+", " ", f[0]).strip()
            if not etiqueta or len(etiqueta) > 70:
                continue
            salida.append({"tabla": it, "fila": ifi, "columna": 1,
                           "etiqueta": etiqueta, "texto": f[1]})
    return salida


def _pista_de_nombre(ruta: Path) -> str:
    """`TDD_V3_Ticket DAP.docx` -> `Ticket DAP`. Solo es respaldo: si el
    documento declara su APM #, ese manda sobre cualquier nombre de archivo."""
    base = ruta.stem
    base = re.sub(r"^tdd[_\s]*(v\d+)?[_\s]*", "", base, flags=re.I)
    base = re.sub(r"^tec[_\s]*[_\s]*", "", base, flags=re.I)
    base = re.sub(r"[_\s]*(brayan|final|copia|v\d+)$", "", base, flags=re.I)
    return re.sub(r"[_]+", " ", base).strip()


def es_documento_tdd(ruta: str | Path) -> bool:
    """¿Este archivo ES un TDD? Se usa para NO tragarselo como documento fuente:
    un TDD es destino, no materia prima.

    Se reconoce por su estructura, no por el nombre: alguien puede renombrar el
    archivo, pero la tabla de identificacion con `APM (ID Habilitador)` y el
    encabezado de Diseno Tecnico son de la plantilla.
    """
    ruta = Path(ruta)
    if ruta.suffix.lower() != ".docx":
        return False
    try:
        d = docx.Document(ruta)
    except Exception:
        return False

    texto = _norm(" ".join(p.text for p in d.paragraphs[:40]))
    if "diseno tecnico" in texto or "diseño tecnico" in _norm(texto):
        return True
    for t in d.tables[:8]:
        for r in t.rows[:6]:
            for c in r.cells:
                n = _norm(c.text)
                if "apm" in n and "habilitador" in n:
                    return True
    return False


# ---------------------------------------------------------------------------
# Escritura de la version nueva
# ---------------------------------------------------------------------------

def siguiente_version(ruta: str | Path, carpeta_destino: Path | None = None) -> Path:
    """`TDD_V3_PASE.docx` -> `TDD_V4_PASE.docx`. Si ya existe, sigue subiendo.
    Nunca devuelve un nombre ocupado: no se pisa una version."""
    ruta = Path(ruta)
    carpeta = Path(carpeta_destino) if carpeta_destino else ruta.parent
    m = re.search(r"_V(\d+)_", ruta.stem, re.I)
    if m:
        base = ruta.stem.replace(m.group(0), f"_V{int(m.group(1)) + 1}_", 1)
    else:
        base = f"{ruta.stem}_V2"
    destino = carpeta / f"{base}{ruta.suffix}"
    n = 2
    while destino.exists():
        destino = carpeta / f"{base}_{n}{ruta.suffix}"
        n += 1
    return destino


def escribir_version(ruta_origen: str | Path, cambios: list[dict],
                     destino: Path | str) -> dict:
    """Copia el TDD y escribe en la copia SOLO las celdas aprobadas.

    `cambios` = [{tabla, fila, columna, valor}] con indices 1-based de tabla y
    0-based de fila/columna, tal como los devuelve `leer`.

    Se copia el archivo con shutil ANTES de abrirlo, en vez de reconstruirlo:
    un TDD trae imagenes, diagramas y estilos que valen mas que el texto, y
    regenerarlo los perderia. Asi el documento nuevo es el viejo con celdas
    cambiadas, y nada mas.

    Y una celda que ya tiene contenido NO se pisa: si llega un cambio para una
    celda escrita, se rechaza y se reporta. Sobrescribir el trabajo de alguien
    sin avisar es exactamente lo que no queremos.
    """
    ruta_origen, destino = Path(ruta_origen), Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ruta_origen, destino)

    d = docx.Document(destino)
    aplicados, rechazados = [], []

    for cambio in cambios:
        try:
            it = int(cambio["tabla"]) - 1
            ifi, ico = int(cambio["fila"]), int(cambio["columna"])
            valor = str(cambio.get("valor", ""))
        except (KeyError, ValueError, TypeError):
            rechazados.append({**cambio, "motivo": "cambio mal formado"})
            continue

        if not (0 <= it < len(d.tables)):
            rechazados.append({**cambio, "motivo": "esa tabla no existe en el documento"})
            continue
        tabla = d.tables[it]
        if not (0 <= ifi < len(tabla.rows)) or not (0 <= ico < len(tabla.rows[ifi].cells)):
            rechazados.append({**cambio, "motivo": "fila o columna fuera de la tabla"})
            continue

        celda = tabla.rows[ifi].cells[ico]
        anterior = celda.text.strip()
        if not celda_vacia(anterior):
            # Una celda escrita solo se reemplaza cuando una persona lo decidio
            # explicitamente sobre ese conflicto. `sobrescribir` no lo pone el
            # automatismo: lo pone la decision. Sin esa marca, el llenado
            # rellena huecos y nada mas.
            if not cambio.get("sobrescribir"):
                rechazados.append({**cambio, "motivo":
                                   f"la celda ya dice «{anterior[:50]}»; "
                                   "no se sobrescribe sin decisión explícita"})
                continue
            if _norm(anterior) == _norm(valor):
                continue    # ya dice lo mismo: no es un cambio

        # Se escribe conservando el estilo del parrafo que ya estaba, en vez de
        # borrar la celda: si no, el texto nuevo sale con la fuente por omision
        # y el documento queda parchado a la vista.
        parrafo = celda.paragraphs[0]
        if parrafo.runs:
            parrafo.runs[0].text = valor
            for r in parrafo.runs[1:]:
                r.text = ""
        else:
            parrafo.add_run(valor)
        aplicados.append({**cambio, "anterior": anterior})

    d.save(destino)
    return {"destino": str(destino), "aplicados": aplicados, "rechazados": rechazados}
