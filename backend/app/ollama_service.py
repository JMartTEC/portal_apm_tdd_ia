"""
ollama_service.py
-----------------
Proveedor LOCAL de clasificacion. No requiere API key ni conexion a internet:
habla con un Ollama corriendo en la misma maquina.

Existe para que la POC sea demostrable sin token. El contrato es identico al de
claude_service.clasificar: mismas entradas, mismo JSON de salida, misma
taxonomia. El validador y el arbitraje determinista no cambian, asi que las
reglas de gobierno se siguen aplicando igual que con la API.

Limitacion real y declarada: los modelos de texto locales no leen imagenes.
En este modo los diagramas no enriquecen la clasificacion y eso se anota en
observaciones en vez de callarse.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request

from . import claude_service

log = logging.getLogger(__name__)

# Se lee en cada llamada para que los cambios desde la pantalla apliquen sin
# reiniciar el servidor.
def _host() -> str:
    return (os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").strip().rstrip("/")


def _modelo() -> str:
    return (os.getenv("OLLAMA_MODEL") or "qwen3:8b").strip()


TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))

# El contexto local es mucho mas chico que el de la API. Se recorta antes de
# enviar para no desbordar la ventana y que el modelo pierda el final.
def _max_chars() -> int:
    try:
        return int(os.getenv("OLLAMA_MAX_CHARS") or 18000)
    except ValueError:
        return 18000


MAX_CHARS = 18000  # solo para mensajes; el valor real sale de _max_chars()
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "3000"))

# Anexo al system prompt. La taxonomia y las reglas siguen viniendo de
# claude_service.construir_system_prompt(): fuente unica, un solo lugar que tocar.
ANEXO_LOCAL = """

=================================================================
MODO LOCAL
=================================================================
No escribas razonamiento, ni etiquetas <think>, ni markdown, ni explicaciones.
Tu respuesta completa debe ser un unico objeto JSON que empiece con { y
termine con }. Respeta exactamente las llaves del esquema de salida.
"""


def _recortar(texto: str) -> tuple[str, bool]:
    """Recorta por la mitad conservando inicio y final, que es donde viven
    portada y control de cambios."""
    tope = _max_chars()
    if len(texto) <= tope:
        return texto, False
    mitad = tope // 2
    return (texto[:mitad] + "\n\n[...documento recortado para el modelo local...]\n\n"
            + texto[-mitad:]), True


def _limpiar(texto: str) -> str:
    """Quita bloques de razonamiento que algunos modelos emiten igual."""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL | re.IGNORECASE)
    texto = re.sub(r"<think>.*", "", texto, flags=re.DOTALL | re.IGNORECASE)
    return texto.strip()


def _post(ruta: str, carga: dict) -> dict:
    peticion = urllib.request.Request(
        f"{_host()}{ruta}",
        data=json.dumps(carga).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


# Fallas que valen la pena reintentar UNA vez: son de red/tiempo, no del
# contenido de la respuesta. La mas comun en la practica es un timeout de
# LECTURA (el socket se conecta bien, pero Ollama tarda en mandar el primer
# byte porque tiene que cargar el modelo en memoria si llevaba un rato
# inactivo) -- y ese, en concreto, `urllib` lo lanza como `socket.timeout` /
# `TimeoutError` SIN envolverlo en `URLError`, así que un `except
# urllib.error.URLError` no lo atrapa. `ConnectionError` cubre el caso de que
# Ollama se haya reiniciado a la mitad. `URLError` sigue aqui por si el
# tropiezo es al conectar, no solo al leer.
_FALLAS_TRANSITORIAS = (TimeoutError, socket.timeout, ConnectionError, urllib.error.URLError)


def _post_con_reintento(ruta: str, carga: dict) -> dict:
    """Como `_post`, pero con un reintento ante una falla transitoria.

    Un timeout en el primer intento contra un Ollama que acaba de arrancar
    (o que llevaba un rato sin usarse y tuvo que recargar el modelo en
    memoria) no significa que Ollama este caido: casi siempre el segundo
    intento, con el modelo ya caliente, contesta bien y rapido. Un solo
    reintento -- no un bucle -- para no quedarse insistiendo indefinidamente
    contra algo que de verdad no responde; si el segundo tampoco funciona, el
    error sube tal cual para que se vea la causa real.
    """
    try:
        return _post(ruta, carga)
    except _FALLAS_TRANSITORIAS as exc:
        log.warning("Ollama no contestó a tiempo en el primer intento (%s); "
                    "reintentando una vez antes de darlo por fallido...", exc)
        return _post(ruta, carga)


def disponible() -> tuple[bool, str]:
    """Comprueba que Ollama responda y que el modelo este descargado."""
    try:
        with urllib.request.urlopen(f"{_host()}/api/tags", timeout=5) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except Exception:
        return False, (
            f"Ollama no responde en {_host()}. Abre la aplicacion de Ollama "
            f"o ejecuta 'ollama serve' en una terminal.")

    instalados = [m.get("name", "") for m in datos.get("models", [])]
    base = _modelo().split(":")[0]
    if not any(m == _modelo() or m.split(":")[0] == base for m in instalados):
        return False, (
            f"Ollama responde pero no tiene el modelo '{_modelo()}'. "
            f"Ejecuta 'ollama pull {_modelo()}'. Modelos disponibles: "
            f"{', '.join(instalados) or 'ninguno'}.")
    return True, ""


def clasificar(texto_doc: str, candidatos: dict, imagenes: list[dict]) -> dict:
    ok, motivo = disponible()
    if not ok:
        raise RuntimeError(motivo)

    texto, recortado = _recortar(texto_doc)

    mensaje_usuario = (
        f"{claude_service._bloque_candidatos(candidatos)}\n\n"
        f"=== DOCUMENTO A CLASIFICAR ===\n\n{texto}\n\n"
        f"=== FIN DEL DOCUMENTO ===\n\n"
        f"Devuelve unicamente el JSON del esquema."
    )

    carga = {
        "model": _modelo(),
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
        "messages": [
            {"role": "system",
             "content": claude_service.construir_system_prompt() + ANEXO_LOCAL},
            {"role": "user", "content": mensaje_usuario},
        ],
    }

    try:
        respuesta = _post_con_reintento("/api/chat", carga)
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "ignore")[:300]
        # Ollama viejo no conoce "think": se reintenta sin ese campo.
        if "think" in detalle.lower():
            carga.pop("think", None)
            respuesta = _post_con_reintento("/api/chat", carga)
        else:
            raise RuntimeError(f"Ollama devolvio {exc.code}: {detalle}") from None
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(
            f"Ollama no contestó a tiempo (dos intentos) en {_host()}. Si la "
            f"maquina esta lenta o el modelo es grande, prueba de nuevo -- "
            f"normalmente el siguiente intento ya lo tiene cargado en "
            f"memoria y contesta rapido.") from None
    except ConnectionError as exc:
        raise RuntimeError(
            f"Se perdió la conexión con Ollama en {_host()} (dos intentos): "
            f"{exc}. Revisa que 'ollama serve' siga corriendo.") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"No se pudo hablar con Ollama en {_host()}: {exc.reason}") from None

    crudo = _limpiar((respuesta.get("message") or {}).get("content", ""))
    if not crudo:
        raise RuntimeError("Ollama devolvio una respuesta vacia.")

    datos = claude_service._extraer_json(crudo)

    # El modelo local es solo de texto: nunca recibio las imagenes. Si aun asi
    # devolvio diagramas, los dedujo del texto que los menciona, no de verlos.
    # Un diagrama descrito sin haberlo visto es exactamente el tipo de valor
    # plausible sin respaldo que esta POC existe para evitar, asi que se
    # descarta y se dice por que.
    diagramas_inventados = len(datos.get("diagramas") or [])
    datos["diagramas"] = []

    # Observaciones honestas sobre lo que este modo NO pudo hacer.
    observaciones = list(datos.get("observaciones") or [])
    observaciones.append(
        f"Clasificado en modo local con {_modelo()} (sin API key). La capacidad de "
        f"inferencia es menor que la del modelo de la API: revisa con mas "
        f"cuidado descripcion, contexto y relaciones.")
    if imagenes:
        observaciones.append(
            f"El documento trae {len(imagenes)} imagen(es). El modelo local es "
            f"solo de texto, asi que los diagramas NO se analizaron y no "
            f"aportaron a tipo, contexto ni relaciones. Para convertirlos a "
            f"texto indexable usa AI_MODO=claude.")
    if diagramas_inventados:
        observaciones.append(
            f"Se descartaron {diagramas_inventados} descripcion(es) de diagrama "
            f"que el modelo local produjo sin haber visto ninguna imagen. "
            f"Estaban deducidas del texto, no del contenido visual.")
    if recortado:
        observaciones.append(
            f"El documento excede {_max_chars()} caracteres y se recorto por la "
            f"mitad para caber en el contexto local. Puede faltar informacion "
            f"de la parte intermedia.")
    datos["observaciones"] = observaciones

    datos["_uso"] = {
        "proveedor": "ollama",
        "modelo": _modelo(),
        "tokens_entrada": respuesta.get("prompt_eval_count", 0),
        "tokens_salida": respuesta.get("eval_count", 0),
        "imagenes_analizadas": 0,
    }
    return datos
