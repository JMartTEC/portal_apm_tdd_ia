"""
apm.py
------
Lee la hoja Inventory del libro de APM y la vuelve un modelo con el que se puede
trabajar sin adivinar nada.

Por que este archivo NO trae una lista de campos escrita a mano: porque la que
manda es la del libro. Los campos (hoy 45), sus grupos, cuales se capturan y
cuales se calculan, y los valores validos de cada lista desplegable, todo sale
del propio .xlsx al momento de abrirlo. El dia que el Tec agregue una columna o
cambie un catalogo, la aplicacion lo aprende sola. Una copia nuestra de esa
lista se desincronizaria en la primera version del libro y nadie se daria cuenta.

Las tres reglas de escritura, leidas del formato de la hoja y no inventadas:

  1. Una columna con FORMULA no se escribe nunca. `Disposicion TIME` se calcula
     de Puntaje VN x Puntaje ST; escribirla rompe el modelo TIME entero y el
     Dashboard que cuelga de el.
  2. Una columna con relleno BLANCO tampoco: es calculada, no de captura. Asi
     esta `Costo Total Anual`.
  3. Lo demas si. El README del libro lo dice con todas sus letras: "Relleno
     amarillo = celda de entrada, dato a capturar".

Y un detalle que parece menor y no lo es: la hoja tiene DOS columnas llamadas
`Criticidad`, una en Calificacion APM y otra en Valores TEC. Por eso la clave de
cada columna lleva el grupo adentro. Sin eso, un llenado automatico las confunde
y escribe la criticidad tecnica encima de la institucional, sin que nadie lo note
hasta que el reporte sale mal.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

HOJA_INVENTORY = "Inventory"
HOJA_LOOKUPS = "Lookups"

# Como el libro escribe "no hay dato". No es lo mismo que una celda vacia: el
# README dice que significa "se reviso toda la documentacion disponible y no se
# encontro". Es una afirmacion de alguien, y se respeta como tal.
SIN_INFORMACION = "Sin información"

_VACIOS = {"", "-", "--", "n/a", "na", "n.a.", "nd", "n/d", "sin informacion",
           "sin información", "por definir", "tbd", "pendiente"}

BLANCO = "FFFFFF"


def _norm(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


def _clave(grupo: str, etiqueta: str) -> str:
    """Clave estable que incluye el grupo. Ver la nota de las dos `Criticidad`."""
    crudo = f"{grupo}_{etiqueta}"
    crudo = unicodedata.normalize("NFD", crudo)
    crudo = "".join(c for c in crudo if unicodedata.category(c) != "Mn")
    crudo = re.sub(r"[^a-zA-Z0-9]+", "_", crudo).strip("_").lower()
    return re.sub(r"_+", "_", crudo)


def es_vacio(valor) -> bool:
    return _norm(valor) in _VACIOS


def es_sin_informacion(valor) -> bool:
    return _norm(valor) == _norm(SIN_INFORMACION)


@dataclass
class Columna:
    indice: int                 # 1-based, como lo pide openpyxl
    grupo: str
    etiqueta: str
    clave: str
    escribible: bool
    motivo: str = ""            # por que no se puede escribir, si aplica
    nota: str = ""              # advertencia para quien revisa
    lookup: list[str] = field(default_factory=list)

    @property
    def tiene_lookup(self) -> bool:
        return bool(self.lookup)


@dataclass
class Aplicacion:
    fila: int                   # renglon en la hoja
    numero: str                 # columna '#'
    id_habilitador: str
    nombre: str
    valores: dict               # clave de columna -> valor tal cual esta hoy

    def vacios(self, columnas: list[Columna]) -> list[str]:
        return [c.clave for c in columnas
                if c.escribible and es_vacio(self.valores.get(c.clave))]


class LibroAPM:
    """Un libro de APM abierto. No modifica el archivo de origen jamas."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        if not self.ruta.exists():
            raise FileNotFoundError(f"No existe el libro APM: {self.ruta}")

        # Dos pasadas: una con los valores ya calculados y otra con las formulas
        # en crudo. Ninguna sola da las dos cosas, y hacen falta las dos: los
        # valores para mostrar, las formulas para saber que NO se toca.
        self._wb_valores = openpyxl.load_workbook(self.ruta, data_only=True)
        self._wb_formulas = openpyxl.load_workbook(self.ruta)

        if HOJA_INVENTORY not in self._wb_valores.sheetnames:
            raise ValueError(
                f"El archivo no tiene hoja '{HOJA_INVENTORY}'. "
                "¿Seguro que es el libro de APM?")

        self.fila_encabezados = self._localizar_encabezados()
        self.fila_datos = self.fila_encabezados + 1
        self.columnas = self._leer_columnas()
        self.por_clave = {c.clave: c for c in self.columnas}
        self.aplicaciones = self._leer_aplicaciones()

    # -- estructura ---------------------------------------------------------

    def _localizar_encabezados(self) -> int:
        """La fila de encabezados es la que trae 'ID Habilitador'. Se busca en
        vez de fijarla en 3 porque el libro ya cambio de forma entre versiones."""
        ws = self._wb_valores[HOJA_INVENTORY]
        for fila in range(1, min(ws.max_row, 12) + 1):
            textos = [_norm(c.value) for c in ws[fila]]
            if "id habilitador" in textos:
                return fila
        raise ValueError("No se encontro la fila de encabezados en Inventory "
                         "(se busco una fila con 'ID Habilitador').")

    def _leer_columnas(self) -> list[Columna]:
        wsv = self._wb_valores[HOJA_INVENTORY]
        wsf = self._wb_formulas[HOJA_INVENTORY]
        fila_grupos = self.fila_encabezados - 1
        columnas: list[Columna] = []
        grupo = ""

        for i in range(1, wsv.max_column + 1):
            etiqueta = wsv.cell(self.fila_encabezados, i).value
            if not etiqueta:
                continue
            etiqueta = re.sub(r"\s+", " ", str(etiqueta)).strip()

            # Los grupos van en la fila de arriba, en celdas combinadas: solo la
            # primera columna del grupo trae el texto. Se arrastra el ultimo.
            if fila_grupos >= 1:
                crudo = wsv.cell(fila_grupos, i).value
                if crudo:
                    grupo = re.sub(r"\s+", " ", str(crudo)).strip()

            # Regla 1: formula en cualquier renglon de datos -> intocable.
            tiene_formula = any(
                str(wsf.cell(f, i).value or "").startswith("=")
                for f in range(self.fila_datos, min(wsf.max_row, self.fila_datos + 80) + 1))

            # Regla 2: relleno blanco -> calculada, tampoco es de captura.
            celda = wsf.cell(self.fila_datos, i)
            relleno = ""
            if celda.fill and celda.fill.patternType and celda.fill.start_color:
                relleno = str(celda.fill.start_color.rgb or "")[-6:].upper()

            if tiene_formula:
                escribible, motivo = False, "es una fórmula del libro"
            elif relleno == BLANCO:
                escribible, motivo = False, "es una celda calculada, no de captura"
            else:
                escribible, motivo = True, ""

            columnas.append(Columna(
                indice=i, grupo=grupo, etiqueta=etiqueta,
                clave=_clave(grupo, etiqueta),
                escribible=escribible, motivo=motivo,
            ))

        self._asignar_lookups(columnas, self._leer_lookups())
        return columnas

    def _leer_lookups(self) -> dict[str, list[str]]:
        """Los valores validos de cada lista desplegable, de la hoja Lookups.

        La fila de encabezados no es la 1: el libro deja la primera en blanco.
        Se busca la primera fila con dos o mas celdas con texto, en vez de
        fijarla, porque ese margen decorativo cambia entre versiones."""
        if HOJA_LOOKUPS not in self._wb_valores.sheetnames:
            return {}
        ws = self._wb_valores[HOJA_LOOKUPS]
        filas = list(ws.iter_rows(values_only=True))

        inicio = next((i for i, f in enumerate(filas)
                       if sum(1 for c in f if c not in (None, "")) >= 2), None)
        if inicio is None:
            return {}

        salida: dict[str, list[str]] = {}
        for i, encabezado in enumerate(filas[inicio]):
            if not encabezado:
                continue
            valores = [str(f[i]).strip() for f in filas[inicio + 1:]
                       if i < len(f) and f[i] not in (None, "")]
            if valores:
                salida[_norm(encabezado)] = valores
        return salida

    def _asignar_lookups(self, columnas: list[Columna],
                         lookups: dict[str, list[str]]) -> None:
        """Amarra cada lista a su columna, con cuidado cuando el nombre se repite.

        `Criticidad` es el caso que obliga a esto: existe en Calificacion APM
        (Mission Critical / High / Medium / Low) y en Valores TEC, donde el
        README describe una escala 1-5 completamente distinta. Pegarle la misma
        lista a las dos seria meter el catalogo equivocado en una de ellas.

        Asi que cuando una etiqueta esta repetida, la lista solo se asigna a la
        columna cuyos datos actuales son compatibles con ella. La otra se queda
        sin catalogo y con una nota, para que se resuelva mirando el libro y no
        adivinando aqui.
        """
        ws = self._wb_valores[HOJA_INVENTORY]
        repetidas = {e for e in (_norm(c.etiqueta) for c in columnas)
                     if [_norm(x.etiqueta) for x in columnas].count(e) > 1}

        for col in columnas:
            lista = lookups.get(_norm(col.etiqueta))
            if not lista:
                continue
            if _norm(col.etiqueta) not in repetidas:
                col.lookup = lista
                continue

            permitidos = {_norm(v) for v in lista}
            actuales = {_norm(ws.cell(f, col.indice).value)
                        for f in range(self.fila_datos, ws.max_row + 1)}
            actuales = {v for v in actuales if v and v not in _VACIOS}

            if actuales and actuales <= permitidos:
                col.lookup = lista
            elif actuales:
                muestra = ", ".join(sorted(actuales)[:6])
                col.nota = (
                    f"conflicto de catálogo: hay más de una columna «{col.etiqueta}» y "
                    f"ésta contiene «{muestra}», que no son los valores del catálogo "
                    f"de ese nombre ({', '.join(lista[:4])}…). No se aplica ningún "
                    "catálogo aquí; hay que aclarar cuál manda antes de escribirla.")
            else:
                col.nota = (
                    f"hay más de una columna «{col.etiqueta}» y ésta está vacía, así que "
                    "no se puede deducir qué catálogo le toca. Se deja sin catálogo.")

    def _leer_aplicaciones(self) -> list[Aplicacion]:
        ws = self._wb_valores[HOJA_INVENTORY]
        col_num = self._col_por_etiqueta("#")
        col_id = self._col_por_etiqueta("ID Habilitador")
        # La primera columna del grupo de identidad es el nombre del habilitador.
        col_nombre = (self._col_por_etiqueta("Habilitador (Aplicación)")
                      or self._col_por_etiqueta("Habilitador"))

        apps: list[Aplicacion] = []
        for fila in range(self.fila_datos, ws.max_row + 1):
            nombre = ws.cell(fila, col_nombre.indice).value if col_nombre else None
            if not nombre or not str(nombre).strip():
                continue
            valores = {c.clave: ws.cell(fila, c.indice).value for c in self.columnas}
            apps.append(Aplicacion(
                fila=fila,
                numero=str(ws.cell(fila, col_num.indice).value or "").strip() if col_num else "",
                id_habilitador=str(ws.cell(fila, col_id.indice).value or "").strip() if col_id else "",
                nombre=re.sub(r"\s+", " ", str(nombre)).strip(),
                valores=valores,
            ))
        return apps

    def _col_por_etiqueta(self, etiqueta: str) -> Columna | None:
        objetivo = _norm(etiqueta)
        for c in self.columnas:
            if _norm(c.etiqueta) == objetivo:
                return c
        return None

    # -- consulta -----------------------------------------------------------

    @property
    def escribibles(self) -> list[Columna]:
        return [c for c in self.columnas if c.escribible]

    @property
    def bloqueadas(self) -> list[Columna]:
        return [c for c in self.columnas if not c.escribible]

    def aplicacion(self, numero: str = "", id_habilitador: str = "",
                   nombre: str = "") -> Aplicacion | None:
        """Busca por identificador antes que por nombre: el numero y el ID son
        exactos, el nombre se escribe de diez formas distintas."""
        if numero:
            # Los TDD escriben el numero con cero a la izquierda ("APM #03") y la
            # hoja no ("3"). Se comparan como numeros cuando ambos lo son.
            objetivo = str(numero).strip()
            for a in self.aplicaciones:
                if a.numero == objetivo:
                    return a
            if objetivo.isdigit():
                for a in self.aplicaciones:
                    if a.numero.isdigit() and int(a.numero) == int(objetivo):
                        return a
        if id_habilitador and not es_vacio(id_habilitador):
            objetivo = _norm(id_habilitador)
            for a in self.aplicaciones:
                if _norm(a.id_habilitador) == objetivo:
                    return a
        if nombre:
            objetivo = _norm(nombre)
            for a in self.aplicaciones:
                if _norm(a.nombre) == objetivo:
                    return a
        return None

    def valida_para(self, clave: str, valor: str) -> tuple[bool, str]:
        """Si la columna tiene lista de valores, el valor tiene que ser uno de
        ellos. Un texto libre en una columna con validacion revienta el
        desplegable de Excel y ensucia el Dashboard."""
        col = self.por_clave.get(clave)
        if not col:
            return False, "esa columna no existe en el libro"
        if not col.escribible:
            return False, col.motivo
        if not col.lookup or es_vacio(valor):
            return True, ""
        objetivo = _norm(valor)
        for permitido in col.lookup:
            if _norm(permitido) == objetivo:
                return True, ""
        return False, ("valor fuera del catálogo. Permitidos: "
                       + ", ".join(col.lookup))

    def resumen(self) -> dict:
        return {
            "ruta": str(self.ruta),
            "aplicaciones": len(self.aplicaciones),
            "columnas": len(self.columnas),
            "escribibles": len(self.escribibles),
            "bloqueadas": [{"etiqueta": c.etiqueta, "motivo": c.motivo}
                           for c in self.bloqueadas],
            "con_catalogo": [c.etiqueta for c in self.columnas if c.tiene_lookup],
            "con_nota": [{"etiqueta": c.etiqueta, "grupo": c.grupo, "nota": c.nota}
                         for c in self.columnas if c.nota],
            "grupos": list(dict.fromkeys(c.grupo for c in self.columnas if c.grupo)),
        }

    # -- escritura ----------------------------------------------------------

    def escribir_version(self, cambios: list[dict], destino: Path | str) -> dict:
        """Escribe los cambios YA VALIDADOS en una copia nueva del libro.

        `cambios` = [{fila, clave, valor}]. El archivo de origen no se abre en
        modo escritura ni una sola vez: se carga, se modifica en memoria y se
        guarda con otro nombre. La version anterior queda intacta en su lugar,
        que es lo que permite comparar y, si algo salio mal, tirar la nueva.
        """
        destino = Path(destino)
        wb = openpyxl.load_workbook(self.ruta)     # con formulas, para no perderlas
        ws = wb[HOJA_INVENTORY]

        aplicados, rechazados = [], []
        for cambio in cambios:
            clave, valor = cambio.get("clave", ""), cambio.get("valor", "")
            fila = int(cambio.get("fila", 0))
            col = self.por_clave.get(clave)

            if not col:
                rechazados.append({**cambio, "motivo": "columna desconocida"})
                continue
            if not col.escribible:
                rechazados.append({**cambio, "motivo": col.motivo})
                continue
            ok, motivo = self.valida_para(clave, valor)
            if not ok:
                rechazados.append({**cambio, "motivo": motivo})
                continue
            if fila < self.fila_datos:
                rechazados.append({**cambio, "motivo": "fila fuera del área de datos"})
                continue

            ws.cell(fila, col.indice).value = valor
            aplicados.append({**cambio, "columna": col.etiqueta, "grupo": col.grupo})

        destino.parent.mkdir(parents=True, exist_ok=True)
        wb.save(destino)
        return {"destino": str(destino),
                "aplicados": aplicados, "rechazados": rechazados}


def es_libro_apm(ruta: str | Path) -> bool:
    """¿Este archivo ES el APM? Se usa para NO tragarselo como documento fuente:
    el APM es destino, no materia prima."""
    ruta = Path(ruta)
    if ruta.suffix.lower() not in (".xlsx", ".xlsm"):
        return False
    try:
        wb = openpyxl.load_workbook(ruta, read_only=True)
        hojas = {_norm(h) for h in wb.sheetnames}
        wb.close()
        return _norm(HOJA_INVENTORY) in hojas
    except Exception:
        return False


def siguiente_version(ruta: str | Path, carpeta_destino: str | Path | None = None) -> Path:
    """`APM_Portfolio_Inventory_E1.xlsx` -> `..._v19.xlsx`, y si ya existe, v20.
    Nunca devuelve un nombre que ya este ocupado: no se pisa una version.

    `carpeta_destino`, si se da, es donde se escribe la version nueva -- separada
    del original a proposito, para que las versiones no se mezclen con la carpeta
    de origen del usuario. El original nunca se toca de todos modos."""
    ruta = Path(ruta)
    carpeta = Path(carpeta_destino) if carpeta_destino else ruta.parent
    carpeta.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"_v\d+$", "", ruta.stem)
    n = 19
    m = re.search(r"_v(\d+)$", ruta.stem)
    if m:
        n = int(m.group(1)) + 1
    destino = carpeta / f"{base}_v{n}{ruta.suffix}"
    while destino.exists():
        n += 1
        destino = carpeta / f"{base}_v{n}{ruta.suffix}"
    return destino
