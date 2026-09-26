"""
almacen.py
----------
La base interna. Un archivo SQLite junto a la aplicacion.

Por que existe: hasta la v5 nada persistia. Cada corrida volvia a leer los mismos
documentos, a proponer los mismos campos y a preguntar los mismos conflictos que
alguien ya habia resuelto. Con 70 aplicativos eso no es una molestia, es que el
trabajo no se acumula.

Y lo que guarda no es "los documentos": es la LINEA BASE institucional.

    La base arranca con lo que YA dicen el APM y los TDD.

Ese es el punto entero. Un documento nuevo no se interpreta en el vacio: se
compara contra lo que el inventario y los diseños tecnicos ya afirman. Sin esa
referencia, cada escaneo empieza de cero y la aplicacion no puede distinguir
"esto es nuevo" de "esto ya lo sabiamos" ni de "esto contradice lo que hay".

Las tres cosas que se guardan, y para que sirve cada una:

  1. LINEA BASE   lo que dicen hoy el APM (68 aplicativos x 45 campos) y los TDD.
                  Es la referencia. Se vuelve a sembrar cuando cambia el libro.
  2. MEMORIA      que dijo cada documento leido, con la huella de su contenido.
                  El mismo archivo no se vuelve a leer aunque lo renombren.
  3. DECISIONES   que escogio una persona ante cada conflicto, y cuando.
                  Un conflicto resuelto no vuelve a preguntarse.

Sobre SQLite: es un archivo, no un servidor. Viene en la libreria estandar de
Python, asi que no agrega una sola dependencia ni algo que instalar en el equipo
del Tec. Y como la meta declarada es pasar esto a una API con base de verdad,
todo el acceso vive detras de las funciones de este modulo -- ninguna otra parte
del programa escribe SQL. Ese es el punto de costura: el dia que la base sea
Azure SQL, se reescribe este archivo y nada mas.

`exportar()` saca todo a JSON y a un CSV por tabla, para que la migracion sea
copiar y no un proyecto.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

NOMBRE_ARCHIVO = "almacen.db"
VERSION_ESQUEMA = 2

# El esquema. Se escribe entero aqui y se aplica con IF NOT EXISTS: al ser una
# POC que todavia cambia, es mas honesto releer el esquema completo en cada
# arranque que arrastrar migraciones a medias.
ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

-- ---------- 1. LINEA BASE: lo que dice el APM hoy ----------
CREATE TABLE IF NOT EXISTS aplicativos (
    numero          TEXT PRIMARY KEY,
    id_habilitador  TEXT,
    nombre          TEXT NOT NULL,
    fila            INTEGER,
    sembrado_en     TEXT NOT NULL,
    origen          TEXT NOT NULL          -- ruta del .xlsx del que salio
);
CREATE INDEX IF NOT EXISTS ix_apps_idh ON aplicativos(id_habilitador);
CREATE INDEX IF NOT EXISTS ix_apps_nombre ON aplicativos(nombre);

CREATE TABLE IF NOT EXISTS base_apm (
    numero      TEXT NOT NULL,
    clave       TEXT NOT NULL,
    grupo       TEXT,
    etiqueta    TEXT,
    valor       TEXT,
    escribible  INTEGER NOT NULL DEFAULT 1,
    sembrado_en TEXT NOT NULL,
    PRIMARY KEY (numero, clave)
);
CREATE INDEX IF NOT EXISTS ix_base_clave ON base_apm(clave);

-- ---------- 1b. LINEA BASE: lo que dicen los TDD hoy ----------
CREATE TABLE IF NOT EXISTS base_tdd (
    huella        TEXT PRIMARY KEY,
    ruta          TEXT NOT NULL,
    nombre        TEXT NOT NULL,
    numero        TEXT,                    -- aplicativo, si se pudo amarrar
    id_habilitador TEXT,
    tablas        INTEGER,
    celdas_llenas INTEGER,
    celdas_totales INTEGER,
    completitud   INTEGER,
    faltantes     TEXT,                    -- JSON con las tablas incompletas
    sembrado_en   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tdd_numero ON base_tdd(numero);

CREATE TABLE IF NOT EXISTS base_tdd_celdas (
    huella   TEXT NOT NULL,
    tabla    INTEGER NOT NULL,
    fila     INTEGER NOT NULL,
    columna  INTEGER NOT NULL,
    etiqueta TEXT,
    texto    TEXT,
    PRIMARY KEY (huella, tabla, fila, columna)
);

-- ---------- 1c. LINEA BASE: TDD Nivel 2 (reemplaza al TDD_V3 de arriba) ----------
-- Mismo patron que base_tdd/base_tdd_celdas, pero un TDD Nivel 2 no se ubica
-- por tabla/fila/columna -- se ubica por SECCION y CAMPO, que es como lo
-- entiende una persona que lo revisa (ver tdd_nivel2.CampoTDD2.llave).
CREATE TABLE IF NOT EXISTS base_tdd2 (
    huella         TEXT PRIMARY KEY,
    ruta           TEXT NOT NULL,
    nombre         TEXT NOT NULL,
    numero         TEXT,                   -- aplicativo, si se pudo amarrar
    id_habilitador TEXT,
    campos_llenos  INTEGER,
    campos_totales INTEGER,
    completitud    INTEGER,
    sembrado_en    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tdd2_numero ON base_tdd2(numero);

CREATE TABLE IF NOT EXISTS base_tdd2_campos (
    huella         TEXT NOT NULL,
    llave          TEXT NOT NULL,          -- "seccion::campo_normalizado"
    seccion        TEXT NOT NULL,
    seccion_titulo TEXT,
    campo          TEXT NOT NULL,
    valor          TEXT,
    confianza      TEXT,                   -- "C1".."C4" o ""
    PRIMARY KEY (huella, llave)
);

-- ---------- 2. MEMORIA: documentos fuente ya leidos ----------
CREATE TABLE IF NOT EXISTS documentos (
    huella      TEXT PRIMARY KEY,          -- sha256 del CONTENIDO, no del nombre
    nombre      TEXT NOT NULL,
    origen      TEXT,                      -- ruta local o URL
    tipo_origen TEXT,                      -- ruta | url | subido
    bytes       INTEGER,
    numero      TEXT,                      -- aplicativo al que se amarro
    senal       TEXT,                      -- como se amarro
    evidencia   TEXT,
    leido_en    TEXT NOT NULL,
    veces_visto INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_docs_numero ON documentos(numero);

CREATE TABLE IF NOT EXISTS hallazgos (
    huella    TEXT NOT NULL,
    clave     TEXT NOT NULL,
    valor     TEXT,
    evidencia TEXT,
    PRIMARY KEY (huella, clave)
);

-- ---------- 3. DECISIONES de una persona ----------
CREATE TABLE IF NOT EXISTS decisiones (
    numero      TEXT NOT NULL,
    clave       TEXT NOT NULL,
    valor       TEXT,                      -- lo que escogio; "" = no cambiar
    estado      TEXT,                      -- el conflicto que resolvia
    candidatos  TEXT,                      -- JSON: entre que opciones eligio
    decidido_en TEXT NOT NULL,
    PRIMARY KEY (numero, clave)
);

-- ---------- rastro de lo escrito ----------
CREATE TABLE IF NOT EXISTS escrituras (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo        TEXT NOT NULL,             -- apm | tdd
    numero      TEXT,
    origen      TEXT NOT NULL,
    destino     TEXT NOT NULL,
    celdas      INTEGER NOT NULL,
    detalle     TEXT,                      -- JSON de lo aplicado
    escrito_en  TEXT NOT NULL
);

-- ---------- referencia activa (copia interna de nombre fijo) ----------
-- El nombre de esta copia NUNCA cambia (a diferencia de los archivos que
-- "Hacer nueva version" deja para llevarse, que si numeran _v19, _v20...).
-- Para saber que tan al dia esta, no se usa un numero de version: se usan
-- fechas. `origen_actual` es solo informativo (de que archivo real vino la
-- ultima actualizacion), nunca se usa para decidir nada.
CREATE TABLE IF NOT EXISTS referencia (
    tipo           TEXT NOT NULL,          -- apm | tdd
    numero         TEXT NOT NULL,          -- '' para apm (es un solo libro)
    ruta_estable   TEXT NOT NULL,
    origen_actual  TEXT NOT NULL,
    creado_en      TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (tipo, numero)
);
"""


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def huella_de(ruta: str | Path) -> str:
    """sha256 del CONTENIDO. Deliberadamente no incluye el nombre ni la fecha:
    el mismo documento renombrado, o copiado a otra carpeta, sigue siendo el
    mismo documento y no hay por que volver a leerlo."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 256), b""):
            h.update(bloque)
    return h.hexdigest()


def huella_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


class Almacen:
    """Toda la persistencia del proyecto pasa por aqui. Ver la nota del modulo
    sobre por que: es la costura por donde esto se vuelve una API."""

    def __init__(self, carpeta: str | Path):
        self.ruta = Path(carpeta) / NOMBRE_ARCHIVO
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(ESQUEMA)
            con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                        ("version_esquema", str(VERSION_ESQUEMA)))

    @contextmanager
    def _con(self):
        con = sqlite3.connect(self.ruta, timeout=15)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------
    # 1. Sembrar la linea base
    # ------------------------------------------------------------------

    def sembrar_apm(self, libro) -> dict:
        """Vuelca el estado ACTUAL del libro a la base. Es idempotente: se puede
        volver a correr cuando el APM cambie, y reemplaza lo que habia.

        Se guardan tambien las columnas no escribibles. Parece de mas, pero es
        justo lo que permite contestar «¿por que este campo no se llenó?» sin
        volver a abrir el .xlsx.
        """
        t = ahora()
        filas_app, filas_campo = [], []
        for a in libro.aplicaciones:
            filas_app.append((a.numero, a.id_habilitador, a.nombre, a.fila,
                              t, str(libro.ruta)))
            for c in libro.columnas:
                valor = a.valores.get(c.clave)
                filas_campo.append((a.numero, c.clave, c.grupo, c.etiqueta,
                                    "" if valor is None else str(valor),
                                    1 if c.escribible else 0, t))

        with self._con() as con:
            con.execute("DELETE FROM aplicativos")
            con.execute("DELETE FROM base_apm")
            con.executemany("INSERT INTO aplicativos VALUES (?,?,?,?,?,?)", filas_app)
            con.executemany("INSERT INTO base_apm VALUES (?,?,?,?,?,?,?)", filas_campo)
        return {"aplicativos": len(filas_app), "campos": len(filas_campo)}

    def sembrar_tdd(self, ruta: str | Path, doc, celdas: list[dict],
                    numero: str = "") -> str:
        """Guarda un TDD y su contenido celda por celda. Devuelve la huella.

        Guardar las celdas y no solo el resumen es lo que permite, mas adelante,
        contestar «¿que TDD ya documenta el RTO?» sin volver a abrir 17 archivos
        de 3 MB.
        """
        ruta = Path(ruta)
        huella = huella_de(ruta)
        t = ahora()
        with self._con() as con:
            con.execute(
                "INSERT OR REPLACE INTO base_tdd VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (huella, str(ruta), ruta.name, numero or doc.numero_apm,
                 doc.id_habilitador, doc.total_tablas, doc.celdas_llenas,
                 doc.celdas_totales, doc.completitud,
                 json.dumps(doc.faltantes(), ensure_ascii=False), t))
            con.execute("DELETE FROM base_tdd_celdas WHERE huella = ?", (huella,))
            con.executemany(
                "INSERT OR REPLACE INTO base_tdd_celdas VALUES (?,?,?,?,?,?)",
                [(huella, c["tabla"], c["fila"], c["columna"],
                  c.get("etiqueta", ""), c.get("texto", "")) for c in celdas])
        return huella

    def sembrar_tdd2(self, ruta: str | Path, doc, numero: str = "") -> str:
        """Igual que `sembrar_tdd`, pero para el TDD Nivel 2: guarda el
        documento y CADA campo con su seccion, su valor y su confianza
        declarada (C1-C4). Devuelve la huella.

        `doc` es un `tdd_nivel2.DocumentoTDD2` (tiene `.campos`,
        `.id_habilitador`, `.campos_con_dato`).
        """
        ruta = Path(ruta)
        huella = huella_de(ruta)
        t = ahora()
        totales = len(doc.campos)
        llenos = len(doc.campos_con_dato)
        completitud = round(llenos * 100 / totales) if totales else 0
        with self._con() as con:
            con.execute(
                "INSERT OR REPLACE INTO base_tdd2 VALUES (?,?,?,?,?,?,?,?,?)",
                (huella, str(ruta), ruta.name, numero or "", doc.id_habilitador,
                 llenos, totales, completitud, t))
            con.execute("DELETE FROM base_tdd2_campos WHERE huella = ?", (huella,))
            con.executemany(
                "INSERT OR REPLACE INTO base_tdd2_campos VALUES (?,?,?,?,?,?,?)",
                [(huella, c.llave, c.seccion, c.seccion_titulo, c.campo,
                  c.valor, c.confianza) for c in doc.campos])
        return huella

    def tdd2_de(self, numero: str) -> list[dict]:
        """Los TDD Nivel 2 ya sembrados de un aplicativo, mas reciente primero."""
        if not numero:
            return []
        with self._con() as con:
            return [dict(r) for r in con.execute(
                "SELECT huella, ruta, nombre, completitud, campos_llenos, "
                "campos_totales, sembrado_en FROM base_tdd2 WHERE numero = ? "
                "ORDER BY sembrado_en DESC", (numero,))]

    def progreso_tdd2(self, numero: str) -> list[str]:
        """6 colores (uno por cada grupo de ~3 secciones seguidas del TDD
        Nivel 2, en orden de documento) que resumen que tan lleno esta cada
        pedazo del TDD Nivel 2 mas reciente de este aplicativo.

        Sin TDD sembrado todavia -> las 6 "rojo" (vacio). Con TDD sembrado,
        cada grupo se colorea por el % de sus campos que tienen dato:
        <=10% rojo, <80% naranja, >=80% verde. Un grupo sin ningun campo
        capturado en esa parte del documento queda "gris" (no aplica).
        """
        with self._con() as con:
            fila = con.execute(
                "SELECT huella FROM base_tdd2 WHERE numero = ? "
                "ORDER BY sembrado_en DESC LIMIT 1", (numero,)).fetchone()
            if not fila:
                return ["rojo"] * 6
            huella = fila["huella"]
            campos = con.execute(
                "SELECT seccion, valor FROM base_tdd2_campos WHERE huella = ?",
                (huella,)).fetchall()

        grupos_llenos = [0] * 6
        grupos_totales = [0] * 6
        for c in campos:
            seccion = (c["seccion"] or "")
            mayor_txt = seccion.split(".")[0].strip()
            if mayor_txt.isdigit():
                mayor = int(mayor_txt)
                grupo = min(5, (mayor * 6) // 17)
            else:
                grupo = 5   # anexos y tablas sin numero de seccion: al final
            grupos_totales[grupo] += 1
            valor = (c["valor"] or "").strip()
            if valor and valor.lower() != "sin información":
                grupos_llenos[grupo] += 1

        colores = []
        for llenos, total in zip(grupos_llenos, grupos_totales):
            if total == 0:
                colores.append("gris")
                continue
            pct = llenos * 100 / total
            if pct <= 10:
                colores.append("rojo")
            elif pct < 80:
                colores.append("naranja")
            else:
                colores.append("verde")
        return colores

    def cobertura_tdd2(self) -> list[dict]:
        """Por aplicativo: si ya tiene un TDD Nivel 2 sembrado como referencia,
        y que tan completo esta. Es el equivalente de `cobertura()` pero para
        la plantilla nueva (que reemplaza al TDD_V3)."""
        with self._con() as con:
            return [dict(r) for r in con.execute("""
                SELECT a.numero, a.nombre, a.id_habilitador,
                  t.nombre AS tdd2_nombre, t.campos_llenos, t.campos_totales,
                  t.completitud, t.sembrado_en
                FROM aplicativos a
                LEFT JOIN base_tdd2 t ON t.numero = a.numero
                ORDER BY CAST(a.numero AS INTEGER)""")]

    # ------------------------------------------------------------------
    # 2. Memoria de documentos fuente
    # ------------------------------------------------------------------

    def documento_conocido(self, huella: str) -> dict | None:
        """¿Ya leimos este contenido? Devuelve el documento con sus hallazgos, o
        None. Esta es la funcion que ahorra el re-escaneo completo."""
        with self._con() as con:
            fila = con.execute("SELECT * FROM documentos WHERE huella = ?",
                               (huella,)).fetchone()
            if not fila:
                return None
            hallazgos = con.execute(
                "SELECT clave, valor, evidencia FROM hallazgos WHERE huella = ?",
                (huella,)).fetchall()
        return {**dict(fila),
                "hallazgos": [dict(h) for h in hallazgos]}

    def registrar_documento(self, huella: str, nombre: str, origen: str,
                            tipo_origen: str, tamano: int, numero: str,
                            senal: str, evidencia: str,
                            hallazgos: dict) -> None:
        """Guarda lo que un documento aporto. `hallazgos` = {clave: (valor, evidencia)}."""
        with self._con() as con:
            existe = con.execute("SELECT veces_visto FROM documentos WHERE huella = ?",
                                 (huella,)).fetchone()
            veces = (existe["veces_visto"] + 1) if existe else 1
            con.execute(
                "INSERT OR REPLACE INTO documentos VALUES (?,?,?,?,?,?,?,?,?,?)",
                (huella, nombre, origen, tipo_origen, tamano, numero, senal,
                 evidencia, ahora(), veces))
            con.execute("DELETE FROM hallazgos WHERE huella = ?", (huella,))
            con.executemany(
                "INSERT OR REPLACE INTO hallazgos VALUES (?,?,?,?)",
                [(huella, clave, v, e) for clave, (v, e) in hallazgos.items()])

    def documentos_de(self, numero: str) -> list[dict]:
        with self._con() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM documentos WHERE numero = ? ORDER BY leido_en DESC",
                (numero,))]

    def tdd_de(self, numero: str) -> list[dict]:
        """Los TDD ya sembrados de un aplicativo. Es lo que permite, al escanear
        un documento fuente y amarrarlo a un aplicativo, decir tambien CUAL TDD
        es el que se va a llenar -- antes no habia esa referencia visible."""
        if not numero:
            return []
        with self._con() as con:
            return [dict(r) for r in con.execute(
                "SELECT huella, ruta, nombre, completitud, celdas_llenas, "
                "celdas_totales, sembrado_en FROM base_tdd WHERE numero = ? "
                "ORDER BY sembrado_en DESC", (numero,))]

    # ------------------------------------------------------------------
    # 3. Decisiones
    # ------------------------------------------------------------------

    def guardar_decisiones(self, numero: str, propuestas: list, decisiones: dict) -> int:
        """Recuerda que escogio la persona. Solo se guardan las decisiones REALES
        -- las de un conflicto que exigia elegir. Un campo que se lleno solo no
        es una decision de nadie y guardarlo como tal seria atribuirle a una
        persona algo que no hizo."""
        t = ahora()
        filas = []
        for p in propuestas:
            clave = p["clave"] if isinstance(p, dict) else p.clave
            if clave not in decisiones:
                continue
            exige = (p.get("exige_decision") if isinstance(p, dict)
                     else p.exige_decision)
            if not exige:
                # El campo no preguntaba nada: se llenaba solo o ya coincidia.
                # Archivarlo como "decision" le atribuiria a una persona algo
                # que nunca decidio, y la proxima vez se saltaria una revision
                # que en realidad nadie hizo.
                continue
            estado = p["estado"] if isinstance(p, dict) else p.estado
            cands = p.get("candidatos", []) if isinstance(p, dict) else [
                {"valor": c.valor, "documento": c.documento} for c in p.candidatos]
            filas.append((numero, clave, str(decisiones[clave]), estado,
                          json.dumps(cands, ensure_ascii=False), t))
        with self._con() as con:
            con.executemany("INSERT OR REPLACE INTO decisiones VALUES (?,?,?,?,?,?)",
                            filas)
        return len(filas)

    def decisiones_de(self, numero: str) -> dict[str, dict]:
        with self._con() as con:
            return {r["clave"]: dict(r) for r in con.execute(
                "SELECT * FROM decisiones WHERE numero = ?", (numero,))}

    # ------------------------------------------------------------------
    # Rastro de escrituras
    # ------------------------------------------------------------------

    def registrar_escritura(self, tipo: str, numero: str, origen: str,
                            destino: str, aplicados: list) -> None:
        with self._con() as con:
            con.execute(
                "INSERT INTO escrituras (tipo,numero,origen,destino,celdas,detalle,escrito_en)"
                " VALUES (?,?,?,?,?,?,?)",
                (tipo, numero, origen, destino, len(aplicados),
                 json.dumps(aplicados, ensure_ascii=False)[:20000], ahora()))

    # ------------------------------------------------------------------
    # Referencia activa (copia interna de nombre fijo, ver el esquema)
    # ------------------------------------------------------------------

    def actualizar_referencia(self, tipo: str, numero: str, ruta_estable: str,
                              origen_actual: str) -> dict:
        """Registra que la copia de referencia (`ruta_estable`, un nombre que
        no cambia) se acaba de actualizar a partir de `origen_actual` (el
        archivo real de donde salio esta vez -- el original, o una version
        nueva escrita por 'Hacer nueva version'). `creado_en` solo se escribe
        la primera vez; `actualizado_en` cambia cada vez. Devuelve las dos
        fechas, para no tener que volver a consultar."""
        t = ahora()
        numero = numero or ""
        with self._con() as con:
            previo = con.execute(
                "SELECT creado_en FROM referencia WHERE tipo = ? AND numero = ?",
                (tipo, numero)).fetchone()
            creado_en = previo["creado_en"] if previo else t
            con.execute(
                "INSERT OR REPLACE INTO referencia "
                "(tipo,numero,ruta_estable,origen_actual,creado_en,actualizado_en)"
                " VALUES (?,?,?,?,?,?)",
                (tipo, numero, str(ruta_estable), str(origen_actual), creado_en, t))
        return {"creado_en": creado_en, "actualizado_en": t}

    def referencia_de(self, tipo: str, numero: str = "") -> dict | None:
        with self._con() as con:
            fila = con.execute(
                "SELECT * FROM referencia WHERE tipo = ? AND numero = ?",
                (tipo, numero or "")).fetchone()
            return dict(fila) if fila else None

    # ------------------------------------------------------------------
    # Consulta y exportacion
    # ------------------------------------------------------------------

    def resumen(self) -> dict:
        with self._con() as con:
            def n(tabla):
                return con.execute(f"SELECT COUNT(*) c FROM {tabla}").fetchone()["c"]
            sembrado = con.execute(
                "SELECT MAX(sembrado_en) t, MAX(origen) o FROM aplicativos").fetchone()
            ref_apm = con.execute(
                "SELECT * FROM referencia WHERE tipo = 'apm' AND numero = ''").fetchone()
            return {
                "archivo": str(self.ruta),
                "existe": self.ruta.exists(),
                "kb": round(self.ruta.stat().st_size / 1024, 1) if self.ruta.exists() else 0,
                "aplicativos": n("aplicativos"),
                "campos_base": n("base_apm"),
                "tdd": n("base_tdd"),
                "celdas_tdd": n("base_tdd_celdas"),
                "tdd2": n("base_tdd2"),
                "campos_tdd2": n("base_tdd2_campos"),
                "documentos": n("documentos"),
                "hallazgos": n("hallazgos"),
                "decisiones": n("decisiones"),
                "escrituras": n("escrituras"),
                "sembrado_en": sembrado["t"] if sembrado else None,
                "origen_apm": sembrado["o"] if sembrado else None,
                "referencia_apm": dict(ref_apm) if ref_apm else None,
            }

    def cobertura(self) -> list[dict]:
        """Por aplicativo: cuanto tiene lleno el APM, cuantos TDD y cuantos
        documentos fuente. Es la vista que contesta «¿por donde vamos?»."""
        with self._con() as con:
            return [dict(r) for r in con.execute("""
                SELECT a.numero, a.nombre, a.id_habilitador,
                  (SELECT COUNT(*) FROM base_apm b
                     WHERE b.numero = a.numero AND b.escribible = 1
                       AND TRIM(COALESCE(b.valor,'')) <> ''
                       AND LOWER(TRIM(b.valor)) <> 'sin información') AS llenos,
                  (SELECT COUNT(*) FROM base_apm b
                     WHERE b.numero = a.numero AND b.escribible = 1) AS total,
                  (SELECT COUNT(*) FROM base_tdd t WHERE t.numero = a.numero) AS tdds,
                  (SELECT COUNT(*) FROM documentos d WHERE d.numero = a.numero) AS docs,
                  (SELECT COUNT(*) FROM decisiones x WHERE x.numero = a.numero) AS decisiones
                FROM aplicativos a
                ORDER BY CAST(a.numero AS INTEGER)""")]

    TABLAS = ("aplicativos", "base_apm", "base_tdd", "base_tdd_celdas",
              "base_tdd2", "base_tdd2_campos",
              "documentos", "hallazgos", "decisiones", "escrituras", "referencia")

    def exportar(self, carpeta: str | Path) -> dict:
        """Saca todo a un JSON y a un CSV por tabla.

        El JSON es para mover la base completa de un jalon; los CSV son para que
        alguien la abra en Excel sin instalar nada. Los dos existen porque la
        meta declarada es pasar esto a una base de verdad, y una exportacion que
        solo un programa puede leer no ayuda a migrar: ayuda a atorarse.
        """
        carpeta = Path(carpeta)
        carpeta.mkdir(parents=True, exist_ok=True)
        todo, archivos = {}, []

        with self._con() as con:
            for tabla in self.TABLAS:
                filas = [dict(r) for r in con.execute(f"SELECT * FROM {tabla}")]
                todo[tabla] = filas
                destino = carpeta / f"{tabla}.csv"
                with open(destino, "w", encoding="utf-8-sig", newline="") as f:
                    if filas:
                        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
                        w.writeheader()
                        w.writerows(filas)
                    else:
                        f.write("(sin registros)\n")
                archivos.append(str(destino))

        destino_json = carpeta / "almacen.json"
        destino_json.write_text(
            json.dumps({"exportado_en": ahora(), "version_esquema": VERSION_ESQUEMA,
                        "tablas": todo}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        archivos.insert(0, str(destino_json))
        return {"carpeta": str(carpeta), "archivos": archivos,
                "filas": {t: len(v) for t, v in todo.items()}}
