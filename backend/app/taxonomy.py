"""
taxonomy.py
-----------
Fuente unica de verdad de la clasificacion.

Todo lo que este aqui se usa DOS veces:
  1. Se inyecta al prompt de Claude (para que clasifique dentro del catalogo).
  2. Se usa para validar la respuesta (para que no invente valores fuera del catalogo).

Si se agrega un valor nuevo, se agrega aqui y se propaga solo.
"""

# ---------------------------------------------------------------------------
# CAPAS DEL MODELO DE METADATOS
# ---------------------------------------------------------------------------
# 1. IDENTIDAD      -> que documento es          (id, version, fecha)
# 2. NATURALEZA     -> que clase de activo es    (tipo)
# 3. SEMANTICA      -> de que trata              (descripcion, contexto)
# 4. GOBIERNO       -> se puede confiar en el    (estado, responsable, confidencialidad)
# 5. PROCEDENCIA    -> de donde viene            (fuente)
# 6. GRAFO          -> con que se conecta        (relaciones)
# 7. CALIDAD        -> que tan solido es         (trazabilidad, confianza, observaciones)
# ---------------------------------------------------------------------------

TIPOS = [
    "Entregable",
    "Requerimiento",
    "Decision",
    "Riesgo",
    "Supuesto",
    "Evidencia",
    "Criterio de aceptacion",
    "Componente",
    "Proceso",
    "Arquitectura",
    "Integracion",
    "Minuta",
    "Procedimiento",
    "Manual",
    "Politica",
    "Estandar",
    "Documento tecnico",
    "Documento funcional",
    "Otro",
]

ESTADOS = [
    "Borrador",
    "En revision",
    "Aprobado",
    "Vigente",
    "Obsoleto",
    "No identificado",
]

CONFIDENCIALIDAD = [
    "Publico",
    "Interno",
    "Confidencial",
    "Restringido",
    "No identificado",
]

TIPOS_RELACION = [
    "Sistema",
    "Aplicacion",
    "Proceso",
    "Proyecto",
    "Area",
    "Persona",
    "Documento",
    "Requerimiento",
    "Decision",
    "Riesgo",
    "Dependencia",
    "Tecnologia",
    "Dominio",
]

# Como se obtuvo cada valor. Es el campo que hace auditable la clasificacion.
METODOS = [
    "extraido",    # literal en el documento o en sus propiedades
    "derivado",    # calculado a partir de datos literales (p.ej. nombre de archivo)
    "inferido",    # clasificacion semantica del modelo
    "no_identificado",
]

# ---------------------------------------------------------------------------
# CONTRATO POR ATRIBUTO
# ---------------------------------------------------------------------------
# metodos_permitidos: si "inferido" NO esta en la lista, el modelo no puede
# rellenar ese campo por interpretacion; necesita evidencia literal.
# ---------------------------------------------------------------------------

ATRIBUTOS = {
    "id": {
        "capa": "Identidad",
        "valor": "texto",
        "metodos_permitidos": ["extraido", "derivado"],
        "fallback": None,  # se genera POC-ACT-XXXX
    },
    "tipo": {
        "capa": "Naturaleza",
        "valor": "enum",
        "catalogo": TIPOS,
        "metodos_permitidos": ["extraido", "inferido"],
        "fallback": "Otro",
    },
    "descripcion": {
        "capa": "Semantica",
        "valor": "texto",
        "metodos_permitidos": ["inferido"],
        "fallback": "No identificada",
    },
    "version": {
        "capa": "Identidad",
        "valor": "texto",
        "metodos_permitidos": ["extraido", "derivado"],
        "fallback": "No identificada",
    },
    "estado": {
        "capa": "Gobierno",
        "valor": "enum",
        "catalogo": ESTADOS,
        "metodos_permitidos": ["extraido"],
        "fallback": "No identificado",
    },
    "responsable": {
        "capa": "Gobierno",
        "valor": "texto",
        "metodos_permitidos": ["extraido"],
        "fallback": "No identificado",
    },
    "fecha": {
        "capa": "Identidad",
        "valor": "fecha",
        "metodos_permitidos": ["extraido"],
        "fallback": "No identificada",
    },
    "fuente": {
        "capa": "Procedencia",
        "valor": "texto",
        "metodos_permitidos": ["extraido", "derivado", "inferido"],
        "fallback": "No identificada",
    },
    "confidencialidad": {
        "capa": "Gobierno",
        "valor": "enum",
        "catalogo": CONFIDENCIALIDAD,
        "metodos_permitidos": ["extraido"],
        "fallback": "No identificado",
    },
    "contexto": {
        "capa": "Semantica",
        "valor": "objeto",
        "metodos_permitidos": ["inferido"],
        "fallback": None,
    },
    "relaciones": {
        "capa": "Grafo",
        "valor": "lista",
        "metodos_permitidos": ["extraido", "inferido"],
        "fallback": [],
    },
    "trazabilidad": {
        "capa": "Calidad",
        "valor": "texto",
        "metodos_permitidos": ["derivado"],
        "fallback": "No identificada",
    },
}

# Ejes de cada diagrama detectado. Un diagrama de arquitectura suele contener
# mas conocimiento que el texto que lo rodea, y en un indice RAG se pierde
# entero si nadie lo convierte a texto.
EJES_DIAGRAMA = [
    "titulo",
    "tipo_diagrama",        # arquitectura, flujo, organigrama, captura, tabla...
    "descripcion",
    "elementos",            # entidades visibles, separadas por comas
    "flujo",                # que conecta con que, en una frase
]

TIPOS_DIAGRAMA = [
    "Arquitectura",
    "Flujo de proceso",
    "Modelo de datos",
    "Organigrama",
    "Cronograma",
    "Captura de pantalla",
    "Tabla o matriz",
    "Grafica",
    "Otro",
]

# Sub-ejes obligatorios del campo contexto.
EJES_CONTEXTO = [
    "contexto_funcional",
    "contexto_tecnico",
    "dominio",
    "sistemas_involucrados",
    "proceso_relacionado",
]

# Campos que exigen evidencia literal. Si el modelo los llena sin evidencia,
# metadata_validator los degrada al fallback.
CAMPOS_CON_EVIDENCIA_OBLIGATORIA = [
    "version",
    "estado",
    "responsable",
    "fecha",
    "confidencialidad",
]

CAMPOS_CONFIANZA = list(ATRIBUTOS.keys())

UMBRALES_CONFIANZA = {
    "alta": 90,      # 90-100
    "media": 70,     # 70-89
    "revision": 0,   # 0-69
}


def nivel_confianza(score: int) -> str:
    if score >= UMBRALES_CONFIANZA["alta"]:
        return "Alta"
    if score >= UMBRALES_CONFIANZA["media"]:
        return "Media"
    return "Requiere revision"
