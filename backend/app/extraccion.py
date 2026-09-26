"""
extraccion.py
-------------
Saca de un documento fuente los valores que corresponden a columnas del APM.

Como funciona: arma un indice `etiqueta -> valor` con las tablas de dos columnas,
los renglones tipo `Hosting: Cloud-SaaS` y las propiedades del archivo, y luego
busca ahi usando las ETIQUETAS REALES del libro mas un puñado de sinonimos. No
hay una lista de campos inventada: las etiquetas salen de `LibroAPM`, asi que si
manana el Tec agrega una columna, esto la busca sin tocar codigo.

Y lo que NO hace, que es la mitad del valor: no le pide a un modelo que rellene.
Un LLM al que se le da una plantilla de 40 columnas y un documento que habla de
cinco devuelve 40 valores plausibles. Aqui, si el documento no lo dice, el campo
no aparece — y un campo que no aparece se ve, mientras que uno inventado no.

Cada valor viaja con su evidencia: la linea exacta del documento. Sin eso, quien
revisa tiene que abrir el archivo para creerle a la aplicacion, y entonces la
aplicacion no le ahorro nada.
"""

from __future__ import annotations

import re
import unicodedata

from .apm import LibroAPM
from .conciliacion import Candidato

MAX_VALOR = 300

_VACIOS = {"", "-", "--", "n/a", "na", "n.a.", "no aplica", "nd", "n/d",
           "pendiente", "por definir", "tbd", "sin informacion", "sin información",
           "ninguno", "ninguna", "x"}

_SEPARADOR = re.compile(r"^\s*([^:–—]{2,60}?)\s*[:–—]\s*(.+)$")

# Sinonimos por SUFIJO de la clave de columna. Solo donde el documento real usa
# otra palabra que la hoja: no se duplica lo que la etiqueta ya dice.
SINONIMOS = {
    "identidad_de_la_aplicacion_habilitador_aplicacion":
        ["nombre de la aplicacion", "nombre del sistema", "nombre del aplicativo",
         "aplicacion", "sistema", "application name"],
    "identidad_de_la_aplicacion_descripcion":
        ["descripcion funcional", "proposito", "objetivo del sistema"],
    "identidad_de_la_aplicacion_dueno_negocio_product_owner":
        ["product owner", "business owner", "responsable de negocio"],
    "identidad_de_la_aplicacion_responsable_tecnico":
        ["lider tecnico", "technical owner", "arquitecto", "responsable"],
    "identidad_de_la_aplicacion_proveedor": ["vendor", "fabricante", "casa de software"],
    "perfil_tecnico_hosting": ["alojamiento", "modelo de despliegue", "nube", "cloud"],
    "perfil_tecnico_stack_tecnologico":
        ["stack", "tecnologia", "tecnologias", "plataforma tecnologica"],
    "perfil_tecnico_direccion_url_prod": ["url productivo", "url de produccion", "liga productiva"],
    "perfil_tecnico_direccion_url_devl": ["url desarrollo", "ambiente de desarrollo"],
    "perfil_tecnico_direccion_url_pprd": ["url preproduccion", "ambiente de pruebas"],
    "perfil_tecnico_version": ["version del sistema", "release"],
    "ciclo_de_vida_primer_dia_produccion":
        ["fecha de arranque", "puesta en produccion", "go live", "en operacion desde",
         "fecha de liberacion"],
    "ciclo_de_vida_fin_de_soporte": ["end of life", "eol", "fecha de baja", "retiro"],
    "ciclo_de_vida_usuarios_activos": ["numero de usuarios", "usuarios finales", "usuarios"],
    "riesgo_y_cumplimiento_clasificacion_de_datos":
        ["clasificacion de la informacion", "confidencialidad", "sensibilidad de datos"],
    "riesgo_y_cumplimiento_etiquetas_de_cumplimiento":
        ["cumplimiento", "normatividad", "lfpdppp", "gdpr", "regulacion"],
    "riesgo_y_cumplimiento_integraciones": ["numero de integraciones", "interfaces"],
    "gobierno_estatus": ["status", "estado del aplicativo"],
    "valores_tec_ecosistema": ["ecosistema tec", "vicerrectoria"],
}


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower().replace("ñ", "n")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _util(valor: str) -> bool:
    v = _norm(valor)
    return bool(v) and v not in {_norm(x) for x in _VACIOS} and len(v) > 1


def _limpiar(valor: str) -> str:
    v = re.sub(r"\s+", " ", str(valor or "")).strip(" .;\t")
    return v[:MAX_VALOR] + ("…" if len(v) > MAX_VALOR else "")


# --------------------------------------------------------------------------
# Tablas ANCHAS de un TDD_V3 (3+ columnas)
# --------------------------------------------------------------------------
# La regla de abajo (columna 0 = etiqueta, columna 1 = valor) solo tiene
# sentido en tablas de 2 columnas. En un TDD real la mayoria de las tablas
# son mas anchas -- Seguridad, Stack Tecnologico, Integraciones, Datacenter,
# Usuarios, etc. -- y en esas la columna util casi siempre es OTRA (la
# ultima, normalmente). Verificado abriendo DOS documentos reales
# (TDD_V3_PASE.docx y TDD_V3_Canvas.docx): las 19 tablas tienen exactamente
# el mismo encabezado y la misma forma en los dos, asi que reconocerlas por
# su encabezado real (no por su POSICION) funciona igual para cualquier
# archivo "v3".
#
# Regla que se respeta igual que en el resto del archivo: cada valor que
# sale de aqui es texto COPIADO de una celda, cuando mucho varias celdas
# unidas con " | " o " ; ". Nunca se resume ni se redacta de nuevo.

_INSTRUCTIVO_MARCADORES = (
    "si el proyecto requiere revision",   # boilerplate fijo de "Revisiones del equipo"
    "pega aqui la imagen",                # placeholder del recuadro de diagramas (DER, etc.)
)


def _es_instructivo(texto: str) -> bool:
    n = _norm(texto)
    return any(m in n for m in _INSTRUCTIVO_MARCADORES)


def _fila_con_datos(fila: list[str], desde: int = 0) -> bool:
    return any(_util(c) for c in fila[desde:])


def _pares_tabla_ancha(indice: int, filas: list[list[str]],
                       contexto: dict) -> list[tuple[str, str, str]]:
    """Lee UNA tabla ancha conocida de un TDD_V3. `contexto` trae contadores
    compartidos entre tablas del mismo documento (para distinguir, por
    ejemplo, el primer recuadro de un solo texto del segundo)."""
    if not filas:
        return []
    encabezado = [_norm(c) for c in filas[0]]
    resto = filas[1:]
    ancho = len(filas[0])

    def col(i: str | int) -> str:
        return encabezado[i] if isinstance(i, int) and i < len(encabezado) else ""

    salida: list[tuple[str, str, str]] = []

    # --- Bloques de un solo texto (1 celda, o 1 fila x 2 celdas con la
    # primera vacia): diagrama de contexto, DER (casi siempre vacio -- el DER
    # se pega como imagen, no como texto), o el instructivo fijo de
    # "revisiones del equipo", que se descarta por no ser dato del proyecto.
    if len(filas) == 1 and ancho <= 2:
        texto = filas[0][-1].strip() if filas[0] else ""
        if not _util(texto) or _es_instructivo(texto):
            return []
        if ancho == 1:
            contexto["bloques_1x1"] = contexto.get("bloques_1x1", 0) + 1
            if contexto["bloques_1x1"] == 1:
                salida.append(("diagrama de contexto", texto, texto))
            # el segundo bloque de una sola celda (el recuadro del DER) casi
            # siempre es el placeholder ya filtrado arriba; si trajera texto
            # real no hay forma segura de saber a que campo pertenece, asi
            # que no se propone nada en vez de adivinar.
        else:
            salida.append(("consideraciones generales", texto, texto))
        return salida

    if ancho < 3:
        return []

    # --- RTO / SSP / RPO / TIER: 4 columnas SIN encabezado -- cada fila ya
    # trae 2 parejas etiqueta/valor una junto a la otra.
    if ancho == 4 and encabezado[0] in ("rto", "rpo") and len(filas) <= 3:
        for fila in filas:
            for i in (0, 2):
                if i + 1 < len(fila) and fila[i].strip() and _util(fila[i + 1]):
                    ev = f"{fila[i].strip()} | {fila[i + 1].strip()}"
                    salida.append((fila[i].strip(), fila[i + 1].strip(), ev))
        return salida

    # --- Seguridad: checklist CWE (ESTANDAR | CUMPLE... | JUSTIFICACION) ---
    if "estandar" in col(0) and "justificacion" in col(ancho - 1):
        hallazgos = [f"{f[0].strip()}: {f[-1].strip()}" for f in resto
                    if len(f) >= 3 and _util(f[0]) and _util(f[-1])]
        if hallazgos:
            valor = " | ".join(hallazgos)
            salida.append(("cwe", valor, "checklist CWE, columna JUSTIFICACIÓN"))
        return salida

    # --- Stack Tecnologico: BD / Container / On Premise / Cloud / Arquetipo -
    if "stack tecnologico" in col(0) and "componente" in col(1):
        on_prem = cloud = ""
        for f in resto:
            if len(f) < 3 or not _util(f[0]) or not _util(f[-1]):
                continue
            etiqueta_fila, valor_fila = _norm(f[0]), f[-1].strip()
            ev = f"{f[0].strip()} | {valor_fila}"
            if etiqueta_fila == "bd":
                salida.append(("base de datos", valor_fila, ev))
            elif etiqueta_fila.startswith("container"):
                salida.append(("contenedores", valor_fila, ev))
            elif etiqueta_fila.startswith("on premise"):
                on_prem = valor_fila
            elif etiqueta_fila == "cloud":
                cloud = valor_fila
            elif etiqueta_fila.startswith("arquetipo"):
                salida.append(("arquetipo", valor_fila, ev))
        combinado = " | ".join(p for p in
                               (f"On Premise: {on_prem}" if on_prem else "",
                                f"Cloud: {cloud}" if cloud else "") if p)
        if combinado:
            salida.append(("on premise", combinado, combinado))
        return salida

    # --- Horario de Servicio del Aplicativo ---------------------------------
    if "horario de servicio" in col(0):
        renglones = [" | ".join(c.strip() for c in f if _util(c))
                    for f in resto if _fila_con_datos(f, desde=1)]
        if renglones:
            valor = " ; ".join(renglones)
            salida.append(("horario de servicio del aplicativo", valor, valor))
        return salida

    # --- Datacenter / On Prem / Nube / Ambiente / Cores / RAM / Storage -----
    if "datacenter" in col(0) and "cores" in encabezado:
        idx_cores = encabezado.index("cores")
        filas_dc, filas_cr = [], []
        for f in resto:
            if not _fila_con_datos(f):
                continue
            filas_dc.append(" | ".join(c for c in f[0:3] if _util(c)))
            if idx_cores < len(f):
                filas_cr.append(" | ".join(c for c in f[idx_cores:idx_cores + 3] if _util(c)))
        filas_dc = [f for f in filas_dc if f]
        filas_cr = [f for f in filas_cr if f]
        if filas_dc:
            valor = " ; ".join(filas_dc)
            salida.append(("datacenter", valor, valor))
        if filas_cr:
            valor = " ; ".join(filas_cr)
            salida.append(("cores", valor, valor))
        return salida

    # --- Integraciones: DESCRIPCION/TIPO/COMUNICACION/ORIGEN/DESTINO/... ---
    if "descripcion" in col(0) and "origen" in encabezado and "destino" in encabezado:
        idx_frecuencia = next((i for i, c in enumerate(encabezado) if "frecuencia" in c), None)
        detalle, frecuencias = [], []
        for f in resto:
            if not _fila_con_datos(f):
                continue
            detalle.append(" | ".join(c.strip() for c in f if _util(c)))
            if idx_frecuencia is not None and idx_frecuencia < len(f) and _util(f[idx_frecuencia]):
                frecuencias.append(f[idx_frecuencia].strip())
        if detalle:
            valor = " ; ".join(detalle)
            salida.append(("integraciones", valor, valor))
        if frecuencias:
            valor = " ; ".join(frecuencias)
            salida.append(("frecuencia y volumen", valor, valor))
        return salida

    # --- Procesos Batch: NOMBRE DEL PROCESO / HORARIO / DIAS / ACCIONES ----
    if "nombre del proceso" in col(0):
        renglones = [" | ".join(c.strip() for c in f if _util(c))
                    for f in resto if _fila_con_datos(f)]
        if renglones:
            valor = " ; ".join(renglones)
            salida.append(("nombre del proceso", valor, valor))
        return salida

    # --- Fuentes de datos / nuevos componentes: NOMBRE/¿NUEVA?/TIPO/... ----
    if col(0) == "nombre" and "nueva" in col(1):
        renglones = [" | ".join(c.strip() for c in f if _util(c))
                    for f in resto if _fila_con_datos(f)]
        if renglones:
            valor = " ; ".join(renglones)
            salida.append(("fuentes de datos", valor, valor))
        return salida

    # --- Usuarios: PERFIL/ROL / USUARIO FINAL / NUMERO ----------------------
    if "perfil" in col(0) and "usuario final" in encabezado:
        perfiles, numeros = [], []
        for f in resto:
            if len(f) < 3 or not _util(f[0]):
                continue
            if _util(f[1]):
                perfiles.append(f"{f[0].strip()}: {f[1].strip()}")
            if _util(f[2]):
                numeros.append(f"{f[0].strip()}: {f[2].strip()}")
        if perfiles:
            salida.append(("perfil/rol", " ; ".join(perfiles), " ; ".join(perfiles)))
        if numeros:
            salida.append(("numero", " ; ".join(numeros), " ; ".join(numeros)))
        return salida

    # --- Decisiones (ADR): titulo repetido + fila ADR/DECISION/OBSERVACIONES
    titulo_fila0 = next((c for c in filas[0] if _util(c)), "")
    if "decisiones acordadas" in _norm(titulo_fila0):
        datos = resto[1:] if resto and "adr" in _norm(" ".join(resto[0])) else resto
        renglones = [f"{f[-3].strip()}: {f[-2].strip()} — {f[-1].strip()}"
                    for f in datos if len(f) >= 3 and _fila_con_datos(f)]
        if renglones:
            valor = " ; ".join(renglones)
            etiqueta = ("decisiones acordadas etapa de design review"
                        if "design review" in _norm(titulo_fila0)
                        else "decisiones acordadas etapa de assessment")
            salida.append((etiqueta, valor, valor))
        return salida

    return salida


def indice_de(doc: dict) -> list[tuple[str, str, str]]:
    """(etiqueta normalizada, valor, evidencia), en orden de aparicion.

    Si una etiqueta se repite, gana la PRIMERA: en un documento con plantilla,
    la primera suele ser la ficha de portada y las siguientes son ejemplos.
    """
    pares: list[tuple[str, str, str]] = []

    def agregar(etiqueta: str, valor: str, evidencia: str):
        if not _util(valor):
            return
        clave = _norm(etiqueta)
        if clave and len(clave) <= 70:
            pares.append((clave, _limpiar(valor), _limpiar(evidencia)))

    # Tablas anchas conocidas PRIMERO: si se dejara para despues, la lectura
    # generica de abajo (columna 0 / columna 1) ya habria puesto una pareja
    # de peor calidad con la MISMA etiqueta, y como gana la primera, la buena
    # nunca se usaria.
    contexto: dict = {}
    for i, tabla in enumerate(doc.get("tablas") or []):
        for etiqueta, valor, evidencia in _pares_tabla_ancha(i, tabla.get("filas") or [], contexto):
            agregar(etiqueta, valor, evidencia)

    # Pareja columna0/columna1 SOLO en tablas de 2 columnas: en una tabla
    # ancha (3+) la fila 0 es un encabezado de columnas, no una etiqueta con
    # su valor al lado (ej. "HORARIO DE SERVICIO DEL APLICATIVO" | "DÍAS"
    # NO significa que el horario sea "DÍAS" -- "DÍAS" es el nombre de la
    # segunda columna). Las tablas anchas ya se leyeron arriba, en
    # `_pares_tabla_ancha`; dejarlas pasar tambien por aqui solo mete ruido.
    for tabla in (doc.get("tablas") or []):
        filas = tabla.get("filas") or []
        if filas and len(filas[0]) > 2:
            continue
        for fila in filas:
            celdas = [str(c or "").strip() for c in fila]
            if len(celdas) >= 2 and celdas[0]:
                agregar(celdas[0], celdas[1], f"{celdas[0]} | {celdas[1]}")

    for parrafo in (doc.get("parrafos") or []):
        for linea in str(parrafo).split("\n"):
            m = _SEPARADOR.match(linea.strip())
            if m:
                agregar(m.group(1), m.group(2), linea.strip())

    props = doc.get("propiedades") or {}
    if isinstance(props, dict):
        for k, v in props.items():
            agregar(k, v, f"propiedad del archivo · {k}: {v}")

    return pares


def _etiquetas_de(col, clave: str) -> list[str]:
    base = [_norm(col.etiqueta)]
    # `Dirección URL (PROD)` -> tambien `direccion url prod`, ya normalizado.
    base += [_norm(s) for s in SINONIMOS.get(clave, [])]
    return [b for b in dict.fromkeys(base) if b]


def extraer(doc: dict, libro: LibroAPM, nombre_documento: str
            ) -> dict[str, list[Candidato]]:
    """Lo que este documento aporta, por columna del APM.

    Solo se devuelven columnas ESCRIBIBLES: proponer un valor para una formula
    es ruido que quien revisa tiene que descartar a mano cada vez.
    """
    pares = indice_de(doc)
    salida: dict[str, list[Candidato]] = {}

    for col in libro.columnas:
        if not col.escribible:
            continue
        etiquetas = _etiquetas_de(col, col.clave)

        encontrado = None
        # Pasada 1: la etiqueta del documento es exactamente una de las nuestras.
        for clave, valor, ev in pares:
            if clave in etiquetas:
                encontrado = (valor, ev)
                break
        # Pasada 2: la etiqueta del documento contiene la nuestra como palabra.
        if not encontrado:
            for clave, valor, ev in pares:
                for e in etiquetas:
                    if len(e) >= 5 and re.search(rf"\b{re.escape(e)}\b", clave):
                        encontrado = (valor, ev)
                        break
                if encontrado:
                    break

        if encontrado:
            salida[col.clave] = [Candidato(encontrado[0], nombre_documento, encontrado[1])]

    return salida


def fusionar(por_documento: list[dict[str, list[Candidato]]]
             ) -> dict[str, list[Candidato]]:
    """Junta lo de varios documentos en una sola bolsa por columna.

    No se deduplica ni se escoge un ganador aqui: eso lo hace `conciliar_apm`,
    que es quien sabe distinguir «los dos dicen lo mismo» de «los dos se
    contradicen». Mezclar las dos responsabilidades es como se pierde el
    conflicto sin que nadie lo vea.
    """
    salida: dict[str, list[Candidato]] = {}
    for hallazgos in por_documento:
        for clave, candidatos in hallazgos.items():
            salida.setdefault(clave, []).extend(candidatos)
    return salida
