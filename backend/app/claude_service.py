"""
claude_service.py
-----------------
Construye el prompt de catalogacion a partir de taxonomy.py y llama a la API.

El prompt no esta escrito a mano con los catalogos copiados: se genera desde
la taxonomia, asi que agregar un tipo o un estado nuevo solo se hace en un lugar.
"""

from __future__ import annotations

import json
import logging
import os
import re

import anthropic

from . import fuentes, taxonomy

log = logging.getLogger(__name__)

MAX_TOKENS = 50_000


# El entorno se lee EN CADA LLAMADA, no al importar el modulo. Antes eran
# constantes de import: cambiar la llave desde la pantalla no surtia efecto
# hasta reiniciar el servidor. Ahora el cambio aplica de inmediato.
def _modelo() -> str:
    return (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5").strip()


def _workspace() -> str:
    return (os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip()


# Compatibilidad: algun modulo viejo podia importar MODELO.
MODELO = _modelo()

# Las API keys ligadas a identidad (las que emite una cuenta dentro de una
# organizacion) exigen declarar el workspace en el que actua la peticion. Sin
# esta cabecera la API responde 400 aunque el token sea correcto.

CONTEXTO_INSTITUCIONAL = """Estas analizando documentacion de proyectos del Tecnologico de Monterrey.

El objetivo es clasificar conocimiento relacionado con proyectos, aplicaciones,
arquitectura, gobierno de datos, integraciones, procesos, decisiones, riesgos,
entregables y documentacion tecnica o funcional.

Los metadatos seran utilizados posteriormente para construir activos de
conocimiento IA-ready y alimentar soluciones RAG, busqueda semantica, copilotos
y agentes. Una clasificacion incorrecta contamina el indice y hace que un
documento obsoleto se recupere como si fuera vigente. Por eso es preferible
devolver "No identificado" a devolver un valor plausible sin respaldo."""


def _catalogo(nombre: str, valores: list[str]) -> str:
    return f"{nombre}:\n" + "\n".join(f"  - {v}" for v in valores)


def construir_system_prompt() -> str:
    inferibles = [c for c, a in taxonomy.ATRIBUTOS.items()
                  if "inferido" in a["metodos_permitidos"]]
    literales = taxonomy.CAMPOS_CON_EVIDENCIA_OBLIGATORIA

    return f"""{CONTEXTO_INSTITUCIONAL}

Devuelves EXCLUSIVAMENTE un objeto JSON valido. Sin markdown, sin ```json,
sin texto antes ni despues.

=================================================================
REGLA CENTRAL: DOS CLASES DE ATRIBUTO
=================================================================

A) ATRIBUTOS INTERPRETABLES -> {", ".join(inferibles)}
   Son clasificaciones semanticas. Puedes deducirlas leyendo el documento,
   aunque no esten escritas de forma literal.

B) ATRIBUTOS DECLARATIVOS -> {", ".join(literales)}
   Son hechos administrativos. Solo puedes llenarlos si el valor aparece
   escrito en el documento, en sus propiedades, en encabezado/pie, en portada,
   en una tabla de control de cambios o en el nombre del archivo.
   Si no aparece: usa el valor "No identificado" / "No identificada".
   NUNCA los deduzcas por el tono, la formalidad o el aspecto del documento.
   Un documento bien formateado NO significa que este aprobado.

=================================================================
CATALOGOS CONTROLADOS (no inventes valores fuera de estas listas)
=================================================================

{_catalogo("tipo", taxonomy.TIPOS)}

{_catalogo("estado", taxonomy.ESTADOS)}

{_catalogo("confidencialidad", taxonomy.CONFIDENCIALIDAD)}

{_catalogo("relaciones[].tipo", taxonomy.TIPOS_RELACION)}

{_catalogo("metodo (como obtuviste cada valor)", taxonomy.METODOS)}

=================================================================
FUENTES INSTITUCIONALES (para los campos apm y tdd)
=================================================================

{fuentes.bloque_prompt("apm")}

{fuentes.bloque_prompt("tdd")}

=================================================================
REGLAS POR CAMPO
=================================================================

id           Usa el identificador oficial si el documento lo trae (codigo de
             documento, folio, clave). Si no existe, devuelve "" y el sistema
             generara uno temporal.

tipo         Un solo valor del catalogo. Elige el que describa la FUNCION del
             documento, no su formato. Una minuta que contiene decisiones sigue
             siendo "Minuta"; un documento cuya razon de ser es registrar una
             decision es "Decision".

descripcion  1 a 3 oraciones. Explica que conocimiento aporta el activo, no
             como se llama. No repitas el titulo.

version      Cadena tal cual aparece ("1.3", "v2", "3.0 final"). Si no aparece:
             "No identificada".

estado       Solo con marca explicita (BORRADOR, VIGENTE, tabla de control de
             cambios, sello de aprobacion). Si no hay marca: "No identificado".

responsable  Persona o area explicitamente senalada como autor, propietario,
             responsable o aprobador. Si no aparece: "No identificado".

fecha        Formato AAAA-MM-DD. Fecha del documento, no la de hoy. Si hay
             varias, la de la version mas reciente. Si no aparece:
             "No identificada".

fuente       De donde proviene el conocimiento: proyecto, area, sistema,
             reunion, repositorio o documento origen mencionado.

confidencialidad  Solo con leyenda explicita. Si no hay: "No identificado".

contexto     Objeto con estos ejes: {", ".join(taxonomy.EJES_CONTEXTO)}.
             Cada eje es una cadena breve. Si un eje no aplica, escribe
             "No identificado". sistemas_involucrados va como texto separado
             por comas.

relaciones   Lista de objetos {{"tipo": <catalogo>, "nombre": "..."}}.
             Extrae entidades reales nombradas en el documento o visibles en
             sus diagramas. Sin duplicados. Maximo 25.

apm          Que informacion del INVENTARIO DE APLICACIONES (APM) aporta este
             documento. Lista de objetos {{"grupo": <nombre exacto del catalogo
             APM>, "cobertura": <Documentado | Referenciado>, "detalle": "que trae exactamente",
             "cita": "fragmento breve del documento"}}.
             "Documentado" = el documento CONTIENE el dato.
             "Referenciado" = lo menciona o dice donde vive, sin contenerlo.
             NO incluyas grupos ausentes; si el documento no toca APM, lista vacia.
             NO devuelvas el nivel de criticidad: lo pone el sistema.

tdd          Lo mismo para la PLANTILLA DE DISENO TECNICO (TDD), usando los
             nombres de bloque del catalogo TDD. Misma estructura y mismas reglas.

             Distincion que importa: un documento que EXPLICA que APM y TDD
             existen no es lo mismo que uno que CONTIENE sus datos. Si solo los
             describe o enumera, la cobertura es "Referenciado", nunca
             "Documentado".

diagramas    Lista de objetos, UNO POR CADA IMAGEN que sea informativa
             (diagrama, arquitectura, flujo, organigrama, captura, grafica).
             Ejes: {", ".join(taxonomy.EJES_DIAGRAMA)}.
             tipo_diagrama sale de este catalogo: {", ".join(taxonomy.TIPOS_DIAGRAMA)}.
             "elementos" son las entidades que se leen en la imagen (cajas,
             sistemas, areas, roles), separadas por comas. "flujo" describe en
             una frase que conecta con que y en que direccion.
             Convierte la imagen en texto util para busqueda: alguien que solo
             lea el texto debe entender lo que muestra el diagrama.
             Si una imagen es decorativa (logo, linea, vineta) NO la incluyas.
             Si no recibiste imagenes, devuelve lista vacia.

trazabilidad Una frase que diga de donde salio la clasificacion, citando
             secciones, tablas, encabezados o imagenes concretas del documento.
             No inventes secciones que no existan.

evidencias   Objeto donde cada llave es un campo y el valor es
             {{"metodo": <catalogo>, "origen": "seccion/tabla/imagen/propiedad
             concreta", "cita": "fragmento breve del documento o cadena vacia"}}.
             Incluye al menos los campos declarativos.

confianza    Entero 0-100 por campo, para: {", ".join(taxonomy.CAMPOS_CONFIANZA)}.
             Calibra de verdad: si pusiste "No identificado" la confianza en ese
             campo debe ser baja (menor a 40). Si un valor es literal y explicito,
             puede pasar de 90. La confianza mide que tan respaldado esta el
             valor, no que tan seguro te sientes.

observaciones Lista de cadenas. Anota vacios relevantes, contradicciones,
             posible obsolescencia o cualquier cosa que un revisor humano deba
             mirar. Si no hay nada: lista vacia.

=================================================================
ESQUEMA DE SALIDA
=================================================================

{{
  "id": "",
  "tipo": "",
  "descripcion": "",
  "version": "",
  "estado": "",
  "responsable": "",
  "fecha": "",
  "fuente": "",
  "confidencialidad": "",
  "contexto": {{
    "contexto_funcional": "",
    "contexto_tecnico": "",
    "dominio": "",
    "sistemas_involucrados": "",
    "proceso_relacionado": ""
  }},
  "relaciones": [{{"tipo": "", "nombre": ""}}],
  "apm": [{{"grupo": "", "cobertura": "", "detalle": "", "cita": ""}}],
  "tdd": [{{"grupo": "", "cobertura": "", "detalle": "", "cita": ""}}],
  "diagramas": [{{"titulo": "", "tipo_diagrama": "", "descripcion": "",
                 "elementos": "", "flujo": ""}}],
  "trazabilidad": "",
  "evidencias": {{"campo": {{"metodo": "", "origen": "", "cita": ""}}}},
  "confianza": {{"tipo": 0, "descripcion": 0, "version": 0, "estado": 0,
                 "responsable": 0, "fecha": 0, "fuente": 0,
                 "confidencialidad": 0, "contexto": 0, "relaciones": 0,
                 "trazabilidad": 0, "id": 0}},
  "observaciones": []
}}"""


def _bloque_candidatos(candidatos: dict) -> str:
    if not candidatos:
        return ("DETECCION DETERMINISTA PREVIA: el analizador no encontro marcas "
                "explicitas de version, fecha, responsable, estado ni "
                "confidencialidad. Trata esos campos como no identificados salvo "
                "que los veas literalmente en el contenido.")
    lineas = [
        f"  - {campo}: '{d['valor']}'  (origen: {d['evidencia']}, metodo: {d['metodo']})"
        for campo, d in candidatos.items()
    ]
    return ("DETECCION DETERMINISTA PREVIA (reglas del analizador, ya verificadas "
            "contra el archivo):\n" + "\n".join(lineas) +
            "\nUsa estos valores salvo que el contenido los contradiga. Si los "
            "contradices, explica por que en observaciones.")


def _contenido_usuario(texto_doc: str, candidatos: dict, imagenes: list[dict]) -> list:
    bloques = []

    for i, img in enumerate(imagenes, start=1):
        bloques.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["base64"],
            },
        })
        bloques.append({
            "type": "text",
            "text": (f"Imagen {i} del documento. Si es un diagrama, arquitectura, "
                     f"organigrama o captura, usa lo que aparece en ella para "
                     f"enriquecer tipo, contexto y relaciones. Si es decorativa, "
                     f"ignorala."),
        })

    bloques.append({
        "type": "text",
        "text": (f"{_bloque_candidatos(candidatos)}\n\n"
                 f"=== DOCUMENTO A CLASIFICAR ===\n\n{texto_doc}\n\n"
                 f"=== FIN DEL DOCUMENTO ===\n\n"
                 f"Devuelve unicamente el JSON del esquema."),
    })
    return bloques


def _extraer_json(texto: str) -> dict:
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.MULTILINE).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio != -1 and fin > inicio:
        return json.loads(texto[inicio:fin + 1])
    raise ValueError("El modelo no devolvio JSON interpretable.")


def clasificar(texto_doc: str, candidatos: dict, imagenes: list[dict]) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta ANTHROPIC_API_KEY. Copia .env.example a .env y coloca tu token."
        )

    workspace = _workspace()
    modelo = _modelo()
    cabeceras = {"anthropic-workspace-id": workspace} if workspace else None
    client = anthropic.Anthropic(api_key=api_key, default_headers=cabeceras)

    try:
        # client.messages.create (sin streaming) rechaza la llamada con
        # "Streaming is required for operations that may take longer than
        # 10 minutes" en cuanto MAX_TOKENS es lo bastante alto para que el
        # SDK estime que podria tardar mas de eso. Con streaming no hay ese
        # limite: se va leyendo la respuesta mientras llega y al final
        # get_final_message() arma el mismo objeto Message de siempre, asi
        # que el resto de esta funcion no cambia.
        with client.messages.stream(
            model=modelo,
            max_tokens=MAX_TOKENS,
            system=construir_system_prompt(),
            messages=[{
                "role": "user",
                "content": _contenido_usuario(texto_doc, candidatos, imagenes),
            }],
        ) as stream:
            respuesta = stream.get_final_message()
    except anthropic.BadRequestError as exc:
        if "workspace" in str(exc).lower() and not workspace:
            raise RuntimeError(
                "Tu token esta ligado a una identidad y la API exige saber en que "
                "workspace actua. Agrega ANTHROPIC_WORKSPACE_ID=<id> al .env "
                "(lo encuentras en console.anthropic.com, en Settings > Workspaces; "
                "empieza con 'wrkspc_'). Mientras tanto puedes usar AI_MODO=local."
            ) from None
        raise

    texto = "".join(b.text for b in respuesta.content if b.type == "text")
    uso = {
        "proveedor": "claude",
        "modelo": modelo,
        "tokens_entrada": respuesta.usage.input_tokens,
        "tokens_salida": respuesta.usage.output_tokens,
        "stop_reason": respuesta.stop_reason,
    }
    # Diagnostico: queda en el log cuanto se uso de los MAX_TOKENS
    # disponibles y por que se detuvo la respuesta, para poder ajustar el
    # limite con datos reales en vez de a ciegas la proxima vez que alguien
    # reporte "no se pudo interpretar el JSON".
    log.info("claude respondio | modelo=%s stop_reason=%s tokens_entrada=%s "
              "tokens_salida=%s/%s", modelo, uso["stop_reason"],
              uso["tokens_entrada"], uso["tokens_salida"], MAX_TOKENS)

    try:
        datos = _extraer_json(texto)
    except ValueError:
        log.warning("claude no devolvio JSON interpretable | stop_reason=%s "
                    "tokens_salida=%s/%s caracteres_respuesta=%s",
                    uso["stop_reason"], uso["tokens_salida"], MAX_TOKENS, len(texto))
        if uso["stop_reason"] == "max_tokens":
            raise ValueError(
                "El modelo no devolvio JSON interpretable: la respuesta se "
                "corto porque llego al limite de tokens de salida "
                f"(max_tokens={MAX_TOKENS}). Si esto se repite seguido, sube "
                "MAX_TOKENS en claude_service.py."
            ) from None
        raise

    datos["_uso"] = uso
    return datos
