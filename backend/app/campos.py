"""
campos.py
---------
El detalle fino de las dos plantillas: no los GRUPOS (eso ya lo tiene
fuentes.py) sino los CAMPOS CONCRETOS que hay que llenar dentro de cada grupo.

Por que hace falta este archivo y no basta fuentes.py: fuentes.py responde
"cuanto de APM toca este documento". Eso sirve para decidir que entra al
Knowledge Hub, pero no llena nada. Para llenar hay que saber que el grupo
"Perfil Tecnico" pide siete cosas y cuales son. Esa lista es la plantilla.

Cada campo trae `pistas`: las etiquetas con las que ese dato aparece escrito en
un documento real. Son las llaves de busqueda del extractor determinista, no
adornos. Si un campo no tiene pistas, es porque solo puede venir de la ficha ya
clasificada o de captura humana; se deja vacio antes que adivinarlo.

REGLA QUE NO SE NEGOCIA: aqui no se inventa contenido. El extractor solo copia
lo que el documento dice, con la linea exacta como evidencia. Un campo sin
respaldo se queda vacio y marcado, porque un inventario con datos plausibles
pero falsos es peor que un inventario incompleto: el incompleto se ve.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# APM · 9 grupos / 45 campos
# --------------------------------------------------------------------------
# Esta lista YA NO es una aproximacion escrita a mano: son las 45 columnas
# REALES de la hoja "Inventory" de E1.1.6_Inventario autoritativo de
# aplicativos.xlsx (v24, verificado abriendo el archivo con la clase real
# LibroAPM: 45 columnas, 68 aplicaciones). Los nombres de "etiqueta" son
# literalmente los encabezados de esa hoja, para que este catalogo (el
# "piso" que se usa cuando NO hay ningun libro sembrado) corresponda con el
# libro real y no con una version inventada.
#
# La hoja trae un grupo chiquito "ID" (columna #, Revisado, VPAF/Centrales,
# Decomiso e ID Habilitador) antes de que empiece "Identidad de la
# Aplicacion": aqui se deja fusionado dentro de "Identidad de la Aplicacion"
# para no romper el conteo narrado en todos lados como "9 grupos" -- pero
# los 45 campos SI estan todos, ninguno se perdio en la fusion. Dos columnas
# de esta hoja son calculadas por formula del propio libro (Costo Total
# Anual, Disposicion TIME): se dejan aqui igual, porque cuando no hay libro
# real que las calcule, se muestran como "faltante" en vez de desaparecer --
# ver el comentario junto a cada una.
#
# 2026-09: E1.1.6 agrego 3 columnas nuevas al frente del grupo "ID" frente
# al libro anterior (APM_Portfolio_Inventory_E1.xlsx, 42 campos): Revisado,
# VPAF/Centrales y Decomiso. Nada se renombro ni se quito -- superset limpio.

APM_CAMPOS = [
    # --- Identidad de la Aplicacion (15: sin contar el numero de fila, que
    # es un renglon automatico del inventario, no un dato de la aplicacion) ---
    ("Identidad de la Aplicacion", "id_revisado", "Revisado",
     ["revisado"]),
    ("Identidad de la Aplicacion", "id_vpaf_centrales", "VPAF/Centrales",
     ["vpaf/centrales", "vpaf centrales", "vpaf"]),
    ("Identidad de la Aplicacion", "id_decomiso", "Decomiso",
     ["decomiso"]),
    ("Identidad de la Aplicacion", "id_habilitador", "ID Habilitador",
     ["id habilitador", "id del habilitador", "clave del aplicativo",
      "application id", "id apm"]),
    ("Identidad de la Aplicacion", "habilitador_aplicacion", "Habilitador (Aplicación)",
     ["habilitador", "nombre del habilitador", "nombre de la aplicacion",
      "nombre del sistema", "application name", "aplicacion", "sistema"]),
    ("Identidad de la Aplicacion", "descripcion", "Descripción",
     ["descripcion", "descripcion funcional", "proposito", "objetivo del sistema"]),
    ("Identidad de la Aplicacion", "producto_componente_title", "Producto_Componente:Title",
     ["producto_componente:title", "producto componente title"]),
    ("Identidad de la Aplicacion", "producto_componente", "Producto_Componente",
     ["producto_componente", "producto componente"]),
    ("Identidad de la Aplicacion", "dueno_negocio", "Dueño Negocio (Product Owner)",
     ["dueno de negocio", "duenio de negocio", "business owner", "product owner",
      "responsable de negocio"]),
    ("Identidad de la Aplicacion", "responsable_tecnico", "Responsable Técnico",
     ["responsable tecnico", "dueno tecnico", "technical owner", "lider tecnico"]),
    ("Identidad de la Aplicacion", "responsable_funcional", "Responsable funcional",
     ["responsable funcional", "dueno funcional", "functional owner"]),
    ("Identidad de la Aplicacion", "responsable_implementacion", "Responsable de implementación",
     ["responsable de implementacion", "implementacion"]),
    ("Identidad de la Aplicacion", "responsable_operacion", "Responsable de operación",
     ["responsable de operacion", "operacion"]),
    ("Identidad de la Aplicacion", "responsable_soporte", "Responsable de soporte",
     ["responsable de soporte", "contacto de soporte", "mesa de ayuda", "soporte"]),
    ("Identidad de la Aplicacion", "proveedor", "Proveedor",
     ["proveedor", "vendor", "fabricante", "casa de software"]),

    # --- Perfil Tecnico (7) ---
    ("Perfil Tecnico", "nivel_customizacion", "Nivel de customización",
     ["nivel de customizacion", "nivel de personalizacion", "customizacion"]),
    ("Perfil Tecnico", "hosting", "Hosting",
     ["hosting", "alojamiento", "on premise", "on-premise", "nube", "cloud",
      "modelo de despliegue"]),
    ("Perfil Tecnico", "stack_tecnologico", "Stack Tecnológico",
     ["stack tecnologico", "stack", "tecnologia", "tecnologias", "plataforma tecnologica"]),
    ("Perfil Tecnico", "url_prod", "Dirección URL (PROD)",
     ["url productivo", "url prod", "url de produccion", "ambiente productivo",
      "liga productiva"]),
    ("Perfil Tecnico", "url_devl", "Dirección URL (DEVL)",
     ["url desarrollo", "url dev", "ambiente de desarrollo"]),
    ("Perfil Tecnico", "url_pprd", "Dirección URL (PPRD)",
     ["url pprd", "preproduccion", "pre produccion", "ambiente de pruebas", "qa"]),
    ("Perfil Tecnico", "version_aplicacion", "Versión",
     ["version", "version del sistema", "release"]),

    # --- Ciclo de Vida (3) ---
    ("Ciclo de Vida", "primer_dia_produccion", "Primer Día Producción",
     ["fecha de arranque", "puesta en produccion", "go live", "primer dia produccion",
      "en operacion desde"]),
    ("Ciclo de Vida", "fin_soporte", "Fin de Soporte",
     ["fin de soporte", "end of life", "eol", "fecha de baja", "retiro"]),
    ("Ciclo de Vida", "usuarios_activos", "Usuarios Activos",
     ["usuarios activos", "numero de usuarios", "cantidad de usuarios", "usuarios"]),

    # --- Costos de Propiedad (4) ---
    ("Costos de Propiedad", "costo_licencias", "Costo Licencias($)",
     ["costo de licencias", "licenciamiento", "licencias"]),
    ("Costos de Propiedad", "costo_infraestructura", "Costo Infraestructura ($)",
     ["costo de infraestructura", "infraestructura anual"]),
    ("Costos de Propiedad", "soporte_anual", "Soporte Anual ($)",
     ["costo de soporte", "soporte anual", "mantenimiento anual"]),
    ("Costos de Propiedad", "costo_total_anual", "Costo Total Anual ($)",
     # Calculada por formula en el libro real (Licencias+Infra+Soporte). Sin
     # libro que la calcule, se deja como "faltante": no se inventa un total.
     ["costo total anual", "tco", "costo total de propiedad"]),

    # --- Calificacion APM (4) ---
    ("Calificacion APM", "criticidad", "Criticidad",
     ["criticidad", "nivel de criticidad", "criticality"]),
    ("Calificacion APM", "puntaje_vn", "Puntaje VN (1–5)",
     ["puntaje vn", "valor de negocio", "business value"]),
    ("Calificacion APM", "puntaje_st", "Puntaje ST (1–5)",
     ["puntaje st", "salud tecnica", "technical health"]),
    ("Calificacion APM", "disposicion_time", "Disposición TIME",
     # Calculada de Puntaje VN x Puntaje ST en el libro real; ver nota arriba.
     ["disposicion time", "time", "tolerate invest migrate eliminate"]),

    # --- Gobierno (3) ---
    ("Gobierno", "fecha_ultima_evaluacion", "Fecha Última Evaluación",
     ["fecha de evaluacion", "fecha de assessment", "evaluado el"]),
    ("Gobierno", "proxima_revision", "Próx Revisión",
     ["proxima revision", "siguiente revision", "fecha de revision"]),
    ("Gobierno", "estatus", "Estatus",
     ["estatus", "status", "estado del aplicativo"]),

    # --- Riesgo y Cumplimiento (4) ---
    ("Riesgo y Cumplimiento", "integraciones_numero", "Integraciones #",
     ["numero de integraciones", "integraciones", "cantidad de interfaces"]),
    ("Riesgo y Cumplimiento", "clasificacion_datos", "Clasificación de Datos",
     ["clasificacion de datos", "clasificacion de la informacion", "confidencialidad",
      "sensibilidad de datos"]),
    ("Riesgo y Cumplimiento", "etiquetas_cumplimiento", "Etiquetas de Cumplimiento",
     ["cumplimiento", "normatividad", "lfpdppp", "gdpr", "regulacion",
      "cumplimiento normativo", "etiquetas de cumplimiento"]),
    ("Riesgo y Cumplimiento", "notas_riesgo", "Notas",
     ["notas de riesgo", "riesgos", "observaciones de riesgo", "notas"]),

    # --- Valores TEC (2) ---
    ("Valores TEC", "ecosistema", "Ecosistema",
     ["ecosistema", "ecosistema tec", "vicerrectoria", "escuela"]),
    ("Valores TEC", "criticidad_interna", "Criticidad (interna TEC)",
     ["criticidad interna", "criticidad tec", "clasificacion institucional"]),

    # --- Trazabilidad (2) ---
    ("Trazabilidad", "fuente_sharepoint", "Fuente de Información (SharePoint)",
     ["fuente", "sharepoint", "origen del dato", "repositorio origen"]),
    ("Trazabilidad", "confianza", "Confianza",
     ["nivel de confianza", "confianza del dato", "calidad del dato"]),
]

# --------------------------------------------------------------------------
# TDD · 10 bloques / 19 tablas
# --------------------------------------------------------------------------
# Igual que con APM: esta lista se rehizo abriendo DOS documentos reales
# (TDD_V3_PASE.docx y TDD_V3_Canvas.docx, carpeta docs/ de la v20) y
# comparando tabla por tabla -- las 19 tablas tienen EXACTAMENTE el mismo
# encabezado y la misma forma en los dos, asi que es la plantilla estable de
# "cualquier archivo que diga v3". Los campos que aqui habia (cifrado,
# protocolos_transferencia, framework, lenguaje, diagrama_despliegue) se
# quitaron porque no corresponden a ninguna fila real de la plantilla -- se
# habian inventado por parecer razonables, no porque el documento los pida.
# El extractor de tablas anchas que llena esto vive en extraccion.py
# (funcion `_pares_tablas_tdd`): antes solo sabia leer tablas de 2 columnas,
# asi que TODAS las tablas anchas (Seguridad, Stack, Integraciones, Datacenter,
# Usuarios, etc. -- la mayoria de las 19) se leian mal o no se leian.

TDD_CAMPOS = [
    # --- Identificacion y Continuidad (tablas "AIA" + RTO/RPO/SSP/TIER) ---
    ("Identificacion y Continuidad", "id_habilitador", "APM (ID Habilitador)",
     ["id habilitador", "apm id habilitador", "apm (id habilitador)", "clave apm", "id apm"]),
    ("Identificacion y Continuidad", "responsable_tdd", "Responsable de Implementación",
     ["responsable de implementacion", "responsable tecnico", "arquitecto", "lider tecnico"]),
    ("Identificacion y Continuidad", "rto", "RTO",
     ["rto", "recovery time objective", "tiempo objetivo de recuperacion"]),
    ("Identificacion y Continuidad", "rpo", "RPO",
     ["rpo", "recovery point objective", "punto objetivo de recuperacion"]),
    ("Identificacion y Continuidad", "ssp", "SSP Id (Evaluación de Sonar Cloud)",
     ["ssp", "ssp id", "sistema de soporte primario", "sonar cloud"]),
    ("Identificacion y Continuidad", "tier", "TIER",
     ["tier", "nivel tier", "clasificacion tier"]),

    # --- Seguridad (1 tabla: checklist de estandares CWE) ---
    ("Seguridad", "estandares_cwe", "Estándares CWE cubiertos",
     ["cwe", "estandar", "estandares de seguridad", "owasp", "checklist de seguridad"]),

    # --- Stack Tecnologico (1 tabla: BD / Contenedores / On Premise / Cloud / Arquetipo) ---
    ("Stack Tecnologico", "tdd_base_datos", "BD (Motor de base de datos)",
     ["base de datos", "motor de base de datos", "bd", "dbms"]),
    ("Stack Tecnologico", "contenedores", "Container (runtime / orquestador)",
     ["contenedores", "container", "docker", "kubernetes", "aks", "openshift"]),
    ("Stack Tecnologico", "modelo_despliegue", "On Premise / Cloud",
     ["on premise", "on-premise", "cloud", "nube", "azure", "aws", "modelo de despliegue"]),
    ("Stack Tecnologico", "arquetipo", "Arquetipo(s) de referencia aplicado",
     ["arquetipo", "arquetipos", "arquetipo de referencia"]),

    # --- Integraciones (1 tabla ancha: descripcion/tipo/comunicacion/origen/destino/datos/frecuencia) ---
    ("Integraciones", "integraciones_detalle", "Integraciones (descripción, origen → destino)",
     ["integracion", "integraciones", "interfaz", "interfaces", "sistemas origen",
      "sistemas destino", "api", "servicio web", "descripcion"]),
    ("Integraciones", "frecuencia_volumen", "Frecuencia y volumen",
     ["frecuencia", "volumen", "periodicidad", "frecuencia y volumen", "registros por"]),

    # --- Diagramas y Contexto (tabla 1.2 + tabla "Diagramas" 2.1 + DER 2.3.1) ---
    ("Diagramas y Contexto", "diagrama_contexto", "Diagrama de Contexto",
     ["diagrama de contexto", "contexto del sistema"]),
    ("Diagramas y Contexto", "casos_uso", "Casos de uso",
     ["casos de uso", "caso de uso", "use case"]),
    ("Diagramas y Contexto", "diagrama_secuencia", "Diagramas de Actividad / Secuencia",
     ["diagramas de actividad", "diagrama de actividad", "secuencia", "diagrama de secuencia",
      "flujo del proceso"]),
    ("Diagramas y Contexto", "modelo_datos", "Clases / Diagrama Entidad–Relación (DER)",
     ["der", "diagrama entidad relacion", "modelo entidad relacion", "clases",
      "diagrama de clases", "modelo de datos", "modelo conceptual de datos"]),

    # --- Infraestructura (general / horario / datacenter+cores) ---
    ("Infraestructura", "consideraciones_generales", "Consideraciones generales",
     ["consideraciones generales", "consideraciones de infraestructura"]),
    ("Infraestructura", "horario_servicio", "Horario de Servicio del Aplicativo",
     ["horario de servicio", "horario de servicio del aplicativo", "ventana de servicio",
      "ventanas de mantenimiento", "dias", "horario operativo"]),
    ("Infraestructura", "datacenter", "Datacenter / On Prem / Nube / Ambiente",
     ["datacenter", "on prem", "on prem / nube", "ambiente", "centro de datos"]),
    ("Infraestructura", "cores_ram", "Cores / RAM / Storage",
     ["cores", "cpu", "ram", "memoria", "vcpu", "storage"]),

    # --- Decisiones (ADR) (Assessment + Design Review) ---
    ("Decisiones (ADR)", "adr_assessment", "Decisiones Acordadas — Etapa de Assessment",
     ["adr", "decision de arquitectura", "decisiones acordadas etapa de assessment",
      "assessment", "acuerdos"]),
    ("Decisiones (ADR)", "adr_design_review", "Decisiones Acordadas — Etapa de Design Review",
     ["design review", "decisiones acordadas etapa de design review",
      "revision de diseno", "acuerdos de diseno"]),

    # --- Usuarios (1 tabla: perfil/rol, usuario final, numero) ---
    ("Usuarios", "perfiles_usuario", "Perfil / Rol y Usuario Final",
     ["perfil de usuario", "perfil/rol", "perfiles", "roles", "rol", "usuario final"]),
    ("Usuarios", "numero_usuarios", "Número de usuarios finales",
     ["numero de usuarios", "usuarios finales", "cantidad de usuarios", "numero"]),

    # --- Portada / Control (historial de versiones + proposito + revisiones) ---
    ("Portada / Control", "historial_versiones", "Historial de versiones",
     ["historial de versiones", "control de versiones", "control de cambios",
      "bitacora de cambios"]),
    ("Portada / Control", "proposito_documento", "Propósito del Documento",
     ["proposito del documento", "proposito", "objetivo del documento", "alcance del documento"]),
    ("Portada / Control", "revisiones_equipo", "Revisiones del equipo",
     # OJO: en la plantilla en blanco esta tabla trae el INSTRUCTIVO fijo
     # ("Si el proyecto requiere revision, levanta un ticket...") -- eso NO
     # es informacion del proyecto, es el mismo texto en todos los TDD. El
     # extractor de tablas anchas lo reconoce y lo descarta para no proponer
     # el instructivo como si fuera un dato real.
     ["revisado por", "revisiones del equipo", "aprobado por", "autorizo"]),

    # --- Procesos Batch y Componentes (recuperacion batch + fuentes/componentes nuevos) ---
    ("Procesos Batch y Componentes", "recuperacion_batch", "Acciones Correctivas ante Interrupción del Proceso Batch",
     ["batch", "proceso batch", "recuperacion ante fallas", "acciones correctivas",
      "reproceso", "job", "nombre del proceso"]),
    ("Procesos Batch y Componentes", "nuevos_componentes", "Nuevos servidores / componentes (fuentes de datos)",
     ["nuevos componentes", "nuevos servidores", "componentes requeridos",
      "fuentes de datos", "nueva"]),
]


def _armar(filas: list[tuple]) -> list[dict]:
    return [{"grupo": g, "clave": c, "etiqueta": e, "pistas": p}
            for g, c, e, p in filas]


CAMPOS = {
    "apm": _armar(APM_CAMPOS),
    "tdd": _armar(TDD_CAMPOS),
}


def de(fuente: str) -> list[dict]:
    return CAMPOS[fuente]


def por_grupo(fuente: str) -> dict[str, list[dict]]:
    salida: dict[str, list[dict]] = {}
    for campo in CAMPOS[fuente]:
        salida.setdefault(campo["grupo"], []).append(campo)
    return salida


def total(fuente: str) -> int:
    return len(CAMPOS[fuente])
