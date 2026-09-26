/* =========================================================================
   comun.js -- v10
   Lo que antes vivia una sola vez en app.js (utilidades, cabecera, franja de
   pasos) y se cargaba junto con TODA la logica de las 11 pantallas, aunque
   solo hiciera falta una. Ahora el front es un HTML por pantalla, cada uno
   con su propio script (paso1.js, paso5.js, conciliar.js, ...), y este
   archivo es lo unico que todos cargan siempre: helpers genericos, la
   cabecera/nav, y el puente con el "estado de sesion" del servidor (ver
   sesion.py) que reemplaza al objeto `S` que antes vivia solo en memoria del
   navegador -- ahora hace falta porque cada paso es una recarga de verdad.
   ========================================================================= */

const $ = (id) => document.getElementById(id);

const esc = (t) => String(t ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const kb = (b) => b < 1024 ? `${b} B`
  : b < 1048576 ? `${(b / 1024).toFixed(0)} KB`
  : `${(b / 1048576).toFixed(1)} MB`;

function mostrarError(paso, mensaje) {
  const el = $(`error-${paso}`);
  if (!el) return;
  el.textContent = mensaje;
  el.hidden = !mensaje;
}

function _fechaLegible(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleDateString("es-MX", { day: "numeric", month: "long", year: "numeric" });
}

/* ---------- pipeline de 4 etapas (paso 2 y paso 3: extraccion, reglas,
   modelo, validacion). Compartido porque en modo "un solo documento" el
   mismo trabajo de analisis se sigue viendo repartido entre esas dos
   pantallas: paso 2 pinta extraccion/reglas, paso 3 retoma el pintado
   exactamente donde se quedo y agrega modelo/validacion. En modo carpeta
   (lote) tambien se usa, solo en paso 3. */

function fase(nombre, estado) {
  const li = document.querySelector(`#pipeline li[data-fase="${nombre}"]`);
  if (li) li.className = estado;
}

function progreso(pct, texto) {
  $("barra").style.width = `${Math.min(100, Math.max(0, pct))}%`;
  $("progreso-texto").textContent = texto;
}

/* Arma la linea de detalle de una etapa con los datos REALES que mando el
   servidor para ESE documento -- no un texto generico igual para todos. */
function detalleFase(nombre, info) {
  if (!info) return "";
  if (info.detalle) return info.detalle;
  switch (nombre) {
    case "extraccion":
      return `${info.archivo || ""}`
        + (info.formato ? ` · ${info.formato}` : "")
        + (info.paginas ? ` · ${info.paginas} páginas/hojas/diapositivas` : "");
    case "reglas": {
      const ETIQUETAS_CAMPO = {
        version: "versión", fecha: "fecha", responsable: "responsable",
        estado: "estado", confidencialidad: "confidencialidad",
      };
      const campos = info.campos_detectados || {};
      const detectados = Object.keys(campos)
        .filter((c) => ETIQUETAS_CAMPO[c])
        .map((c) => `${ETIQUETAS_CAMPO[c]}: ${campos[c]}`);
      return (detectados.length
          ? `Detectó ${detectados.join(" · ")}`
          : `${info.candidatos_detectados ?? 0} candidatos detectados por reglas`)
        + (info.contenido_truncado ? " · documento truncado por tamaño" : "");
    }
    case "modelo":
      return `${(info.caracteres_texto ?? 0).toLocaleString("es-MX")} caracteres`
        + ` · ${info.imagenes_encontradas ?? 0} imágenes`
        + (info.uso?.tokens_salida ? ` · ${info.uso.tokens_salida} tokens de respuesta` : "");
    case "validacion":
      return info.campos_por_revisar
        ? `${info.campos_por_revisar} campo(s) por revisar`
        : "sin pendientes";
    default:
      return "";
  }
}

function pintarEtapas(etapas) {
  ["extraccion", "reglas", "modelo", "validacion"].forEach((nombre) => {
    const info = etapas && etapas[nombre];
    const li = document.querySelector(`#pipeline li[data-fase="${nombre}"]`);
    const detalle = li && li.querySelector(".detalle-fase");
    if (!info) {
      if (li) li.className = "";
      if (detalle) detalle.textContent = "";
      return;
    }
    if (li) li.className = info.estado === "ok" ? "hecha" : "fallida";
    if (detalle) detalle.textContent = detalleFase(nombre, info);
  });
}

/* Mismo lenguaje visual que ya usaba la tabla de un lote: un chip por lo que
   se encontro (o no) al ligar el documento con el APM Portafolio. */
function chipAplicativo(info) {
  if (!info || info.sin_libro || !info.disponible) {
    return info && info.disponible === false && info.motivo && !info.sin_libro
      ? `<span class="etiqueta aviso-chip">${esc(info.motivo)}</span>` : "";
  }
  if (info.identificado) {
    return `<span class="etiqueta ok-chip">#${esc(info.numero || "")} `
      + `${esc(info.nombre_aplicativo || "")}</span>`;
  }
  if (info.valido === false) {
    return `<span class="etiqueta aviso-chip">${esc(info.motivo || "sin usar")}</span>`;
  }
  return `<span class="etiqueta aviso-chip">no se identificó ningún aplicativo</span>`;
}

function pintarHallazgoVivo(info) {
  const cont = $("hallazgo-vivo");
  if (!cont) return;
  const chip = chipAplicativo(info);
  if (!chip) { cont.hidden = true; cont.classList.remove("visible"); return; }
  cont.innerHTML = `Aplicativo identificado: ${chip}`;
  cont.hidden = false;
  requestAnimationFrame(() => cont.classList.add("visible"));
}

const ORDEN_ETAPAS = ["extraccion", "reglas", "modelo", "validacion"];
const ETIQUETAS_ETAPA = {
  extraccion: "Extrayendo el contenido…",
  reglas: "Aplicando reglas de detección…",
  modelo: "Clasificando con IA…",
  validacion: "Validando y arbitrando…",
};

/* Guarda en la sesion del servidor el resultado de un documento excluido
   (destino, no fuente -- el propio libro de APM o un TDD) y entra al
   paso 4. Se usa desde paso 2 (ahi se detecta, antes de llegar siquiera a
   clasificar con IA) y como red de seguridad desde paso 3. */
async function guardarExcluidoYContinuar(r) {
  const esApm = r.tipo_excluido === "apm";
  const ref = r.referencia || {};
  let motivo, fecha = "";
  if (r.referencia_actualizada) {
    fecha = ref.actualizado_en ? _fechaLegible(ref.actualizado_en) : "";
    motivo = "Este documento ya está en el sistema"
      + (fecha ? ` · referencia actualizada el ${fecha}` : "") + ".";
  } else {
    motivo = `Es ${esApm ? "el propio libro de APM" : "un TDD"} — es destino, no `
      + "una fuente, así que no se manda a clasificar."
      + (ref.motivo ? ` (no se pudo fijar como referencia: ${ref.motivo})` : "");
  }
  const resultado = {
    modoLote: false, loteId: null, nombres: [],
    activos: [],
    activosOmitidos: [r.referencia_actualizada
      ? { nombre: r.nombre, motivo, mismoEnSistema: true, fecha, ruta: Estado.get("ruta") }
      : { nombre: r.nombre, motivo }],
    indice: 0,
  };
  await guardarResultadoSesion(resultado);
  Estado.set("vivoId", "");
  Estado.set("indice", 0);
  Estado.set("alcanzado", 4);
  location.href = "/paso/4";
}

/* Guarda el resultado ya clasificado de un solo documento y entra al
   paso 4. Vive en paso 3 (ahi es normalmente donde termina la IA), pero
   tambien se usa desde paso 2 como red de seguridad si el trabajo llegara a
   terminar completo antes de que la persona alcance a ver el paso 3. */
async function guardarClasificadoYContinuar(r) {
  const resultado = {
    modoLote: false, loteId: null,
    nombres: [r.activo._documento?.nombre_archivo || Estado.get("ruta")],
    activos: [{
      nombre: r.activo._documento?.nombre_archivo || Estado.get("ruta"),
      activo: r.activo, texto: "", markdown: r.markdown,
      base: r.nombre_sugerido, ruta: Estado.get("ruta"),
    }],
    activosOmitidos: [],
    indice: 0,
  };
  await guardarResultadoSesion(resultado);
  Estado.set("vivoId", "");
  Estado.set("indice", 0);
  Estado.set("alcanzado", 4);
  location.href = "/paso/4";
}

async function pedir(url, opciones) {
  const r = await fetch(url, opciones);
  let cuerpo;
  try { cuerpo = await r.json(); } catch { cuerpo = {}; }
  if (!r.ok) {
    const mensaje = typeof cuerpo.detail === "string" ? cuerpo.detail : `Error ${r.status}`;
    const e = new Error(mensaje);
    e.cuerpo = cuerpo;
    throw e;
  }
  return cuerpo;
}

const json = (datos) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(datos),
});

/* ---------- estado del asistente (banderas chicas, por navegador) ---------
   Solo identificadores y valores sueltos -- nunca el documento completo, que
   puede traer diagramas en base64 y pesar varios MB (ver Estado del servidor
   mas abajo). Vive en sessionStorage: sobrevive a navegar entre paginas de
   esta pestaña, se pierde al cerrarla -- que es exactamente lo que antes
   pasaba al recargar la SPA de un solo archivo. */
const Estado = {
  get(clave, porDefecto = "") {
    const v = sessionStorage.getItem(`estado.${clave}`);
    return v === null ? porDefecto : v;
  },
  getBool(clave, porDefecto = false) {
    const v = sessionStorage.getItem(`estado.${clave}`);
    return v === null ? porDefecto : v === "1";
  },
  getNum(clave, porDefecto = 0) {
    const v = sessionStorage.getItem(`estado.${clave}`);
    return v === null ? porDefecto : Number(v);
  },
  set(clave, valor) { sessionStorage.setItem(`estado.${clave}`, String(valor)); },
  setBool(clave, valor) { sessionStorage.setItem(`estado.${clave}`, valor ? "1" : "0"); },
  borrar(clave) { sessionStorage.removeItem(`estado.${clave}`); },
};

function limpiarEstadoAsistente() {
  ["modo", "ruta", "rutaApm", "rutaApmAuto", "recursivo", "escribir",
   "loteId", "indice", "alcanzado", "avisoInicio"]
    .forEach((k) => Estado.borrar(k));
  fetch("/api/sesion-limpiar", { method: "POST" }).catch(() => {});
}

/* ---------- estado del asistente (el documento en trabajo, del lado del
   servidor) ---------------------------------------------------------------
   Antes era `S.activos[S.indice]`, una entrada de un arreglo que vivia en
   memoria del navegador mientras durara la SPA. Ahora cada paso es su propia
   pagina, asi que ese objeto -- que puede traer el texto completo del
   documento y sus diagramas en base64 -- se guarda del lado del servidor
   (ver sesion.py) en vez de en sessionStorage, para no pelear con el limite
   de tamaño del navegador. Es en memoria del proceso, igual que los lotes:
   no persiste si el servidor se reinicia. */
async function guardarSesion(clave, valor) {
  try { await pedir(`/api/sesion/${clave}`, json(valor)); } catch (e) { console.error(e); }
}
async function cargarSesion(clave) {
  try { return await pedir(`/api/sesion/${clave}`); } catch { return null; }
}

/* Un lote (modo carpeta) trae VARIOS documentos -- cambiar el selector de
   "Documento" en el paso 4 no debe tirar lo que ya se corrigio en otro. Esto
   guarda/lee la edicion de UN documento del lote, por indice, aparte del
   resultado original que ya vive en lotes.py. */
async function guardarItemLoteSesion(loteId, indice, item) {
  try { await pedir(`/api/sesion/lote/${loteId}/${indice}`, json(item)); } catch (e) { console.error(e); }
}
async function cargarItemLoteSesion(loteId, indice) {
  try { return await pedir(`/api/sesion/lote/${loteId}/${indice}`); } catch { return null; }
}

/* ---------- el "resultado" del analisis (paso 3 -> 4 -> 5 -> 6 -> 7) ------
   Reemplaza a S.activos / S.activosOmitidos / S.indice / S.loteId. Misma
   forma para modo archivo y modo carpeta, para que el paso 4 en adelante no
   tenga que preguntarse en cual modo esta:

     { modoLote, loteId, nombres, activos, activosOmitidos, indice }

   En modo archivo `activos` trae el (0 o 1) resultado completo, ya listo.
   En modo carpeta `activos` viaja VACIO -- el lote ya tiene todo en
   lotes.py, asi que releerlo de ahi (con construirActivosDeLote) evita
   guardar los mismos datos dos veces. `nombres` es solo para pintar el
   selector de "Documento" sin tener que pedir el detalle completo del lote
   nada mas para llenar una lista. */
async function cargarResultadoSesion() {
  return await cargarSesion("resultado");
}
async function guardarResultadoSesion(resultado) {
  await guardarSesion("resultado", resultado);
}

/* Mismo criterio que `cargarResultadosLote()` en el app.js de la v9: un
   documento con aplicativo invalido (sin identificar, sin datos utiles, o ya
   visto sin novedad) no cuenta como algo que revisar. */
function construirActivosDeLote(l) {
  const util = (r) => r.ok && r.activo && r.aplicativo?.valido !== false;
  const activos = l.resultados.filter(util).map((r) => ({
    nombre: r.nombre, activo: r.activo, texto: r.texto || "",
    markdown: null, base: null, archivos: r.archivos, ruta: r.ruta || "",
  }));
  const activosOmitidos = l.resultados
    .filter((r) => r.excluido || (r.ok && r.activo && r.aplicativo?.valido === false))
    .map((r) => ({
      nombre: r.nombre,
      motivo: r.excluido ? r.motivo : (r.aplicativo?.motivo || "no se usó"),
    }));
  return { activos, activosOmitidos };
}

/* El documento que se esta revisando AHORA MISMO. En modo lote, si ya se
   habia editado (ficha corregida, llenado aplicado, aplicativo manual...) se
   trae esa version -- cambiar de documento en el selector y volver no tira
   lo ya hecho, que es justo lo que garantizaba tener todo en un solo arreglo
   en memoria en la v9. */
async function cargarDocumentoActual(resultado) {
  if (!resultado.modoLote) {
    return resultado.activos[resultado.indice] || null;
  }
  const editado = await cargarItemLoteSesion(resultado.loteId, resultado.indice);
  if (editado) return editado;
  const l = await pedir(`/api/lote/${resultado.loteId}?detalle=true`);
  const { activos } = construirActivosDeLote(l);
  return activos[resultado.indice] || null;
}

async function guardarDocumentoActual(resultado, item) {
  if (resultado.modoLote) {
    await guardarItemLoteSesion(resultado.loteId, resultado.indice, item);
  } else {
    resultado.activos[resultado.indice] = item;
    await guardarResultadoSesion(resultado);
  }
}

/* ---------- catalogos (taxonomia, aplicativos, documentos de referencia) --
   Se piden una sola vez por pagina y se guardan en cache -- no cambian
   mientras dura la sesion del navegador. */
let _catalogosPromise = null;
function cargarCatalogos() {
  if (!_catalogosPromise) {
    _catalogosPromise = pedir("/api/taxonomy").catch(() => (
      { tipos: [], estados: [], confidencialidad: [], extensiones: [],
        carpeta_salida: "_ia-ready", proveedor: "" }));
  }
  return _catalogosPromise;
}

let _catalogoAplicativosPromise = null;
function cargarCatalogoAplicativos() {
  if (!_catalogoAplicativosPromise) {
    _catalogoAplicativosPromise = pedir("/api/almacen/resumen")
      .then((r) => r.cobertura || [])
      .catch(() => []);
  }
  return _catalogoAplicativosPromise;
}

let _docsReferenciaPromise = null;
function cargarDocsReferencia() {
  if (!_docsReferenciaPromise) {
    _docsReferenciaPromise = pedir("/api/docs-referencia")
      .then((r) => {
        const sello = $("sello-docs");
        if (sello) { sello.textContent = "Progreso de APM y TDD"; sello.hidden = false; }
        return r;
      })
      .catch(() => {
        const sello = $("sello-docs");
        if (sello) sello.hidden = true;
        return null;
      });
  }
  return _docsReferenciaPromise;
}

/* La liga con el APM no se le pide a nadie: se detecta sola contra lo que ya
   esta sembrado en la base (panel "APM y TDD"). Se vuelve a consultar justo
   antes de lanzar cada analisis, para que un cambio de aplicativo se refleje
   sin que el usuario tenga que avisar nada. */
async function detectarApmAutomatico() {
  try {
    const r = await pedir("/api/almacen/resumen");
    return (r.resumen && r.resumen.origen_apm) || "";
  } catch {
    return "";
  }
}

/* ═════════ compartido entre "Comparar APM" y "Comparar TDD Nivel 2" ═══════
   Antes vivian en conciliar.js, que tdd2.js reusaba como variables globales
   porque los dos scripts se cargaban juntos en la misma pagina (ver la nota
   de la v9 en tdd2.js). Ahora cada uno es su propia pagina y ya no comparten
   script, asi que lo que de verdad es comun -- el semaforo de estados de un
   conflicto, abrir una etapa, y subir un archivo -- se queda aqui. */

const ESTADOS = {
  coincide:          { texto: "Ya coincide",            clase: "e-ok" },
  propuesto:         { texto: "Propuesto",              clase: "e-prop" },
  sobre_sin_info:    { texto: "Pisa «Sin información»", clase: "e-ambar" },
  conflicto_fuentes: { texto: "Los documentos difieren", clase: "e-rojo" },
  conflicto_apm:     { texto: "Difiere del APM",        clase: "e-rojo" },
  bloqueado:         { texto: "No se puede escribir",   clase: "e-gris" },
};

function abrirEtapa(id) { $(id).classList.remove("apagada"); }

/* El navegador NO entrega la ruta real de un archivo subido: por seguridad
   la esconde, y solo da el contenido. Subir copia el archivo a la carpeta de
   la app y devuelve una ruta que el resto del flujo ya puede usar igual. */
async function subir(archivos, etiqueta, mostrarErrorEn) {
  if (!archivos || !archivos.length) return [];
  const cuerpo = new FormData();
  for (const a of archivos) cuerpo.append("files", a, a.name);

  const r = await fetch("/api/conciliar/subir", { method: "POST", body: cuerpo });
  let datos;
  try { datos = await r.json(); } catch { datos = {}; }
  if (!r.ok) throw new Error(datos.detail || `Error ${r.status} al subir`);

  if ((datos.rechazados || []).length && mostrarErrorEn) {
    mostrarErrorEn(`${datos.rechazados.length} de ${etiqueta} no se pudieron usar: `
      + datos.rechazados.map((x) => `${x.nombre} (${x.motivo})`).join("; "));
  }
  return datos.archivos || [];
}

/* ═════════ selector manual de aplicativo (paso 5 y 6) ═════════
   El amarre automatico puede fallar o quedar en duda. Este selector deja
   elegir a mano contra cual aplicativo comparar. Vive aqui porque el paso 5
   y el paso 6 lo usan identico -- solo cambia el sufijo ("5"/"6") y cual
   `item` esta en pantalla en ese momento. */
function pintarSelectorManual(sufijo, item) {
  const cont = $(`selector-manual-${sufijo}`);
  const sel = $(`sel-aplicativo-${sufijo}`);
  const nota = $(`nota-manual-${sufijo}`);
  const candCont = $(`candidatos-manual-${sufijo}`);
  const candLista = $(`lista-candidatos-${sufijo}`);
  if (!item || !cont || !sel || !nota) return;

  cont.hidden = false;
  sel.disabled = false;
  cargarCatalogoAplicativos().then((cat) => {
    const info = item.activo?._apm || {};
    const actual = String(info.numero || "");

    /* En cuanto se elige uno a mano, la respuesta del servidor deja de traer
       "candidatos" -- el aplicativo ya quedo identificado, asi que para el
       backend ya no hay ambiguedad que resolver. Pero la persona sigue
       queriendo poder ver -- y cambiar a -- cualquiera de los que el
       documento mencionaba, no solo el que se eligio. Por eso se guardan una
       sola vez en el propio `item` (que ya viaja con el guardado de sesion
       de cada documento, y por lo tanto entre pasos 4/5/6 del mismo
       documento) y de ahi en adelante se usa esa copia, viva o no la
       respuesta actual del servidor los siga trayendo. */
    if ((info.candidatos || []).length) item._candidatosVistos = info.candidatos;
    const candidatos = item._candidatosVistos || [];

    const yaListados = new Set(candidatos.map((c) => String(c.numero)));
    const opcion = (a) => `<option value="${esc(a.numero)}"`
      + `${String(a.numero) === actual ? " selected" : ""}>`
      + `#${esc(a.numero)} · ${esc(a.nombre)}</option>`;

    sel.innerHTML = `<option value="">— elegir habilitador —</option>`
      + (candidatos.length
          ? `<optgroup label="El documento menciona más de uno">`
            + candidatos.map(opcion).join("") + `</optgroup>`
          : "")
      + `<optgroup label="Todos los habilitadores (${cat.length})">`
      + cat.filter((a) => !yaListados.has(String(a.numero))).map(opcion).join("")
      + `</optgroup>`;

    /* Cuadro fijo arriba de todo (ver paso-N.html) con los candidatos que el
       documento SI menciona. Se queda visible aunque ya se haya elegido uno
       (marcado como "activo"), para poder cambiar a otro de los mencionados
       sin perderlos de vista. El combo se deja igual, debajo, como respaldo
       para cuando el que se busca no es de los mencionados. */
    if (candCont && candLista) {
      if (candidatos.length) {
        candLista.innerHTML = candidatos.map((a) => `
          <li class="item-habilitador${String(a.numero) === actual ? " activo" : ""}"
              data-numero="${esc(a.numero)}">
            <span class="lh-nombre">#${esc(a.numero)} · ${esc(a.nombre)}</span>
          </li>`).join("");
        candLista.querySelectorAll("li").forEach((li) =>
          li.addEventListener("click", () => {
            if (li.dataset.numero === actual) return;
            sel.value = li.dataset.numero;
            $(`btn-aplicar-manual-${sufijo}`).click();
          }));
        candCont.hidden = false;
      } else {
        candCont.hidden = true;
        candLista.innerHTML = "";
      }
    }

    if (info.identificado && info.senal === "manual") {
      nota.textContent = `Comparando contra #${esc(info.numero)} · `
        + `${esc(info.nombre_aplicativo)} (elegido a mano). Puedes cambiar a `
        + `otro de los de arriba cuando quieras.`;
    } else if (info.identificado) {
      nota.textContent = `Reconocido automáticamente: #${esc(info.numero)} · `
        + `${esc(info.nombre_aplicativo)}. Si no es el que corresponde, elige `
        + `otro de la lista.`;
    } else if (candidatos.length) {
      nota.textContent = `El documento menciona ${candidatos.length} `
        + `habilitadores distintos y no se puede saber solo cuál es el suyo: `
        + `elige uno de los de arriba.`;
    } else {
      nota.textContent = `No se pudo reconocer a qué habilitador pertenece `
        + `este documento: elige uno de los ${cat.length} para comparar sus `
        + `campos contra la referencia.`;
    }
  });
}

/* Aplica el aplicativo elegido a mano. Muta `item` y devuelve true/false --
   quien llama es quien sabe que repintar despues (la cabecera de modulo 5 o
   la de modulo 6 son pantallas distintas) y quien debe guardar el item en la
   sesion del servidor. */
async function usarAplicativoManual(sufijo, item, rutaApm) {
  const sel = $(`sel-aplicativo-${sufijo}`);
  const btn = $(`btn-aplicar-manual-${sufijo}`);
  if (!item || !sel || !sel.value) return false;
  const numero = sel.value;

  btn.disabled = true;
  try {
    const cuerpo = { ruta_apm: rutaApm, numero, nombre: item.nombre };
    if (item.ruta) cuerpo.ruta = item.ruta;
    else cuerpo.doc = item.activo._doc_snapshot || null;

    const r = await pedir("/api/vincular-manual", json(cuerpo));
    item.activo._apm = r.apm;
    item.activo._llenado = r.llenado;
    item.activo.ficha_apm = {};
    item.activo.ficha_tdd = {};
    item.cambiosLlenado = null;
    item.markdown = null;
    return true;
  } catch (e) {
    mostrarError(sufijo === "6" ? 6 : 5, e.message);
    return false;
  } finally {
    btn.disabled = false;
  }
}

/* ═════════ llenado -- estado vivo y "Hacer nueva versión" (paso 5 y 6) ═════ */

const ESTADO_TEXTO = {
  propuesto: "Propuesto · pendiente de llenar",
  extraido: "Extraído del documento",
  heredado: "Ya está en el APM",
  diferente: "El documento dice otra cosa · revisar",
  faltante: "Falta",
  manual: "Capturado a mano",
  calculado: "Valor calculado (fórmula) · solo lectura",
};

function estadoVivo(item, fuente, campo) {
  if (campo.estado === "calculado") return "calculado";
  const ficha = item.activo[`ficha_${fuente}`] || {};
  const puesto = String(ficha[campo.clave] ?? "").trim();
  if (!puesto) return campo.valor ? "propuesto" : campo.estado;
  if (puesto !== campo.valor) return "manual";
  return campo.estado;
}

const _ESTADOS_ESCRIBIBLES_NV = new Set(["faltante", "extraido"]);

function _pendientesNuevaVersion(item, fuente) {
  const p = item?.activo?._llenado?.[fuente];
  if (!p || !p.grupos) return [];
  const ficha = item.activo[`ficha_${fuente}`] || {};
  const escritos = item[fuente === "apm" ? "nvApmEscritos" : "nvTddEscritos"] || {};
  const claves = [];
  for (const g of p.grupos) {
    for (const c of g.campos) {
      if (!_ESTADOS_ESCRIBIBLES_NV.has(c.estado)) continue;
      const valor = String(ficha[c.clave] ?? "").trim();
      if (!valor) continue;
      if (escritos[c.clave] === valor) continue;
      claves.push(c.clave);
    }
  }
  return claves;
}

function pintarBotonNuevaVersion(item, sufijo, fuente, elegible, motivoNoElegible) {
  const btn = $(`btn-nueva-version-${sufijo}`);
  if (!item || !btn) return;
  if (!elegible) {
    btn.disabled = true;
    btn.title = motivoNoElegible;
    return;
  }
  const pendientes = _pendientesNuevaVersion(item, fuente);
  btn.disabled = pendientes.length === 0;
  btn.title = pendientes.length
    ? `Hay ${pendientes.length} campo(s) nuevo(s) listos para una versión nueva`
    : (fuente === "apm"
        ? "No hay campos vacíos del libro con un dato nuevo que escribir todavía"
        : "No hay campos vacíos del TDD con un dato nuevo que escribir todavía");
}

async function hacerNuevaVersion(item, sufijo, fuente, endpoint, payloadExtra) {
  const btn = $(`btn-nueva-version-${sufijo}`);
  const okEl = $(`nueva-version-ok-${sufijo}`);
  const errEl = $(`nueva-version-error-${sufijo}`);
  okEl.hidden = true;
  errEl.hidden = true;
  btn.disabled = true;
  try {
    const r = await pedir(endpoint, json({ activo: item.activo, ...payloadExtra }));
    if (r.sin_cambios) {
      okEl.textContent = r.mensaje;
    } else {
      const clave = fuente === "apm" ? "nvApmEscritos" : "nvTddEscritos";
      item[clave] = item[clave] || {};
      const ficha = item.activo[`ficha_${fuente}`] || {};
      (r.claves_escritas || []).forEach((c) => { item[clave][c] = String(ficha[c] ?? "").trim(); });
      okEl.textContent = `Se guardó una versión nueva: ${r.nombre} `
        + `(${r.aplicados.length} celda(s) escrita(s)). El original no se tocó: `
        + `${r.original_intacto}`;
      if (r.base_actualizada) {
        okEl.textContent += ` · La base se actualizó con la nueva versión.`;
      }
    }
    okEl.hidden = false;
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

/* ═════════ cabecera: franja de pasos, sellos, arranque de cada pagina ═════ */

function _alcanzado() {
  return Estado.getNum("alcanzado", 1);
}

function _pintarChips() {
  const actualStr = document.body.dataset.paso;
  if (!actualStr) return;   // pantallas sin franja de pasos (config/conciliar/tdd2/docs)
  const actual = Number(actualStr);
  if (actual > _alcanzado()) Estado.set("alcanzado", actual);
  const alcanzado = _alcanzado();

  document.querySelectorAll(".paso-chip").forEach((c) => {
    const destino = Number(c.dataset.ir);
    c.classList.toggle("activo", destino === actual);
    c.classList.toggle("hecho", destino < actual);
    const bloqueado = destino > alcanzado;
    c.classList.toggle("bloqueado", bloqueado);
    c.title = bloqueado ? "Todavía no llegas a este paso" : "";
    c.addEventListener("click", (e) => {
      if (Number(c.dataset.ir) > _alcanzado()) {
        e.preventDefault();
        mostrarError(actual, `Todavía no llegas al paso ${c.dataset.ir}. `
          + `Termina el paso ${_alcanzado()} primero.`);
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  _pintarChips();

  cargarCatalogos().then((d) => {
    const prov = $("sello-proveedor");
    if (prov) {
      prov.textContent = d.proveedor === "ollama" ? "Modo local" : "Claude API";
      prov.hidden = false;
    }
    const notaFormatos = $("nota-formatos");
    if (notaFormatos && d.extensiones) {
      notaFormatos.textContent = `Formatos que se pueden escanear: ${d.extensiones.join(", ")}.`;
    }
    const nombreSalida = $("nombre-salida");
    if (nombreSalida && d.carpeta_salida) nombreSalida.textContent = d.carpeta_salida;
  });

  cargarDocsReferencia();

  const btnInicio = $("btn-inicio");
  if (btnInicio) btnInicio.addEventListener("click", limpiarEstadoAsistente);
});
