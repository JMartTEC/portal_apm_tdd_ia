"""
metadata_validator.py
---------------------
Barrera entre lo que devuelve el modelo y lo que se le muestra al usuario.

Hace cuatro cosas:
  1. Normaliza la forma (que existan todos los campos).
  2. Fuerza los catalogos controlados.
  3. Degrada a "No identificado" los campos declarativos sin evidencia.
  4. Calcula nivel de confianza y una bandera de revision por campo.
"""

from __future__ import annotations

import random
import string
import unicodedata

from . import fuentes, taxonomy

NO_ID_TEXTO = {"", "n/a", "na", "none", "null", "-", "sin dato", "desconocido"}


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _match_catalogo(valor, catalogo: list[str], fallback: str) -> str:
    if not isinstance(valor, str) or valor.strip().lower() in NO_ID_TEXTO:
        return fallback
    objetivo = _sin_acentos(valor.strip().lower())
    for opcion in catalogo:
        if _sin_acentos(opcion.lower()) == objetivo:
            return opcion
    for opcion in catalogo:
        if objetivo in _sin_acentos(opcion.lower()):
            return opcion
    return fallback


def _generar_id() -> str:
    sufijo = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"POC-ACT-{sufijo}"


def _tiene_evidencia(campo: str, evidencias: dict) -> bool:
    ev = evidencias.get(campo) or {}
    if not isinstance(ev, dict):
        return False
    metodo = str(ev.get("metodo", "")).lower()
    origen = str(ev.get("origen", "")).strip()
    if metodo in ("no_identificado", "inferido", ""):
        return False
    return bool(origen) and origen.lower() not in NO_ID_TEXTO


def validar(datos: dict, candidatos: dict, parsed: dict) -> dict:
    datos = dict(datos or {})
    evidencias = datos.get("evidencias") or {}
    if not isinstance(evidencias, dict):
        evidencias = {}
    observaciones = list(datos.get("observaciones") or [])

    salida = {}

    # --- id -----------------------------------------------------------------
    id_val = str(datos.get("id") or "").strip()
    id_generado = not id_val or id_val.lower() in NO_ID_TEXTO

    # Un nombre de archivo NO es un identificador oficial. El modelo tiende a
    # devolverlo cuando el documento no trae folio, y eso mete al indice claves
    # que cambian en cuanto alguien renombra el archivo. Se degrada a ID
    # temporal, que es lo que la taxonomia pide cuando no hay identificador.
    nombre_archivo = str(parsed.get("nombre", ""))
    variantes = {nombre_archivo.lower(),
                 nombre_archivo.rsplit(".", 1)[0].lower(),
                 nombre_archivo.rsplit(".", 1)[0].replace(" ", "").lower()}
    if not id_generado and id_val.replace(" ", "").lower() in variantes:
        id_generado = True
        observaciones.append(
            f"El modelo propuso '{id_val}' como identificador, pero es el nombre "
            f"del archivo, no un folio oficial. Se sustituyo por un ID temporal.")
    if id_generado:
        id_val = _generar_id()
        observaciones.append(
            "El documento no trae identificador oficial. Se asigno un ID temporal "
            "de la POC; no debe usarse como clave definitiva.")
    salida["id"] = id_val

    # --- enums --------------------------------------------------------------
    salida["tipo"] = _match_catalogo(datos.get("tipo"), taxonomy.TIPOS, "Otro")
    salida["estado"] = _match_catalogo(
        datos.get("estado"), taxonomy.ESTADOS, "No identificado")
    salida["confidencialidad"] = _match_catalogo(
        datos.get("confidencialidad"), taxonomy.CONFIDENCIALIDAD, "No identificado")

    # --- texto libre --------------------------------------------------------
    for campo, fallback in (("descripcion", "No identificada"),
                            ("version", "No identificada"),
                            ("responsable", "No identificado"),
                            ("fecha", "No identificada"),
                            ("fuente", "No identificada"),
                            ("trazabilidad", "No identificada")):
        valor = datos.get(campo)
        valor = valor.strip() if isinstance(valor, str) else ""
        salida[campo] = valor if valor and valor.lower() not in NO_ID_TEXTO else fallback

    # --- contexto -----------------------------------------------------------
    ctx_in = datos.get("contexto")
    if isinstance(ctx_in, str):
        ctx_in = {"contexto_funcional": ctx_in}
    if not isinstance(ctx_in, dict):
        ctx_in = {}
    salida["contexto"] = {
        eje: (str(ctx_in.get(eje) or "").strip() or "No identificado")
        for eje in taxonomy.EJES_CONTEXTO
    }

    # --- relaciones ---------------------------------------------------------
    relaciones, vistos = [], set()
    for rel in (datos.get("relaciones") or []):
        if not isinstance(rel, dict):
            continue
        nombre = str(rel.get("nombre") or "").strip()
        if not nombre:
            continue
        tipo = _match_catalogo(rel.get("tipo"), taxonomy.TIPOS_RELACION, "Sistema")
        clave = (tipo, nombre.lower())
        if clave in vistos:
            continue
        vistos.add(clave)
        relaciones.append({"tipo": tipo, "nombre": nombre})
    salida["relaciones"] = relaciones[:25]

    # --- arbitraje: regla determinista vs. modelo ---------------------------
    # Si el analizador encontro el valor literal en el archivo y el modelo dice
    # otra cosa, gana el analizador salvo que el modelo aporte evidencia propia.
    # Este es el caso peligroso: un documento marcado BORRADOR que el modelo
    # clasifica como Aprobado porque "se ve formal".
    # Solo los candidatos "extraido" (leidos literalmente en el contenido) tienen
    # autoridad para sobrescribir al modelo. Los "derivado" (propiedades de Word,
    # nombre de archivo) son pistas: se ofrecen en el prompt pero no ganan aqui,
    # porque una plantilla reutilizada arrastra autor y fecha del archivo original.
    fuertes = {k: v for k, v in candidatos.items() if v["metodo"] == "extraido"}

    corregidos, degradados = [], []
    for campo in taxonomy.CAMPOS_CON_EVIDENCIA_OBLIGATORIA:
        fallback = taxonomy.ATRIBUTOS[campo]["fallback"]
        actual = salida.get(campo)

        if campo in fuertes:
            det = fuertes[campo]["valor"]
            if campo in ("estado", "confidencialidad"):
                catalogo = (taxonomy.ESTADOS if campo == "estado"
                            else taxonomy.CONFIDENCIALIDAD)
                det = _match_catalogo(det, catalogo, fallback)
            if _sin_acentos(str(actual).lower()) != _sin_acentos(str(det).lower()):
                if _tiene_evidencia(campo, evidencias):
                    observaciones.append(
                        f"Discrepancia en '{campo}': el analizador leyo '{det}' en "
                        f"{fuertes[campo]['evidencia']} y el modelo propone "
                        f"'{actual}'. Se conservo el valor del modelo porque cito "
                        f"evidencia propia. Confirmar con una persona.")
                else:
                    corregidos.append(f"{campo}: '{actual}' -> '{det}'")
                    salida[campo] = det
            continue

        if actual == fallback:
            continue
        if not _tiene_evidencia(campo, evidencias):
            degradados.append(f"{campo} ('{actual}')")
            salida[campo] = fallback

    if corregidos:
        observaciones.append(
            "Se corrigieron con la evidencia literal del archivo: "
            + "; ".join(corregidos) + ".")
    if degradados:
        observaciones.append(
            "Se degradaron a 'No identificado' por falta de evidencia literal: "
            + ", ".join(degradados) + ".")

    # --- confianza ----------------------------------------------------------
    conf_in = datos.get("confianza") or {}
    confianza = {}
    for campo in taxonomy.CAMPOS_CONFIANZA:
        valor = salida.get(campo)
        tiene_valor = bool(valor) and not (
            isinstance(valor, str) and valor.startswith("No identificad"))
        # Si el modelo omitio el score, no se asume 0: se usa un piso neutro
        # que deja el campo en "requiere revision" sin fingir certeza.
        por_defecto = 60 if tiene_valor else 20
        try:
            score = int(conf_in[campo])
        except (KeyError, TypeError, ValueError):
            score = por_defecto
        score = max(0, min(100, score))
        if campo in fuertes:
            score = max(score, 85)
        elif campo in candidatos:
            score = min(max(score, 55), 69)   # pista derivada: siempre a revision
        if campo == "relaciones" and not salida["relaciones"]:
            score = min(score, 35)
        if campo == "id" and id_generado:
            score = min(score, 30)
        # Ultimo, para que ningun piso anterior lo contradiga: un campo sin
        # valor identificado nunca puede reportar confianza alta.
        if not tiene_valor:
            score = min(score, 35)
        confianza[campo] = score
    salida["confianza"] = confianza
    salida["niveles"] = {c: taxonomy.nivel_confianza(s) for c, s in confianza.items()}
    salida["requiere_revision"] = sorted(
        c for c, s in confianza.items() if s < taxonomy.UMBRALES_CONFIANZA["media"])

    # --- evidencias normalizadas -------------------------------------------
    ev_norm = {}
    for campo in taxonomy.ATRIBUTOS:
        if campo in fuertes:
            ev_norm[campo] = {
                "metodo": fuertes[campo]["metodo"],
                "origen": fuertes[campo]["evidencia"],
                "cita": fuertes[campo]["valor"],
            }
            continue
        if campo in candidatos and salida.get(campo) == candidatos[campo]["valor"]:
            ev_norm[campo] = {
                "metodo": candidatos[campo]["metodo"],
                "origen": candidatos[campo]["evidencia"],
                "cita": candidatos[campo]["valor"],
            }
            continue
        ev = evidencias.get(campo)
        if isinstance(ev, dict):
            ev_norm[campo] = {
                "metodo": (str(ev.get("metodo") or "no_identificado").lower()
                           if str(ev.get("metodo") or "").lower() in taxonomy.METODOS
                           else "inferido"),
                "origen": str(ev.get("origen") or "").strip() or "No identificado",
                "cita": str(ev.get("cita") or "").strip()[:280],
            }
        else:
            ev_norm[campo] = {"metodo": "no_identificado",
                              "origen": "No identificado", "cita": ""}
    salida["evidencias"] = ev_norm

    # --- cobertura de APM y TDD ------------------------------------------
    # Se guardan por separado a proposito: son dos fuentes institucionales
    # distintas y la decision pendiente ("que se documenta dentro del Knowledge
    # Hub y que queda como enlace") se toma por fuente, no en conjunto.
    #
    # El nivel de criticidad NO viene del modelo: se toma del catalogo. Es una
    # decision institucional ya tomada, no algo que se infiera leyendo un
    # documento suelto. Si el modelo nombra un grupo fuera del catalogo, se cae.
    for clave in ("apm", "tdd"):
        validos = set(fuentes.nombres(clave))
        vistos, filas = set(), []
        for bruto in (datos.get(clave) or [])[:15]:
            if not isinstance(bruto, dict):
                continue
            grupo = _match_catalogo(bruto.get("grupo"), list(validos), "")
            if not grupo or grupo in vistos:
                continue
            cobertura = _match_catalogo(
                bruto.get("cobertura"), fuentes.COBERTURAS, "Referenciado")
            if cobertura == "Ausente":
                continue          # un grupo ausente no es informacion, es ruido
            vistos.add(grupo)
            filas.append({
                "grupo": grupo,
                "nivel": fuentes.nivel_de(clave, grupo),
                "cobertura": cobertura,
                "detalle": str(bruto.get("detalle") or "").strip()[:400],
                "cita": str(bruto.get("cita") or "").strip()[:280],
            })
        # Criticos primero: es el orden en que un revisor los quiere ver.
        orden = {n: i for i, n in enumerate(fuentes.NIVELES)}
        filas.sort(key=lambda f: (orden.get(f["nivel"], 9), f["grupo"]))
        salida[clave] = filas

    documentados = [f["grupo"] for f in salida["apm"] + salida["tdd"]
                    if f["cobertura"] == "Documentado"
                    and f["nivel"] == "Critico"]
    if documentados:
        observaciones.append(
            "Contiene informacion critica de APM/TDD: "
            + ", ".join(documentados)
            + ". Definir si se documenta dentro del Knowledge Hub o queda como "
              "enlace a la fuente original.")

    # --- diagramas ----------------------------------------------------------
    # Se normalizan igual que las relaciones: catalogo cerrado y sin basura.
    # Un diagrama sin descripcion no aporta nada a un indice, asi que se cae.
    diagramas = []
    for bruto in (datos.get("diagramas") or [])[:12]:
        if not isinstance(bruto, dict):
            continue
        descripcion = str(bruto.get("descripcion") or "").strip()
        if not descripcion or descripcion.lower() in NO_ID_TEXTO:
            continue
        diagramas.append({
            "titulo": str(bruto.get("titulo") or "").strip() or "Sin titulo",
            "tipo_diagrama": _match_catalogo(
                bruto.get("tipo_diagrama"), taxonomy.TIPOS_DIAGRAMA, "Otro"),
            "descripcion": descripcion,
            "elementos": str(bruto.get("elementos") or "").strip(),
            "flujo": str(bruto.get("flujo") or "").strip(),
        })
    salida["diagramas"] = diagramas

    n_imagenes = parsed.get("n_imagenes", 0)
    if n_imagenes and not diagramas:
        observaciones.append(
            f"El documento tiene {n_imagenes} imagen(es) pero ninguna se "
            f"convirtio a texto. Si son diagramas, ese conocimiento no entrara "
            f"al indice de busqueda.")

    # Los avisos del extractor (PDF sin texto, hoja truncada) son cosas que un
    # revisor debe ver, no ruido interno: viajan junto a las observaciones.
    for aviso in parsed.get("avisos", []):
        observaciones.append(f"Extraccion: {aviso}")

    # --- observaciones (se cierra al final, ya con todo lo acumulado) --------
    vistas, limpias = set(), []
    for o in observaciones:
        o = str(o).strip()
        if o and o not in vistas:
            vistas.add(o)
            limpias.append(o)
    salida["observaciones"] = limpias[:15]

    # --- metricas del archivo (no contenido) --------------------------------
    salida["_documento"] = {
        "nombre_archivo": parsed.get("nombre", ""),
        "formato": parsed.get("formato", ""),
        "extension": parsed.get("extension", ""),
        "parrafos": parsed.get("n_parrafos", 0),
        "secciones": len(parsed.get("encabezados", [])),
        "tablas": parsed.get("n_tablas", 0),
        "paginas": parsed.get("n_paginas", 0),
        "imagenes_detectadas": parsed.get("n_imagenes", 0),
    }

    salida["_uso"] = datos.get("_uso", {})
    return salida
