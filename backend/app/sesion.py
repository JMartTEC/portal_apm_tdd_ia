"""
sesion.py
---------
Estado de trabajo del asistente de 7 pasos, ahora que cada paso vive en su
propia pagina (v10: front separado en un HTML por pantalla). Antes todo esto
vivia en el objeto `S` de app.js, en memoria del navegador, porque las 7
pantallas eran en realidad una sola pagina que nunca se recargaba. Al volverse
7 paginas de verdad, navegar de una a otra recarga el navegador y ese `S` se
pierde -- asi que lo que antes vivia del lado del navegador ahora vive aqui,
del lado del servidor, exactamente con el mismo espiritu que ya tenia
lotes.py: en memoria del proceso, sin persistir a disco. Es una app de un
solo usuario local -- no hace falta mas que unas variables de modulo.

Dos cosas distintas se guardan:

  1. Un valor "suelto" por nombre (`item` = el documento que se esta
     revisando en modo de un solo archivo; `alcance` = la vista previa del
     paso 2 en modo carpeta). Un documento a la vez, se sobreescribe con el
     siguiente.

  2. El trabajo hecho sobre UN documento DENTRO de un lote (modo carpeta):
     que se edito en su ficha, si se le aplico "Llenar documento", etc.
     Aparte del punto 1 porque un lote tiene VARIOS documentos y cambiar el
     selector de "Documento" en el paso 4 no debe tirar lo ya corregido en
     otro -- eso es justo lo que hacia el `S.activos` de antes (una lista
     completa en memoria), y aqui se reproduce como un diccionario indice ->
     item editado, por lote.
"""

from __future__ import annotations

from typing import Any

_VALORES: dict[str, Any] = {}
_EDICIONES_LOTE: dict[str, dict[int, dict]] = {}


def guardar(clave: str, valor: Any) -> None:
    _VALORES[clave] = valor


def obtener(clave: str) -> Any:
    return _VALORES.get(clave)


def guardar_item_lote(lote_id: str, indice: int, item: dict) -> None:
    _EDICIONES_LOTE.setdefault(lote_id, {})[indice] = item


def obtener_item_lote(lote_id: str, indice: int) -> dict | None:
    return _EDICIONES_LOTE.get(lote_id, {}).get(indice)


def obtener_indices_editados(lote_id: str) -> list[int]:
    """Indices del lote que ya tienen una edicion guardada -- lo que el panel
    fijo de habilitadores (paso 4) usa para marcar "revisado" sin tener que
    pedir cada documento uno por uno."""
    return sorted(_EDICIONES_LOTE.get(lote_id, {}).keys())


def limpiar() -> None:
    """Se llama al apretar "Inicio": borra el recorrido del asistente (no lo
    sembrado en almacen.db, que sigue igual -- ver reiniciarAsistente en el
    app.js original, mismo criterio de siempre)."""
    _VALORES.clear()
    _EDICIONES_LOTE.clear()
