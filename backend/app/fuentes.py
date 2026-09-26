"""
fuentes.py
----------
Catalogos de las DOS fuentes institucionales que alimentan el Knowledge Hub:

  APM  Inventario de Aplicaciones. 49 aplicaciones en 42 campos, agrupados en
       9 categorias nativas de la hoja Inventory.
  TDD  Plantilla oficial de Diseno Tecnico. 19 tablas agrupadas en 10 bloques
       tematicos.

Por que viven aparte de taxonomy.py: taxonomy.py describe QUE ES un documento
(su tipo, su estado, su gobierno). Esto describe QUE INFORMACION DE APM O TDD
CONTIENE, que es una pregunta distinta y con otro vocabulario. Mezclarlas
obligaria a tocar el contrato de clasificacion cada vez que APM agregue un campo.

El campo "nivel" NO lo decide el modelo: viene de este catalogo. La relevancia
de un grupo para el Knowledge Hub es una decision institucional ya tomada, no
algo que se infiera leyendo un documento suelto.
"""

from __future__ import annotations

NIVELES = ["Critico", "Importante", "Complementario"]

# --- APM · Inventario de Aplicaciones -- 9 grupos / 42 campos ---------------
APM_GRUPOS = [
    {"grupo": "Identidad de la Aplicacion", "nivel": "Critico", "campos": 11,
     "contenido": "Nombre, descripcion, duenos de negocio/tecnico/funcional, proveedor"},
    {"grupo": "Perfil Tecnico", "nivel": "Critico", "campos": 7,
     "contenido": "Hosting, stack tecnologico, URLs (PROD/DEV/PPRD), version"},
    {"grupo": "Calificacion APM", "nivel": "Critico", "campos": 4,
     "contenido": "Criticidad, Valor de Negocio, Salud Tecnica, Disposicion TIME"},
    {"grupo": "Riesgo y Cumplimiento", "nivel": "Importante", "campos": 4,
     "contenido": "Clasificacion de datos, cumplimiento (LFPDPPP), numero de integraciones, notas"},
    {"grupo": "Ciclo de Vida", "nivel": "Importante", "campos": 3,
     "contenido": "Fecha de arranque, fin de soporte, usuarios activos"},
    {"grupo": "Gobierno", "nivel": "Importante", "campos": 3,
     "contenido": "Fecha de evaluacion, proxima revision, estatus"},
    {"grupo": "Costos de Propiedad", "nivel": "Complementario", "campos": 4,
     "contenido": "Licencias, infraestructura, soporte, costo total anual"},
    {"grupo": "Valores TEC", "nivel": "Complementario", "campos": 2,
     "contenido": "Ecosistema, criticidad interna (taxonomia institucional)"},
    {"grupo": "Trazabilidad", "nivel": "Complementario", "campos": 2,
     "contenido": "Fuente SharePoint y nivel de confianza del dato"},
]

# --- TDD · Plantilla de Diseno Tecnico -- 10 bloques / 19 tablas ------------
TDD_BLOQUES = [
    {"grupo": "Identificacion y Continuidad", "nivel": "Critico", "tablas": 2,
     "contenido": "ID Habilitador (enlace a APM), responsable, RTO/RPO, SSP, TIER"},
    {"grupo": "Seguridad", "nivel": "Critico", "tablas": 1,
     "contenido": "Checklist de estandares CWE, cifrado, HTTPS/SFTP"},
    {"grupo": "Stack Tecnologico", "nivel": "Critico", "tablas": 1,
     "contenido": "Base de datos, contenedores, on-premise/cloud, framework, lenguaje"},
    {"grupo": "Integraciones", "nivel": "Critico", "tablas": 1,
     "contenido": "Origen/destino, datos transferidos, frecuencia y volumen"},
    {"grupo": "Diagramas y Contexto", "nivel": "Importante", "tablas": 3,
     "contenido": "Contexto, casos de uso, actividad, secuencia, clases, DER, despliegue"},
    {"grupo": "Infraestructura", "nivel": "Importante", "tablas": 3,
     "contenido": "Consideraciones generales, horario de servicio, datacenter/cores/RAM"},
    {"grupo": "Decisiones (ADR)", "nivel": "Importante", "tablas": 2,
     "contenido": "Decisiones acordadas en Assessment y en Design Review"},
    {"grupo": "Usuarios", "nivel": "Importante", "tablas": 1,
     "contenido": "Perfil/rol y numero de usuarios finales"},
    {"grupo": "Portada / Control", "nivel": "Complementario", "tablas": 3,
     "contenido": "Historial de versiones, proposito del documento, revisiones de equipo"},
    {"grupo": "Procesos Batch y Componentes", "nivel": "Complementario", "tablas": 2,
     "contenido": "Recuperacion ante fallas batch, nuevos servidores/componentes"},
]

# Totales declarados en el requerimiento, para poder contrastarlos.
# El texto dice "49 aplicaciones en 42 campos", pero los 9 grupos de la tabla
# suman 40. No se inventan dos campos para cuadrar la cuenta: la diferencia se
# deja visible para que alguien la aclare contra la hoja Inventory real.
TOTALES_DECLARADOS = {
    "apm_aplicaciones": 49,
    "apm_campos": 42,
    "tdd_tablas": 19,
}

FUENTES = {
    "apm": {
        "etiqueta": "APM · Inventario de Aplicaciones",
        "unidad": "campos",
        "grupos": APM_GRUPOS,
    },
    "tdd": {
        "etiqueta": "TDD · Plantilla de Diseno Tecnico",
        "unidad": "tablas",
        "grupos": TDD_BLOQUES,
    },
}

# Cuanta informacion aporta el documento sobre ese grupo. Es el eje que permite
# responder la pregunta pendiente del requerimiento: que se documenta DENTRO del
# Knowledge Hub y que queda solo como enlace a la fuente original.
COBERTURAS = [
    "Documentado",   # el documento trae el dato en si
    "Referenciado",  # lo menciona o apunta a la fuente, sin contenerlo
    "Ausente",
]


def catalogo(fuente: str) -> list[dict]:
    return FUENTES[fuente]["grupos"]


def nombres(fuente: str) -> list[str]:
    return [g["grupo"] for g in FUENTES[fuente]["grupos"]]


def nivel_de(fuente: str, grupo: str) -> str:
    for g in FUENTES[fuente]["grupos"]:
        if g["grupo"] == grupo:
            return g["nivel"]
    return ""


def bloque_prompt(fuente: str) -> str:
    """Renderiza el catalogo para inyectarlo al prompt. Fuente unica: si manana
    APM agrega un grupo, se agrega aqui y el prompt lo aprende solo."""
    f = FUENTES[fuente]
    lineas = [f"{f['etiqueta']}:"]
    for g in f["grupos"]:
        lineas.append(
            f"  - {g['grupo']}  [{g['nivel']}, {g.get('campos') or g.get('tablas')} "
            f"{f['unidad']}]: {g['contenido']}")
    return "\n".join(lineas)
