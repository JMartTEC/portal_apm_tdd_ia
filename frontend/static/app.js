/* =========================================================================
   app.js -- v4
   Asistente de 6 pasos (el 5 es el llenado de APM y TDD). Un solo objeto de estado; cada paso lee de ahi y
   escribe ahi. No hay framework a proposito: la POC debe poder abrirse y
   entenderse sin instalar nada.
   ========================================================================= */

const $ = (id) => document.getElementById(id);

const S = {
  modo: "archivo",        // archivo | carpeta
  ruta: "",
  rutaApm: "",            // con la que de verdad se escanea (auto o manual)
  rutaApmAuto: "",        // detectada sola desde lo ya sembrado en la base
  catalogoAplicativos: null, // lista de {numero,nombre,id_habilitador,...} para el selector manual
  archivoSubido: null,
  recursivo: true,
  escribir: true,
  catalogos: {},
  alcance: null,          // resultado de /api/explorar
  loteId: null,
  activos: [],            // [{nombre, activo, markdown}]
  activosOmitidos: [],    // excluidos (son el propio APM/TDD) o sin usar (sin
                          // identificar, sin datos, o ya vistos sin novedad)
  indice: 0,
};

/* ---------- utilidades ---------- */

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

/* Hasta que paso se ha llegado DE VERDAD. Solo lo mueve `alcanzar()`, que se
   llama desde los botones de Continuar -- nunca desde un clic en un chip.

   Sin esto se podia entrar al paso 4 sin haber analizado nada y la pantalla
   mostraba su cascaron: el titulo, un selector de documento vacio y una nota
   hablando de campos que no existian. No era que se hubiera perdido el
   contexto; era que nunca hubo, y la pantalla no lo decia. */
S.alcanzado = 1;

function pintarChips(actual) {
  document.querySelectorAll(".paso-chip").forEach((c) => {
    const destino = Number(c.dataset.ir);
    c.classList.toggle("activo", destino === actual);
    c.classList.toggle("hecho", destino < actual);
    const bloqueado = destino > S.alcanzado;
    c.classList.toggle("bloqueado", bloqueado);
    c.disabled = bloqueado;
    c.title = bloqueado ? "Todavía no llegas a este paso" : "";
  });
}

function alcanzar(n) {
  S.alcanzado = Math.max(S.alcanzado, n);
}

function irA(n) {
  // Un paso al que no se ha llegado no se abre: se avisa y no pasa nada. Es
  // mejor un mensaje corto que una pantalla vacia que parece rota.
  if (n > S.alcanzado) {
    mostrarError(S.alcanzado,
      `Todavía no llegas al paso ${n}. Termina el paso ${S.alcanzado} primero.`);
    return;
  }
  alcanzar(n);
  for (let i = 1; i <= 7; i++) $(`paso-${i}`).hidden = (i !== n);
  pintarChips(n);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll("[data-ir]").forEach((b) =>
  b.addEventListener("click", () => irA(Number(b.dataset.ir))));

pintarChips(1);

async function pedir(url, opciones) {
  const r = await fetch(url, opciones);
  let cuerpo;
  try { cuerpo = await r.json(); } catch { cuerpo = {}; }
  if (!r.ok) {
    // `detail` normalmente es un texto, pero en el pipeline de analisis
    // (ver /api/analyze) el cuerpo completo trae ademas el estado de cada
    // etapa -- se guarda en el error para que quien llame pueda pintar el
    // pipeline con precision en vez de solo mostrar un mensaje.
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

/* ---------- arranque ---------- */

fetch("/api/taxonomy").then((r) => r.json()).then((d) => {
  S.catalogos = d;

  const prov = $("sello-proveedor");
  // "· sin API key" ya no hace falta aqui: el boton de junto ahora se llama
  // "Configuración API key", que dice lo mismo sin ocupar espacio del sello.
  prov.textContent = d.proveedor === "ollama" ? "Modo local" : "Claude API";
  prov.hidden = false;

  // La lista de formatos soportados se movio del sello de arriba (que ahora
  // es el de documentos de referencia) a una nota en el Paso 1, que es donde
  // de verdad hace falta saberlo -- justo antes de escoger que escanear.
  $("nota-formatos").textContent =
    `Formatos que se pueden escanear: ${d.extensiones.join(", ")}.`;

  $("nombre-salida").textContent = d.carpeta_salida;
}).catch(() => {});

/* La liga con el APM no se le pide a nadie: se detecta sola contra lo que ya
   esta sembrado en la base (panel "APM y TDD") y no hay ningun control en
   pantalla para esto -- ni una nota, ni una ruta que escribir. Se vuelve a
   consultar justo antes de lanzar cada análisis (single archivo o lote) y
   cuando el propio panel de APM y TDD termina de sembrar una base nueva (ver
   conciliar.js), para que un cambio de aplicativo se refleje sin que el
   usuario tenga que avisar nada ni tocar nada. */
async function detectarApmAutomatico() {
  try {
    const r = await pedir("/api/almacen/resumen");
    S.rutaApmAuto = (r.resumen && r.resumen.origen_apm) || "";
  } catch {
    S.rutaApmAuto = "";
  }
  return S.rutaApmAuto;
}

window.detectarApmAutomatico = detectarApmAutomatico;
detectarApmAutomatico();

/* ---------- documentos de referencia (carpeta docs/) ---------- */

let docsReferenciaCache = null;

async function cargarDocsReferencia() {
  const sello = $("sello-docs");
  try {
    const r = await pedir("/api/docs-referencia");
    docsReferenciaCache = r;
    // Antes decia "{N} documentos de referencia" (el conteo). Ahora es un
    // rotulo fijo -- el conteo exacto se sigue viendo adentro, al abrir el
    // panel, pero aqui arriba ya no hace falta.
    sello.textContent = "APM y TDD";
    sello.hidden = false;
  } catch {
    sello.hidden = true;
  }
}
cargarDocsReferencia();

function pintarDocsReferencia() {
  const d = docsReferenciaCache;
  if (!d) return;

  const lista = d.habilitadores || [];
  $("resumen-docs-apm").textContent = lista.length
    ? `${lista.length} habilitador${lista.length === 1 ? "" : "es"} sembrado${lista.length === 1 ? "" : "s"} como referencia.`
    : "Todavía no se ha sembrado ningún habilitador (sube el libro de APM en "
      + "Inicio, o cárgalo a mano en «Comparar APM y TDD»).";

  const cuadroApm = $("cuadro-apm-referencia");
  if (d.apm_nombre) {
    $("nombre-apm-referencia").textContent = d.apm_nombre;
    cuadroApm.hidden = false;
  } else {
    cuadroApm.hidden = true;
  }

  $("titulo-habilitadores").hidden = lista.length === 0;
  $("lista-docs-aplicativos").innerHTML = lista.length
    ? lista.map((h) => `
      <div class="cuadro-referencia">
        <span class="cuadro-referencia-etiqueta">Habilitador</span>
        <b class="cuadro-referencia-nombre">${esc(h.habilitador || h.id_habilitador || "—")}</b>
        <span class="cuadro-referencia-etiqueta cuadro-referencia-tdd-etiqueta">TDD</span>
        ${h.tdd_nombre
          ? `<span class="cuadro-referencia-tdd">${esc(h.tdd_nombre)}</span>`
          : `<span class="cuadro-referencia-tdd cuadro-referencia-pendiente">Sin TDD todavía</span>`}
      </div>`).join("")
    : "";
}

function abrirDocs() {
  for (let i = 1; i <= 7; i++) $(`paso-${i}`).hidden = true;
  $("panel-config").hidden = true;
  $("panel-conciliar").hidden = true;
  $("panel-tdd2").hidden = true;
  $("pasos-nav").hidden = true;
  pintarDocsReferencia();
  $("panel-docs").hidden = false;
  $("sello-docs").classList.add("activo");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function cerrarDocs() {
  $("panel-docs").hidden = true;
  $("pasos-nav").hidden = false;
  $("sello-docs").classList.remove("activo");
  irA(1);
}

$("sello-docs").addEventListener("click", abrirDocs);
$("btn-cerrar-docs").addEventListener("click", cerrarDocs);
$("btn-volver-docs").addEventListener("click", cerrarDocs);

/* ---------- Inicio: reinicia el asistente de pasos, no lo sembrado ---------- */

/* Reinicia solo el recorrido de los 7 pasos (ruta, archivo, resultados de
   analisis): lo que ya esta sembrado en la base (almacen.db, via el panel de
   Comparar APM y TDD) no se toca -- eso sigue igual aunque reinicies,
   tal como pasa hoy si solo recargas la pagina. Sirve para arrancar una
   consulta nueva desde cualquier paso sin tener que recargar de verdad. */
function reiniciarAsistente() {
  S.modo = "archivo";
  S.ruta = "";
  S.archivoSubido = null;
  S.recursivo = true;
  S.escribir = true;
  S.alcance = null;
  S.loteId = null;
  S.activos = [];
  S.activosOmitidos = [];
  S.indice = 0;
  S.alcanzado = 1;

  $("ruta").value = "";
  $("input-archivo").value = "";
  $("recursivo").checked = true;
  $("escribir").checked = true;
  fijarModo("archivo");

  for (const n of [1, 2, 3, 4, 5, 6]) mostrarError(n, "");
  $("resumen-alcance").innerHTML = "";
  $("tabla-alcance").tBodies[0].innerHTML = "";
  $("det-descartados").hidden = true;
  $("tabla-avance").tBodies[0].innerHTML = "";
  $("envoltura-avance").hidden = true;
  $("btn-continuar-3").hidden = true;
  $("tarjeta-igual-sistema").hidden = true;
  $("tarjeta-igual-sistema").innerHTML = "";

  $("panel-config").hidden = true;
  $("panel-conciliar").hidden = true;
  $("panel-tdd2").hidden = true;
  $("panel-docs").hidden = true;
  $("pasos-nav").hidden = false;
  $("btn-config").classList.remove("activo");
  $("btn-conciliar").classList.remove("activo");
  $("btn-tdd2").classList.remove("activo");
  $("sello-docs").classList.remove("activo");

  irA(1);
}

$("btn-inicio").addEventListener("click", reiniciarAsistente);

/* Catalogo de los aplicativos ya sembrados en la base (numero/nombre/id_
   habilitador), para el selector manual de modulo 5 y 6. Se pide una sola vez
   y se guarda en cache -- la lista de aplicativos no cambia mientras dura la
   sesion del navegador; si se sembro una base nueva, recargar la pagina la
   vuelve a traer fresca. */
async function cargarCatalogoAplicativos() {
  if (S.catalogoAplicativos) return S.catalogoAplicativos;
  try {
    const r = await pedir("/api/almacen/resumen");
    S.catalogoAplicativos = r.cobertura || [];
  } catch {
    S.catalogoAplicativos = [];
  }
  return S.catalogoAplicativos;
}

/* ═════════ PASO 1 · ORIGEN ═════════ */

function fijarModo(modo) {
  S.modo = modo;
  $("modo-archivo").classList.toggle("activo", modo === "archivo");
  $("modo-carpeta").classList.toggle("activo", modo === "carpeta");
  $("ruta-label").textContent = modo === "carpeta"
    ? "Ruta de la carpeta" : "Ruta del documento";
  $("ruta").placeholder = modo === "carpeta"
    ? "C:\\Users\\...\\HI entregables" : "C:\\Users\\...\\documento.docx";
  $("ruta-nota").innerHTML = modo === "carpeta"
    ? "Pega la ruta de la carpeta. En el Explorador: clic derecho sobre la carpeta → <em>Copiar como ruta</em>."
    : "Pega la ruta completa. En el Explorador: clic derecho sobre el archivo → <em>Copiar como ruta</em>.";
  $("check-recursivo").hidden = (modo !== "carpeta");
  mostrarError(1, "");
}

$("modo-archivo").addEventListener("click", () => fijarModo("archivo"));
$("modo-carpeta").addEventListener("click", () => fijarModo("carpeta"));

$("input-archivo").addEventListener("change", (e) => {
  S.archivoSubido = e.target.files[0] || null;
  if (S.archivoSubido) $("ruta").value = "";
});

$("ruta").addEventListener("input", () => { S.archivoSubido = null; });
$("ruta").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btn-continuar-1").click();
});

$("btn-continuar-1").addEventListener("click", async () => {
  mostrarError(1, "");
  S.ruta = $("ruta").value.trim().replace(/^"|"$/g, "");
  S.recursivo = $("recursivo").checked;

  // Se revisa fresco justo antes de escanear -- si sembraron otra base o
  // cambiaron el archivo hace un momento, esto ya lo recoge sin que el
  // usuario tenga que tocar nada.
  await detectarApmAutomatico();
  S.rutaApm = S.rutaApmAuto || "";

  if (S.modo === "archivo") {
    if (!S.ruta && !S.archivoSubido) {
      return mostrarError(1, "Escribe una ruta o elige un archivo.");
    }
    alcanzar(2); irA(2);
    return analizarUno();
  }

  if (!S.ruta) return mostrarError(1, "Escribe la ruta de la carpeta.");

  const btn = $("btn-continuar-1");
  btn.disabled = true; btn.textContent = "Explorando…";
  try {
    S.alcance = await pedir("/api/explorar",
      json({ ruta: S.ruta, recursivo: S.recursivo }));
    $("alcance-un-documento").hidden = true;
    $("alcance-carpeta").hidden = false;
    $("acciones-paso-2").hidden = false;
    $("paso-2-titulo").textContent = "Esto es lo que se va a procesar";
    pintarAlcance();
    alcanzar(2); irA(2);
  } catch (e) {
    mostrarError(1, e.message);
  } finally {
    btn.disabled = false; btn.textContent = "Continuar";
  }
});

/* ═════════ PASO 2 · ALCANCE ═════════ */

function pintarAlcance() {
  const a = S.alcance;
  $("resumen-alcance").innerHTML = `
    <div class="dato"><b>${a.n_aceptados}</b><span>documentos</span></div>
    <div class="dato"><b>${a.n_descartados}</b><span>omitidos</span></div>
    <div class="dato"><b>${a.recursivo ? "Sí" : "No"}</b><span>subcarpetas</span></div>`;

  $("tabla-alcance").tBodies[0].innerHTML = a.aceptados.slice(0, 300).map((f) => `
    <tr><td>${esc(f.nombre)}</td>
        <td><span class="etiqueta">${esc(f.extension)}</span>
            ${f.requiere_vision ? '<span class="etiqueta aviso-chip">necesita visión</span>' : ""}</td>
        <td>${kb(f.bytes)}</td></tr>`).join("");

  $("n-descartados").textContent = a.n_descartados;
  $("det-descartados").hidden = a.n_descartados === 0;
  $("lista-descartados").innerHTML = a.descartados.map((d) =>
    `<li><code>${esc(d.nombre)}</code> — ${esc(d.motivo)}</li>`).join("");

  // Estimacion honesta: con el modelo local un lote grande tarda de verdad.
  const seg = S.catalogos.proveedor === "ollama" ? 28 : 12;
  const total = a.n_aceptados * seg;
  $("aviso-tiempo").textContent = a.n_aceptados
    ? `Estimado: ~${Math.max(1, Math.round(total / 60))} min `
      + `(${seg}s por documento en ${S.catalogos.proveedor === "ollama" ? "modo local" : "modo API"}). `
      + `Puedes cancelar a medias; lo ya procesado se conserva.`
    : "";
}

$("btn-continuar-2").addEventListener("click", async () => {
  mostrarError(2, "");
  S.escribir = $("escribir").checked;
  const btn = $("btn-continuar-2");
  btn.disabled = true;
  try {
    const r = await pedir("/api/lote", json({
      ruta: S.ruta, recursivo: S.recursivo, escribir: S.escribir,
      ruta_apm: S.rutaApm,
    }));
    S.loteId = r.lote.id;
    alcanzar(3); irA(3);
    prepararVistaLote(r.lote);
    seguirLote();
  } catch (e) {
    mostrarError(2, e.message);
  } finally {
    btn.disabled = false;
  }
});

/* ═════════ PASO 3 · ANÁLISIS ═════════ */

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
    case "reglas":
      return `${info.extension || "sin extensión"}`
        + ` · ${info.candidatos_detectados ?? 0} candidatos detectados por reglas`
        + (info.contenido_truncado ? " · documento truncado por tamaño" : "");
    case "modelo":
      return `${(info.caracteres_texto ?? 0).toLocaleString("es-MX")} caracteres`
        + ` · ${info.imagenes_encontradas ?? 0} imágenes`
        + (info.uso?.tokens_salida
            ? ` · ${info.uso.tokens_salida} tokens de respuesta` : "");
    case "validacion":
      return info.campos_por_revisar
        ? `${info.campos_por_revisar} campo(s) por revisar`
        : "sin pendientes";
    default:
      return "";
  }
}

/* Pinta las 4 etapas con el resultado real de CADA UNA que mando el
   servidor, en vez de adivinar del lado del navegador cual fallo. `etapas`
   puede venir incompleto -- el pipeline se corta en la primera etapa que
   falla, asi que las de despues nunca se intentaron y se quedan en gris. */
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

/* Avance REAL, no estimado: el servidor responde al instante con un id de
   trabajo (ver /api/analizar-vivo en main.py) y este modulo va preguntando
   el avance real -- la misma informacion por etapa que ya arma
   _clasificar_ruta, etapa por etapa segun de verdad van terminando, mismo
   patron que ya usa un lote (ver seguirLote) pero para un solo documento. */

function chequeo(nombre, estado) {
  const el = document.querySelector(`#chequeo-alcance .chequeo-item[data-chk="${nombre}"]`);
  if (el) el.className = `chequeo-item${estado ? " " + estado : ""}`;
}

function chequeoTexto(nombre, texto) {
  const el = document.querySelector(
    `#chequeo-alcance .chequeo-item[data-chk="${nombre}"] .chequeo-texto`);
  if (el) el.textContent = texto;
}

/* Mismo chip que ya pinta seguirLote() en la tabla de un lote -- un solo
   lenguaje visual para "esto fue lo que se encontro", sea un documento o
   cuarenta. */
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

/* Arranca el trabajo (responde un id al instante) y va consultando el
   avance real hasta que termina o falla. Resuelve/rechaza con la MISMA
   forma que ya usa `pedir()` -- {mensaje, cuerpo} en el error -- para que
   analizarUno() no tenga que saber que esto no fue una sola peticion. */
function iniciarAnalisisVivo(forzar) {
  return new Promise((resolve, reject) => {
    (async () => {
      let idTrabajo;
      try {
        let r;
        if (S.archivoSubido) {
          const fd = new FormData();
          fd.append("file", S.archivoSubido);
          fd.append("ruta_apm", S.rutaApm || "");
          if (forzar) fd.append("forzar", "1");
          r = await pedir("/api/analizar-vivo/subir", { method: "POST", body: fd });
        } else {
          r = await pedir("/api/analizar-vivo",
            json({ ruta: S.ruta, ruta_apm: S.rutaApm, forzar }));
        }
        idTrabajo = r.id;
      } catch (e) {
        reject(e);
        return;
      }

      $("alcance-doc-nombre").textContent =
        `Documento: ${S.archivoSubido ? S.archivoSubido.name : S.ruta}`;

      let enPaso3 = false;

      const intervalo = setInterval(async () => {
        let a;
        try {
          a = await pedir(`/api/analizar-vivo/${idTrabajo}`);
        } catch (e) {
          clearInterval(intervalo);
          reject(e);
          return;
        }

        const et = a.etapas || {};

        if (et.identificacion) {
          if (et.identificacion.es_fuente) {
            chequeo("identificacion", "hecho");
            chequeoTexto("identificacion", "Documento verificado.");
          } else {
            chequeo("identificacion", "alerta");
            chequeoTexto("identificacion",
              "Ya se reconoce este documento como parte del sistema.");
          }
        }

        if (et.extraccion) {
          if (et.extraccion.estado === "ok") {
            chequeo("extraccion", "hecho");
            chequeoTexto("extraccion",
              `Contenido leído: ${et.extraccion.formato || ""}`
              + (et.extraccion.paginas
                  ? ` · ${et.extraccion.paginas} páginas/hojas/diapositivas` : ""));
          } else {
            chequeo("extraccion", "fallido");
            chequeoTexto("extraccion", et.extraccion.detalle || "No se pudo leer el documento.");
          }
        } else if (et.identificacion && et.identificacion.es_fuente) {
          chequeo("extraccion", "activo");
        }

        const listoParaPaso3 = !!(et.extraccion
          || (et.identificacion && !et.identificacion.es_fuente));
        if (listoParaPaso3 && !enPaso3) {
          enPaso3 = true;
          alcanzar(3); irA(3);
        }

        pintarEtapas(et);
        const hechas = ORDEN_ETAPAS.filter((n) => et[n] && et[n].estado === "ok").length;
        if (a.estado === "corriendo") {
          const siguiente = ORDEN_ETAPAS.find((n) => !et[n]);
          let textoEtapa = "Analizando…";
          if (siguiente && (siguiente === "extraccion"
              || (et[ORDEN_ETAPAS[ORDEN_ETAPAS.indexOf(siguiente) - 1]] || {}).estado === "ok")) {
            fase(siguiente, "activa");
            textoEtapa = ETIQUETAS_ETAPA[siguiente] || textoEtapa;
          }
          progreso(Math.min(92, 10 + hechas * 22), textoEtapa);
        }

        if (a.vinculacion) pintarHallazgoVivo(a.vinculacion);

        if (a.estado === "terminado" || a.estado === "error") {
          clearInterval(intervalo);
          if (a.estado === "terminado") {
            resolve(a.resultado);
          } else {
            const cuerpo = a.error || {};
            const mensaje = typeof cuerpo.detail === "string"
              ? cuerpo.detail : "El análisis no se completó.";
            const e = new Error(mensaje);
            e.cuerpo = cuerpo;
            reject(e);
          }
        }
      }, 350);
    })();
  });
}

/* Documentos que no llegan a Revisión: son el propio APM/TDD, o ya se sabía
   lo que dicen. Se explican aqui, en el paso 4, uno por uno -- no como un
   error, sino como el detalle de por que la lista de revision no los trae.
   La usan tanto el analisis de un solo documento como el de un lote.

   El caso "es igual al que ya está en el sistema" (`o.mismoEnSistema`) NO va
   dentro del acordeón "N documentos que no pasaron a revisión" -- ese
   acordeón empieza cerrado, y esta tarjeta trae dos botones que la persona
   necesita ver de inmediato, no escondidos detrás de un clic. Se pinta
   aparte, siempre visible, arriba del todo en el paso 4. Los demás casos
   (el archivo es el propio APM/TDD pero no se pudo fijar como referencia,
   o los omitidos de un lote) siguen como texto simple dentro del acordeón. */
function pintarOmitidos() {
  const igual = S.activosOmitidos.find((o) => o.mismoEnSistema);
  const resto = S.activosOmitidos.filter((o) => !o.mismoEnSistema);

  const tarjeta = $("tarjeta-igual-sistema");
  if (igual) {
    tarjeta.innerHTML = `
      <div class="omitido-igual">
        <div class="omitido-igual-nombre"><code>${esc(igual.nombre)}</code></div>
        ${igual.fecha ? `<div class="omitido-igual-fecha">${esc(igual.fecha)}</div>` : ""}
        <p class="omitido-igual-leyenda">Este archivo es igual al que está en el sistema.</p>
        <div class="omitido-igual-acciones">
          <button class="btn btn-sec" data-forzar-omitido type="button">Pasar solo para revisión</button>
          <button class="btn btn-sec" data-volver-inicio-omitido type="button">Volver a inicio</button>
        </div>
      </div>`;
    tarjeta.hidden = false;
    tarjeta.querySelector("[data-forzar-omitido]")
      .addEventListener("click", () => { irA(3); analizarUno(true); });
    tarjeta.querySelector("[data-volver-inicio-omitido]")
      .addEventListener("click", reiniciarAsistente);
  } else {
    tarjeta.hidden = true;
    tarjeta.innerHTML = "";
  }

  $("n-omitidos").textContent = resto.length;
  $("det-omitidos").hidden = resto.length === 0;
  $("lista-omitidos").innerHTML = resto.map((o) =>
    `<li><code>${esc(o.nombre)}</code> — ${esc(o.motivo)}</li>`).join("");
}

async function analizarUno(forzar = false) {
  $("alcance-carpeta").hidden = true;
  $("acciones-paso-2").hidden = true;
  $("alcance-un-documento").hidden = false;
  $("paso-2-titulo").textContent = "Verificando el documento";
  chequeo("identificacion", "activo");
  chequeo("extraccion", "");
  chequeoTexto("identificacion", "Verificando el documento…");
  chequeoTexto("extraccion", "Leyendo el contenido…");
  $("hallazgo-vivo").hidden = true;
  $("hallazgo-vivo").classList.remove("visible");

  $("envoltura-avance").hidden = true;
  $("btn-cancelar").hidden = true;
  $("btn-continuar-3").hidden = true;
  mostrarError(2, "");
  mostrarError(3, "");
  pintarEtapas({});
  progreso(0, "Preparando…");

  try {
    const r = await iniciarAnalisisVivo(forzar);

    if (r.excluido) {
      // Es el propio APM o un TDD: no aporta nada que revisar como fuente.
      // No es un error -- se descarta sin drama, igual que en un lote. El
      // corte pasa ANTES de mandarlo a IA (por diseño, para no gastar una
      // llamada en algo que ya se sabe que no es fuente), asi que solo las
      // dos primeras etapas se pintan -- las otras dos ni se intentaron.
      //
      // Paso 2 · Parte A: en vez de solo descartarlo, el servidor ya lo usó
      // para sembrar (o actualizar) la referencia activa -- se avisa aqui en
      // vez de mandar a la persona a la pantalla aparte de "Comparar APM y TDD".
      const esApm = r.tipo_excluido === "apm";
      const ref = r.referencia || {};
      let detalleReglas;
      let fecha = "";
      if (r.referencia_actualizada) {
        // Mensaje simple a propósito: lo único que a la persona le hace falta
        // ver aquí es que el documento ya está en el sistema y desde cuándo
        // -- no la explicación de por qué se excluyó de la clasificación.
        fecha = ref.actualizado_en ? _fechaLegible(ref.actualizado_en) : "";
        detalleReglas = "Este documento ya está en el sistema"
          + (fecha ? ` · referencia actualizada el ${fecha}` : "") + ".";
      } else {
        detalleReglas = `Es ${esApm ? "el propio libro de APM" : "un TDD"} — es destino, no `
          + "una fuente, así que no se manda a clasificar."
          + (ref.motivo ? ` (no se pudo fijar como referencia: ${ref.motivo})` : "");
      }
      pintarEtapas({
        extraccion: { estado: "ok", archivo: r.nombre },
        reglas: { estado: "ok", detalle: detalleReglas },
      });
      progreso(100, r.referencia_actualizada
        ? "Este documento ya está en el sistema."
        : "Este documento no se revisa: es el APM o un TDD, no una fuente.");
      S.activos = [];
      S.activosOmitidos = [r.referencia_actualizada
        ? { nombre: r.nombre, motivo: detalleReglas, mismoEnSistema: true, fecha }
        : { nombre: r.nombre, motivo: detalleReglas }];
      S.indice = 0;
      pintarOmitidos();
      $("btn-continuar-3").hidden = false;
      $("btn-continuar-3").click();
      return;
    }

    pintarEtapas(r.etapas);

    // Ya no se omite en silencio un documento sin identificar o ya visto sin
    // novedad: en el flujo de un solo documento siempre se pasa a Revisión
    // con la ficha completa (todos los campos, llenos o en falta). `valido` y
    // `motivo` siguen viajando en `_apm` y son los que arman la leyenda
    // (ver pintarAplicativoRef) -- aqui ya no se usan para esconder nada.
    progreso(100, `Listo en ${r.duracion_segundos}s`);

    S.activos = [{
      nombre: r.activo._documento?.nombre_archivo || S.ruta,
      activo: r.activo,
      texto: "",
      markdown: r.markdown,
      base: r.nombre_sugerido,
      ruta: S.ruta,
    }];
    S.activosOmitidos = [];
    S.indice = 0;
    pintarOmitidos();
    $("btn-continuar-3").hidden = false;
    $("btn-continuar-3").click();
  } catch (e) {
    const etapas = e.cuerpo && e.cuerpo.etapas;
    if (etapas) {
      // El servidor sabe exactamente en cual de las 4 etapas trueno -- se
      // pinta esa (y solo esa) en rojo, con su motivo real.
      pintarEtapas(etapas);
    } else {
      // No hay informacion de etapas (p. ej. la peticion nunca llego al
      // servidor: sin conexion, o un error del propio navegador). Se cae de
      // vuelta al rastro anterior: lo que seguia "activa" se marca fallido,
      // para no dejar el pipeline a medias sin ninguna senal.
      ["extraccion", "reglas", "modelo", "validacion"].forEach((f) => {
        const li = document.querySelector(`#pipeline li[data-fase="${f}"]`);
        if (li && li.className === "activa") li.className = "fallida";
      });
    }
    progreso(0, "El análisis no se completó.");
    // El fallo pudo pasar antes de llegar a pintar el paso 3 (p. ej. la
    // ruta no existe) -- si el paso 2 sigue siendo el visible, el error se
    // avisa ahi, no en un paso 3 que la persona todavia no ha visto.
    if ($("paso-2").hidden === false) {
      mostrarError(2, e.message);
    } else {
      mostrarError(3, e.message);
    }
  }
}

function prepararVistaLote(lote) {
  $("envoltura-avance").hidden = false;
  $("btn-cancelar").hidden = false;
  $("btn-continuar-3").hidden = true;
  $("tabla-avance").tBodies[0].innerHTML = "";
  ["extraccion", "reglas", "modelo", "validacion"].forEach((f) => fase(f, "activa"));
  progreso(0, `0 de ${lote.total}`);
}

let temporizador = null;

async function seguirLote() {
  clearInterval(temporizador);
  temporizador = setInterval(async () => {
    let l;
    try {
      l = await pedir(`/api/lote/${S.loteId}`);
    } catch (e) {
      clearInterval(temporizador);
      return mostrarError(3, e.message);
    }

    const pct = l.total ? (l.procesados / l.total) * 100 : 0;
    const restante = l.segundos_estimados_restantes;
    progreso(pct, `${l.procesados} de ${l.total}`
      + (l.actual ? ` · ${l.actual}` : "")
      + (restante ? ` · faltan ~${Math.round(restante / 60)} min` : ""));

    $("tabla-avance").tBodies[0].innerHTML = l.resultados.map((r) => `
      <tr class="${r.ok ? (r.excluido || r.aplicativo?.valido === false ? "fila-alerta" : "") : "fila-error"}">
        <td>${esc(r.nombre)}</td>
        <td>${esc(r.tipo || (r.excluido ? (r.tipo_excluido === "apm" ? "Libro APM" : "TDD") : "—"))}</td>
        <td>${esc(r.estado || "—")}</td>
        <td>${r.excluido
          ? `<span class="etiqueta">destino, no fuente</span>`
          : r.ok
          ? (r.aplicativo?.valido === false
              ? `<span class="etiqueta aviso-chip">${esc(r.aplicativo.motivo || "sin usar")}</span>`
              : r.aplicativo?.identificado
              ? `<span class="etiqueta ok-chip">#${esc(r.aplicativo.numero)} ${esc(r.aplicativo.nombre)}</span>`
              : r.requiere_revision?.length
              ? `<span class="etiqueta aviso-chip">${r.requiere_revision.length} por revisar</span>`
              : '<span class="etiqueta ok-chip">ok</span>')
          : `<span class="etiqueta error-chip">${esc(r.error).slice(0, 90)}</span>`}</td>
      </tr>`).join("");

    if (l.estado === "terminado" || l.estado === "cancelado") {
      clearInterval(temporizador);
      ["extraccion", "reglas", "modelo", "validacion"].forEach((f) => fase(f, "hecha"));
      $("btn-cancelar").hidden = true;
      progreso(100, `${l.estado === "cancelado" ? "Cancelado" : "Terminado"}: `
        + `${l.procesados - l.con_error} clasificados, ${l.con_error} con error`
        + (l.carpeta_salida ? ` · guardados en ${l.carpeta_salida}` : ""));
      await cargarResultadosLote();
    }
  }, 1500);
}

$("btn-cancelar").addEventListener("click", async () => {
  try { await pedir(`/api/lote/${S.loteId}/cancelar`, { method: "POST" }); }
  catch (e) { mostrarError(3, e.message); }
});

async function cargarResultadosLote() {
  const l = await pedir(`/api/lote/${S.loteId}?detalle=true`);

  // Un documento con aplicativo invalido (sin identificar, sin datos utiles,
  // o ya visto sin novedad) no cuenta como algo que revisar -- se aparta, no
  // se mezcla con lo que si necesita ojos humanos. Cuando no se dio una ruta
  // de APM, r.aplicativo simplemente no existe y todo se comporta como antes.
  const util = (r) => r.ok && r.activo && r.aplicativo?.valido !== false;

  S.activos = l.resultados.filter(util).map((r) => ({
    nombre: r.nombre,
    activo: r.activo,
    texto: r.texto || "",
    markdown: null,
    base: null,
    archivos: r.archivos,
    ruta: r.ruta || "",
  }));
  S.activosOmitidos = l.resultados
    .filter((r) => r.excluido || (r.ok && r.activo && r.aplicativo?.valido === false))
    .map((r) => ({
      nombre: r.nombre,
      motivo: r.excluido ? r.motivo : (r.aplicativo?.motivo || "no se usó"),
    }));
  S.indice = 0;
  $("btn-continuar-3").hidden = (S.activos.length + S.activosOmitidos.length) === 0;
  pintarOmitidos();

  // Si nada quedó para revisar no es un error: la lista de omitidos del
  // paso 4 ya explica, documento por documento, por qué se descartó cada uno.
}

$("btn-continuar-3").addEventListener("click", () => {
  if (!S.activos.length && !S.activosOmitidos.length) return;

  if (!S.activos.length) {
    // Todo lo escaneado se omitió: no hay nada que pintar en la ficha, pero
    // igual se entra al paso 4 para que se vea POR QUÉ -- la lista de
    // omitidos, no una pantalla en blanco.
    $("selector-lote").hidden = true;
    $("aplicativo-ref").hidden = true;
    $("resumen").innerHTML = "";
    $("nota-campos-ficha").hidden = true;
    $("ficha").innerHTML = "";
    $("observaciones").hidden = true;
    $("fuentes").hidden = true;
    $("diagramas").hidden = true;
    alcanzar(4); irA(4);
    return;
  }

  const sel = $("selector-lote");
  sel.hidden = S.activos.length < 2;
  if (!sel.hidden) {
    $("sel-documento").innerHTML = S.activos.map((a, i) =>
      `<option value="${i}">${esc(a.nombre)}</option>`).join("");
  }
  $("nota-campos-ficha").hidden = false;
  pintarActivo();
  alcanzar(4); irA(4);
});

function alCambiarDocumento() {
  $("llenado-ok").hidden = true;
  $("diff-llenado").hidden = true;
  $("btn-ver-cambios").hidden = true;
  $("btn-deshacer-llenado").hidden = !S.activos[S.indice]?.cambiosLlenado;
  if (S.activos[S.indice]?.cambiosLlenado) { pintarDiff(); }
  pintarLlenado();
}

$("sel-documento").addEventListener("change", (e) => {
  S.indice = Number(e.target.value);
  pintarActivo();
  alCambiarDocumento();
});

/* ═════════ PASO 4 · REVISIÓN ═════════ */

const ETIQUETAS = {
  id: "Identificador", tipo: "Tipo de activo", descripcion: "Descripción",
  version: "Versión", estado: "Estado", responsable: "Responsable",
  fecha: "Fecha", fuente: "Fuente", confidencialidad: "Confidencialidad",
};

// Fecha legible para la leyenda de "documento ya revisado" -- el backend
// manda la fecha en ISO (almacen.ahora()) y aqui se formatea, en vez de
// hacerlo en Python, para no depender de locales del sistema operativo.
function _fechaLegible(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleDateString("es-MX", { day: "numeric", month: "long", year: "numeric" });
}

function pintarAplicativoRef(activo) {
  const info = activo?._apm;
  const el = $("aplicativo-ref");
  if (!info || !info.disponible) { el.hidden = true; return; }

  if (!info.identificado) {
    if (info.aplicacion_nueva) {
      // No calza con ningun aplicativo de los que ya estan en el inventario,
      // pero trae forma de ficha de aplicacion (nombre, responsable, stack,
      // etc.) -- se ofrece como propuesta de alta, no se descarta.
      el.innerHTML = `<p class="nota-aplicativo">
        <b>Aplicación nueva (propuesta):</b> este documento no coincide con
        ningún aplicativo ya dado de alta en el inventario, pero trae
        información que parece describir una aplicación real.
        <br><span class="nota">Se muestra como propuesta para agregar al
        inventario -- no se escribe en el libro de APM real hasta que alguien
        la dé de alta ahí.</span>
        ${info.valido === false
          ? `<br><span class="pil e-rojo">${esc(info.motivo)}</span>` : ""}
      </p>`;
      el.hidden = false;
      return;
    }
    el.innerHTML = `<p class="nota-alerta">
      <b>No se encontró información de ningún aplicativo o habilitador</b> para
      este documento: no se pudo amarrar a ninguno del inventario de APM, así
      que no se usa para llenar nada.
      ${info.candidatos?.length ? `Menciona más de uno: `
        + info.candidatos.map((c) => `#${esc(c.numero)} ${esc(c.nombre)}`).join(", ")
        + `. Hay que decir cuál es." ` : ""}</p>`;
    el.hidden = false;
    return;
  }

  const tdd = info.tdd || [];

  // Leyenda de "documento ya revisado": nunca se salta el análisis (eso
  // siempre corre completo, arriba), esto solo informa si valió la pena
  // frente a la última vez que se vio este mismo documento. Sustituye el
  // aviso rojo genérico solo en este caso -- no es un error, es información.
  let legendaConocido = "";
  if (info.ya_conocido) {
    const fecha = _fechaLegible(info.leido_en_antes);
    legendaConocido = info.trae_novedad
      ? `<br><span class="pil e-ambar">Ya se había revisado antes`
        + `${fecha ? ` (la última vez el ${fecha})` : ""} y trae cambios respecto a `
        + `lo que ya se tenía — revisa los campos marcados más abajo.</span>`
      : `<br><span class="pil e-ok">Ya fue revisado`
        + `${fecha ? ` el ${fecha}` : ""}, sin actualizaciones respecto a lo que ya se tiene.</span>`;
  }

  el.innerHTML = `
    <p class="nota-aplicativo">
      <b>Aplicativo identificado:</b> #${esc(info.numero)} · ${esc(info.nombre_aplicativo)}
      ${info.id_habilitador ? `<span class="etiqueta">${esc(info.id_habilitador)}</span>` : ""}
      <br><span class="nota">${esc(info.evidencia || "")}</span>
      ${tdd.length ? `<br>TDD de este aplicativo en la base: `
          + tdd.map((t) => `<b>${esc(t.nombre)}</b> (${t.completitud}% lleno)`).join(", ")
        : `<br><span class="nota">Este aplicativo todavía no tiene un TDD sembrado en la base.</span>`}
      ${legendaConocido}
      ${info.aporta_informacion === false || (info.valido === false && !info.ya_conocido)
        ? `<br><span class="pil e-rojo">${esc(info.motivo)}</span>` : ""}
    </p>`;
  el.hidden = false;
}

function pintarActivo() {
  const item = S.activos[S.indice];
  if (!item) return;
  const a = item.activo;
  pintarAplicativoRef(a);

  const rev = a.requiere_revision?.length || 0;
  $("resumen").innerHTML = `
    <div class="dato"><b>${esc(a.tipo)}</b><span>tipo</span></div>
    <div class="dato"><b>${esc(a.estado)}</b><span>estado</span></div>
    <div class="dato"><b>${a.relaciones?.length || 0}</b><span>relaciones</span></div>
    <div class="dato"><b>${a.diagramas?.length || 0}</b><span>diagramas</span></div>
    <div class="dato"><b>${a.apm?.length || 0}</b><span>grupos APM</span></div>
    <div class="dato"><b>${a.tdd?.length || 0}</b><span>bloques TDD</span></div>
    <div class="dato ${rev ? "alerta" : ""}"><b>${rev}</b><span>por revisar</span></div>`;

  const ficha = $("ficha");
  ficha.innerHTML = "";
  for (const campo of Object.keys(ETIQUETAS)) {
    const valor = a[campo] ?? "";
    const enRevision = a.requiere_revision?.includes(campo);
    const nivel = a.niveles?.[campo] || "";
    const cat = S.catalogos[
      campo === "tipo" ? "tipos"
      : campo === "estado" ? "estados"
      : campo === "confidencialidad" ? "confidencialidad" : null];

    const control = cat
      ? `<select data-campo="${campo}">${cat.map((o) =>
          `<option${o === valor ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`
      : campo === "descripcion"
        ? `<textarea data-campo="${campo}" rows="3">${esc(valor)}</textarea>`
        : `<input data-campo="${campo}" value="${esc(valor)}">`;

    ficha.insertAdjacentHTML("beforeend", `
      <div class="campo ${enRevision ? "en-revision" : ""}">
        <label>${ETIQUETAS[campo]}
          ${nivel ? `<span class="nivel n-${esc(nivel).replace(/\s/g, "-").toLowerCase()}">${esc(nivel)}</span>` : ""}
        </label>
        ${control}
      </div>`);
  }

  ficha.querySelectorAll("[data-campo]").forEach((el) =>
    el.addEventListener("change", () => {
      a[el.dataset.campo] = el.value;
      item.markdown = null;   // el .md se regenera con lo corregido
    }));

  $("observaciones").hidden = !(a.observaciones?.length);
  $("lista-observaciones").innerHTML =
    (a.observaciones || []).map((o) => `<li>${esc(o)}</li>`).join("");

  // APM y TDD, cada uno en su tabla. Separados porque la decision de que entra
  // al Knowledge Hub se toma por fuente.
  const nivelChip = (n) => `<span class="etiqueta nivel-${esc(n).toLowerCase()}">${esc(n)}</span>`;
  let algunaFuente = false;
  for (const clave of ["apm", "tdd"]) {
    const filas = a[clave] || [];
    algunaFuente = algunaFuente || filas.length > 0;
    $(`bloque-${clave}`).hidden = filas.length === 0;
    $(`tabla-${clave}`).tBodies[0].innerHTML = filas.map((f) => `
      <tr><td>${esc(f.grupo)}</td>
          <td>${nivelChip(f.nivel)}</td>
          <td><span class="etiqueta ${f.cobertura === "Documentado" ? "ok-chip" : (f.cobertura === "Referenciado" ? "ref-chip" : "")}">${esc(f.cobertura)}</span></td>
          <td>${esc(f.detalle || "—")}</td></tr>`).join("");
  }
  $("fuentes").hidden = false;
  $("fuentes-vacio").hidden = algunaFuente;

  $("diagramas").hidden = !(a.diagramas?.length);
  $("lista-diagramas").innerHTML = (a.diagramas || []).map((d) => `
    <article class="diagrama">
      <h4>${esc(d.titulo)} <span class="etiqueta">${esc(d.tipo_diagrama)}</span></h4>
      <p>${esc(d.descripcion)}</p>
      ${d.elementos ? `<p class="nota"><b>Elementos:</b> ${esc(d.elementos)}</p>` : ""}
      ${d.flujo ? `<p class="nota"><b>Flujo:</b> ${esc(d.flujo)}</p>` : ""}
    </article>`).join("");
}

$("btn-continuar-4").addEventListener("click", async () => {
  mostrarError(4, "");
  const item = S.activos[S.indice];
  try {
    await pedir("/api/validate", json({ activo: item.activo, decision: "aceptado" }));
  } catch { /* la validacion no bloquea la exportacion */ }

  pintarLlenado();
  alcanzar(5); irA(5);
});


/* ═════════ SELECTOR MANUAL DE APLICATIVO (modulo 5 y 6) ═════════
   El amarre automatico puede fallar (no identifica nada) o quedar en duda
   (el documento menciona dos o mas aplicativos). Este selector deja elegir a
   mano contra cual aplicativo comparar, en vez de depender solo de lo que
   identificacion.py decidio. Vive por documento (item.activo._apm), asi que
   cambiar de aplicativo en modulo 5 tambien se refleja en modulo 6 y
   viceversa -- por eso las dos instancias del selector (sufijo "5" y "6") se
   repintan juntas cada vez que cambia algo. Solo funciona con documentos que
   se abrieron por ruta (item.ruta): un archivo subido desde el navegador ya
   no existe en disco despues del analisis, asi que no hay nada que
   /api/vincular-manual pueda volver a leer. */

function pintarSelectorManual(sufijo) {
  const item = S.activos[S.indice];
  const cont = $(`selector-manual-${sufijo}`);
  const sel = $(`sel-aplicativo-${sufijo}`);
  const nota = $(`nota-manual-${sufijo}`);
  if (!item || !cont || !sel || !nota) return;

  // Antes esto se apagaba por completo si el documento se subio desde el
  // navegador (su temporal ya no existe en disco despues del analisis). Ya
  // no hace falta: `item.activo._doc_snapshot` trae lo mismo que
  // /api/vincular-manual necesita, asi que el selector funciona igual haya
  // sido por ruta o por subida -- ver la nota de `_doc_snapshot` en main.py.
  cont.hidden = false;
  sel.disabled = false;
  cargarCatalogoAplicativos().then((cat) => {
    const info = item.activo?._apm || {};
    const actual = String(info.numero || "");
    const candidatos = info.candidatos || [];
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

    if (info.identificado && info.senal !== "manual") {
      nota.textContent = `Reconocido automáticamente: #${esc(info.numero)} · `
        + `${esc(info.nombre_aplicativo)}. Si no es el que corresponde, elige `
        + `otro de la lista.`;
    } else if (candidatos.length) {
      nota.textContent = `El documento menciona ${candidatos.length} `
        + `habilitadores distintos y no se puede saber solo cuál es el suyo: `
        + `elige uno de "El documento menciona más de uno".`;
    } else if (info.identificado && info.senal === "manual") {
      nota.textContent = `Comparando contra #${esc(info.numero)} · `
        + `${esc(info.nombre_aplicativo)} (elegido a mano).`;
    } else {
      nota.textContent = `No se pudo reconocer a qué habilitador pertenece `
        + `este documento: elige uno de los ${cat.length} para comparar sus `
        + `campos contra la referencia.`;
    }
  });
}

async function usarAplicativoManual(sufijo) {
  const item = S.activos[S.indice];
  const sel = $(`sel-aplicativo-${sufijo}`);
  const btn = $(`btn-aplicar-manual-${sufijo}`);
  if (!item || !sel || !sel.value) return;
  const numero = sel.value;

  btn.disabled = true;
  try {
    // Si el documento vino de una ruta, se manda esa ruta y el servidor
    // relee el archivo. Si se subió desde el navegador, ya no existe en
    // disco: se manda la instantánea que quedó guardada del análisis
    // original (`_doc_snapshot`) para que el servidor no tenga que releer
    // nada.
    const cuerpo = { ruta_apm: S.rutaApm, numero, nombre: item.nombre };
    if (item.ruta) cuerpo.ruta = item.ruta;
    else cuerpo.doc = item.activo._doc_snapshot || null;

    const r = await pedir("/api/vincular-manual", json(cuerpo));
    item.activo._apm = r.apm;
    item.activo._llenado = r.llenado;
    // Cambiar de aplicativo invalida cualquier valor capturado a mano contra
    // el aplicativo anterior -- se reinicia para no mezclar dos filas
    // distintas del APM (o del TDD) en una sola ficha.
    item.activo.ficha_apm = {};
    item.activo.ficha_tdd = {};
    item.cambiosLlenado = null;
    item.markdown = null;

    pintarAplicativoRef(item.activo);
    pintarLlenado();
    pintarTdd();
  } catch (e) {
    mostrarError(sufijo === "6" ? 6 : 5, e.message);
  } finally {
    btn.disabled = false;
  }
}

$("btn-aplicar-manual-5").addEventListener("click", () => usarAplicativoManual("5"));
$("btn-aplicar-manual-6").addEventListener("click", () => usarAplicativoManual("6"));

/* ═════════ PASO 5 · LLENADO APM ═════════
   Un solo documento contra las columnas REALES del aplicativo con el que ya
   quedó identificado (paso 4). La propuesta viene calculada del servidor
   dentro del activo (`_llenado.apm`): aqui solo se pinta, se aplica y se
   muestra que cambio. Si el documento no quedó identificado con ningún
   aplicativo, `_llenado` es null y no hay nada que pintar -- no es llenar por
   llenar. La regla de fusion NO se reimplementa en el navegador -- se pide a
   /api/llenado/aplicar -- para que el llenado de un documento y el de un lote
   de 49 no puedan divergir.
   ========================================================================= */

const ESTADO_TEXTO = {
  propuesto: "Propuesto · pendiente de llenar",
  extraido: "Extraído del documento",
  heredado: "Ya está en el APM",
  diferente: "El documento dice otra cosa · revisar",
  faltante: "Falta",
  manual: "Capturado a mano",
  calculado: "Valor calculado (fórmula) · solo lectura",
};

/* El estado que se PINTA no es el de la propuesta, sino el de la FICHA REAL.
   Esa distincion es lo que hace que el antes/despues se vea en el formulario y
   no solo en la tabla de cambios: mientras no se aprieta el boton, un campo con
   propuesta esta "propuesto" y su casilla se ve vacia, con el valor sugerido de
   marca de agua. Al llenar pasa a "extraido" o "heredado" y el dato entra de
   verdad. Y si el humano escribe encima, pasa a "manual" y ya nada lo pisa. */
function estadoVivo(item, fuente, campo) {
  // "calculado" nunca cambia de estado: no es una propuesta que "Llenar
  // documento" pueda aplicar, es el valor que el libro YA trae de una
  // formula. Sin este corte temprano, tener un `campo.valor` (el numero
  // calculado) haria que cayera en la rama de "propuesto" de abajo, como si
  // fuera algo pendiente de aplicar.
  if (campo.estado === "calculado") return "calculado";
  const ficha = item.activo[`ficha_${fuente}`] || {};
  const puesto = String(ficha[campo.clave] ?? "").trim();
  if (!puesto) return campo.valor ? "propuesto" : campo.estado;
  if (puesto !== campo.valor) return "manual";
  return campo.estado;
}

function propuesta() {
  return S.activos[S.indice]?.activo?._llenado?.apm || null;
}

/* ═════════ "Hacer nueva versión" (paso 5 y 6) ═════════
   Un campo cuenta como "cambio pendiente" solo si su estado ORIGINAL (el que
   trae la ficha desde el servidor, no el "vivo" que cambia de color con cada
   tecla) era un hueco vacío del libro/TDD real -- "faltante" o "extraido".
   Un campo "heredado" o "diferente" significa que el libro/TDD YA tiene
   contenido ahí, y eso nunca lo escribe este botón (ver
   /api/llenado/nueva-version-apm y -tdd, que aplican la misma regla del lado
   del servidor -- la comprobación de aquí es solo para pintar el botón, la
   que de verdad decide qué se escribe es la del servidor).
   El botón, una vez que escribe una version nueva, se vuelve a apagar hasta
   que haya algo GENUINAMENTE nuevo que escribir: `nvApmEscritos`/
   `nvTddEscritos` recuerdan clave->valor de lo último ya guardado, así que
   si la persona no toca nada mas el botón no se queda azul sin motivo. */
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

function _pintarBotonNuevaVersion(sufijo, fuente, elegible, motivoNoElegible) {
  const item = S.activos[S.indice];
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

async function _hacerNuevaVersion(sufijo, fuente, endpoint, payloadExtra) {
  const item = S.activos[S.indice];
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
    if (fuente === "apm") pintarLlenado(); else pintarTdd();
  }
}

$("btn-nueva-version-5").addEventListener("click", () =>
  _hacerNuevaVersion("5", "apm", "/api/llenado/nueva-version-apm", { ruta_apm: S.rutaApm }));
$("btn-nueva-version-6").addEventListener("click", () =>
  _hacerNuevaVersion("6", "tdd", "/api/llenado/nueva-version-tdd", {}));

// La cabecera de arriba de modulo 5: siempre declara UNO de tres estados,
// para que nunca quede la duda de a que aplicativo pertenece lo que se esta
// mostrando. Mismo criterio que pintarAplicativoRef en modulo 4, pero puesto
// aqui tambien porque es facil llegar a modulo 5 sin haber leido con cuidado
// la cabecera de modulo 4.
function pintarCabeceraModulo5(activo) {
  const info = activo?._apm;
  const el = $("cabecera-modulo5");

  if (info?.identificado) {
    el.innerHTML = `<p class="nota-aplicativo">
      <b>Llenado de APM del aplicativo:</b> #${esc(info.numero)} · ${esc(info.nombre_aplicativo)}
      ${info.id_habilitador ? `<span class="etiqueta">${esc(info.id_habilitador)}</span>` : ""}
    </p>`;
    el.hidden = false;
    return;
  }
  if (info?.aplicacion_nueva) {
    el.innerHTML = `<p class="nota-aplicativo">
      <b>Aplicación nueva (propuesta):</b> este documento no coincide con ningún
      aplicativo ya dado de alta en el inventario, así que no hay una fila real
      contra la cual comparar. Lo de abajo es lo que el documento trae para una
      posible alta nueva -- no se escribe en el libro de APM real.
    </p>`;
    el.hidden = false;
    return;
  }
  if (info?.sin_libro) {
    el.innerHTML = `<p class="nota-alerta">
      <b>No hay ningún libro de APM sembrado en esta base.</b> Lo de abajo son
      los 40 campos del catálogo estándar de APM, con lo que este documento
      trae (o sin dato donde no dice nada) -- pero sin comparar contra ningún
      aplicativo real, porque todavía no se cargó ninguno.
      <br><span class="nota">Sube tu libro de APM en "Inicio" (se siembra solo),
      o cárgalo a mano en "Comparar APM y TDD".</span>
    </p>`;
    el.hidden = false;
    return;
  }
  el.innerHTML = `<p class="nota-alerta">
    <b>No se encontró información de ningún aplicativo o habilitador</b> para
    este documento.</p>`;
  el.hidden = false;
}

function pintarLlenado() {
  const item = S.activos[S.indice];
  const p = propuesta();
  const caja = $("ficha-llenado");

  pintarSelectorManual("5");

  if (!p) {
    pintarCabeceraModulo5(item.activo);
    $("resumen-llenado-apm").innerHTML = "";
    caja.innerHTML = `<p class="nota">Este documento no quedó identificado con
      ningún aplicativo del APM (o se analizó con una versión anterior), así
      que no hay con qué compararlo: no se propone llenar nada.</p>`;
    $("btn-llenar").disabled = true;
    _pintarBotonNuevaVersion("5", "apm", false,
      "Este documento no está identificado con un aplicativo real del inventario");
    return;
  }
  $("btn-llenar").disabled = false;
  pintarCabeceraModulo5(item.activo);
  _pintarBotonNuevaVersion("5", "apm", !!item.activo?._apm?.identificado,
    "Este documento no está identificado con un aplicativo real del inventario");

  const ficha = item.activo.ficha_apm || {};
  const cApm = p.grupos.reduce((n, g) =>
    n + g.campos.filter((c) => String(ficha[c.clave] ?? "").trim()).length, 0);

  $("resumen-llenado-apm").innerHTML = `
    <div class="dato"><b>${cApm}/${p.resumen.total}</b><span>campos APM</span></div>
    <div class="dato"><b>${p.resumen.extraidos}</b><span>hallados en el documento</span></div>
    <div class="dato ${p.resumen.diferentes ? "alerta" : ""}"><b>${p.resumen.diferentes}</b>
         <span>con diferencia · revisar</span></div>
    <div class="dato"><b>${p.resumen.faltantes}</b><span>sin dato</span></div>
    ${p.resumen.calculados ? `<div class="dato"><b>${p.resumen.calculados}</b>
         <span>calculados (fórmula)</span></div>` : ""}`;

  caja.innerHTML = p.grupos.map((g) => `
    <section class="grupo-ficha">
      <h4>${esc(g.grupo)}</h4>
      <div class="rejilla-campos">
        ${g.campos.map((c) => {
          const est = estadoVivo(item, "apm", c);
          if (est === "calculado") {
            // Solo lectura de verdad: sin data-clave (no entra al listener de
            // cambios) y con disabled, para que no se pueda escribir ni se
            // cuele como si fuera una propuesta capturable.
            return `
          <div class="campo-llenado est-calculado">
            <label for="ll-apm-${c.clave}">${esc(c.etiqueta)}</label>
            <input id="ll-apm-${c.clave}" value="${esc(c.valor)}"
                   placeholder="sin valor calculado" disabled>
            <span class="marca-estado">${esc(ESTADO_TEXTO.calculado)}</span>
          </div>`;
          }
          // La casilla solo trae lo que YA esta en la ficha. Lo propuesto vive
          // en el placeholder hasta que el boton lo aplica: asi el "antes" es
          // de verdad un antes.
          const val = String(ficha[c.clave] ?? "");
          const pista = est === "propuesto" ? `propuesto: ${c.valor}`
            : est === "diferente" ? "el APM ya tiene otro valor; revisa antes de aceptar"
            : "sin dato en el documento";
          return `
          <div class="campo-llenado est-${est}">
            <label for="ll-apm-${c.clave}">${esc(c.etiqueta)}</label>
            <input id="ll-apm-${c.clave}" data-clave="${c.clave}" value="${esc(val)}"
                   placeholder="${esc(pista)}">
            <span class="marca-estado">${esc(ESTADO_TEXTO[est] || est)}</span>
            ${c.evidencia ? `<span class="evidencia" title="${esc(c.evidencia)}">${esc(c.evidencia)}</span>` : ""}
          </div>`;
        }).join("")}
      </div>
    </section>`).join("");

  // Lo que el humano escriba manda sobre la propuesta y sobre el .md.
  caja.querySelectorAll("[data-clave]").forEach((el) =>
    el.addEventListener("change", () => {
      item.activo.ficha_apm = item.activo.ficha_apm || {};
      item.activo.ficha_apm[el.dataset.clave] = el.value.trim();
      item.markdown = null;
      pintarLlenado();
    }));
}

$("btn-llenar").addEventListener("click", async () => {
  mostrarError(5, "");
  const item = S.activos[S.indice];
  const btn = $("btn-llenar");
  btn.disabled = true;
  try {
    const r = await pedir("/api/llenado/aplicar", json({ activo: item.activo }));

    // El "antes" se guarda para poder deshacer: llenar no debe ser una
    // decision irreversible tomada por curiosidad.
    item.fichasPrevias = {
      apm: { ...(item.activo.ficha_apm || {}) },
      tdd: { ...(item.activo.ficha_tdd || {}) },
    };
    item.activo.ficha_apm = r.fichas.apm;
    item.activo.ficha_tdd = r.fichas.tdd;
    item.cambiosLlenado = r.cambios;
    item.markdown = null;

    const nApm = r.cambios.apm.length;
    const nTdd = (r.cambios.tdd || []).length;
    const n = nApm + nTdd;
    $("llenado-ok").textContent = n
      ? `Se llenaron ${nApm} campos del APM y ${nTdd} del TDD con lo que dice `
        + `el documento (o con lo que ya tenía). Lo marcado "con diferencia" `
        + `no se tocó: revísalo a mano.`
      : "No hubo nada nuevo que llenar: los campos con dato ya estaban puestos.";
    $("llenado-ok").hidden = false;
    $("btn-ver-cambios").hidden = !n;
    $("btn-deshacer-llenado").hidden = !n;
    pintarDiff();
    if (n) $("diff-llenado").hidden = false;
    pintarLlenado();
    pintarTdd();
  } catch (e) {
    mostrarError(5, e.message);
  } finally {
    btn.disabled = false;
  }
});

function pintarDiff() {
  const cambios = S.activos[S.indice]?.cambiosLlenado;
  if (!cambios) return;
  const fila = (c, fuente) => `<tr>
    <td>${esc(c.etiqueta)}<br><span class="nota">${fuente} · ${esc(c.grupo)}</span></td>
    <td class="antes">(vacío)</td>
    <td class="despues">${esc(c.despues)}</td>
    <td><span class="nota">${esc(c.evidencia || c.origen)}</span></td>
  </tr>`;
  const filas = [
    ...cambios.apm.map((c) => fila(c, "APM")),
    ...(cambios.tdd || []).map((c) => fila(c, "TDD")),
  ];
  $("tabla-diff").tBodies[0].innerHTML = filas.join("");
}

$("btn-ver-cambios").addEventListener("click", () => {
  const d = $("diff-llenado");
  d.hidden = !d.hidden;
});

$("btn-deshacer-llenado").addEventListener("click", () => {
  const item = S.activos[S.indice];
  if (!item.fichasPrevias) return;
  item.activo.ficha_apm = { ...item.fichasPrevias.apm };
  item.activo.ficha_tdd = { ...item.fichasPrevias.tdd };
  item.cambiosLlenado = null;
  item.markdown = null;
  $("diff-llenado").hidden = true;
  $("btn-ver-cambios").hidden = true;
  $("btn-deshacer-llenado").hidden = true;
  $("llenado-ok").textContent = "Se deshizo el llenado. Las fichas volvieron a como estaban.";
  pintarLlenado();
  pintarTdd();
});

$("btn-continuar-5").addEventListener("click", () => {
  mostrarError(5, "");
  pintarTdd();
  alcanzar(6); irA(6);
});

/* ═════════ PASO 6 · LLENADO DE TDD ═════════
   Motor de comparacion real, mismo espiritu que modulo 5 pero contra el
   archivo TDD real del aplicativo (no una plantilla generica: cada TDD trae
   sus propias tablas). Tres casos, declarados siempre arriba en la cabecera:

     1. identificado + TDD real en la base (de los 17 ya sembrados) ->
        comparacion completa extraido/heredado/diferente/faltante, igual que
        el APM.
     2. identificado mas NO tiene TDD real sembrado (de los ~53 restantes) ->
        propuesta: lo que el documento trae, sin nada contra que comparar.
     3. no identificado pero con pinta de ficha de aplicacion (aplicacion
        nueva) -> misma propuesta, por la misma razon: no hay TDD real.
     4. nada de lo anterior -> no se pinta ninguna ficha.

   El campo.clave de la ficha de TDD vive en `item.activo.ficha_tdd`, aparte
   de `ficha_apm`, asi que capturar aqui no pisa nada de modulo 5 ni viceversa.
   El boton "Llenar documento" de modulo 5 ya aplica las dos fichas (ver
   /api/llenado/aplicar), asi que no hace falta un boton duplicado aqui. */

function propuestaTdd() {
  return S.activos[S.indice]?.activo?._llenado?.tdd || null;
}

/* ═════════ Diagramas del documento (paso 6, "ventana aparte") ═════════
   Las imagenes viven en `activo._imagenes` -- vienen en la MISMA respuesta
   que el resto del activo (ver `_clasificar_ruta` en main.py) y NUNCA se
   guardan en disco: son base64 en memoria mientras dura esta sesión del
   navegador, igual que del lado del servidor (ver parsers/imagenes.py). Aquí
   solo se pintan, en una ventana flotante aparte para no tapar el
   formulario de paso 6 que sigue detrás. */
function pintarBotonDiagramas(item) {
  const imagenes = item?.activo?._imagenes || [];
  $("bloque-ver-diagramas").hidden = imagenes.length === 0;
  $("n-diagramas").textContent = `(${imagenes.length})`;
}

function abrirModalDiagramas() {
  const item = S.activos[S.indice];
  const imagenes = item?.activo?._imagenes || [];
  $("modal-diagramas-lista").innerHTML = imagenes.length
    ? imagenes.map((im, i) => `
        <div class="diagrama-item">
          <img src="data:${esc(im.media_type || "image/png")};base64,${im.base64}"
               alt="Diagrama ${i + 1} del documento">
          <p class="diagrama-origen">${esc(im.origen || `Diagrama ${i + 1}`)}</p>
        </div>`).join("")
    : `<p class="nota">No se encontraron diagramas en este documento.</p>`;
  $("modal-diagramas").hidden = false;
}

function cerrarModalDiagramas() {
  $("modal-diagramas").hidden = true;
}

$("btn-ver-diagramas").addEventListener("click", abrirModalDiagramas);
$("btn-cerrar-diagramas").addEventListener("click", cerrarModalDiagramas);
$("modal-diagramas-fondo").addEventListener("click", cerrarModalDiagramas);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("modal-diagramas").hidden) cerrarModalDiagramas();
});

function pintarCabeceraModulo6(activo) {
  const info = activo?._apm;
  const p = activo?._llenado?.tdd;
  const hayFicha = !!(p && p.grupos && p.grupos.length);
  const el = $("cabecera-modulo6");

  if (info?.identificado) {
    if (hayFicha && !p.es_propuesta) {
      el.innerHTML = `<p class="nota-aplicativo">
        <b>Llenado de TDD del aplicativo:</b> #${esc(info.numero)} · ${esc(info.nombre_aplicativo)}
        ${info.id_habilitador ? `<span class="etiqueta">${esc(info.id_habilitador)}</span>` : ""}
        <br>Comparado contra el TDD real: <b>${esc(p.documento_origen)}</b>.
      </p>`;
    } else if (hayFicha && p.es_propuesta) {
      el.innerHTML = `<p class="nota-aplicativo">
        <b>Aplicativo:</b> #${esc(info.numero)} · ${esc(info.nombre_aplicativo)}
        ${info.id_habilitador ? `<span class="etiqueta">${esc(info.id_habilitador)}</span>` : ""}
        <br><b>Este aplicativo no tiene un TDD real sembrado en la base</b>
        (de los que ya se leyeron de la carpeta de TDD), así que no hay con qué
        comparar. Lo de abajo es una <b>propuesta</b>: lo que el documento trae,
        para cuando exista un TDD real que llenar.
      </p>`;
    } else {
      el.innerHTML = `<p class="nota-aplicativo">
        <b>Aplicativo:</b> #${esc(info.numero)} · ${esc(info.nombre_aplicativo)}
        ${info.id_habilitador ? `<span class="etiqueta">${esc(info.id_habilitador)}</span>` : ""}
        <br><b>No hay TDD real sembrado para este aplicativo, y este documento
        tampoco trae información reconocible</b> para proponer nada de TDD.
      </p>`;
    }
    el.hidden = false;
    return;
  }
  if (info?.aplicacion_nueva) {
    el.innerHTML = hayFicha ? `<p class="nota-aplicativo">
      <b>Aplicación nueva (propuesta):</b> este documento no coincide con
      ningún aplicativo del inventario, así que tampoco hay un TDD real con el
      cual comparar. Lo de abajo es lo que el documento trae, como propuesta
      para cuando se dé de alta el aplicativo y su TDD.
    </p>` : `<p class="nota-aplicativo">
      <b>Aplicación nueva (propuesta):</b> este documento no coincide con
      ningún aplicativo del inventario y tampoco trae información reconocible
      de TDD que proponer.
    </p>`;
    el.hidden = false;
    return;
  }
  if (info?.sin_libro) {
    el.innerHTML = `<p class="nota-alerta">
      <b>No hay ningún libro de APM sembrado en esta base.</b> Lo de abajo son
      los 34 campos del catálogo estándar de TDD, con lo que este documento
      trae -- sin comparar contra ningún TDD real, porque todavía no se cargó
      ningún libro.
      <br><span class="nota">Sube tu libro de APM en "Inicio" (se siembra solo),
      o cárgalo a mano en "Comparar APM y TDD".</span>
    </p>`;
    el.hidden = false;
    return;
  }
  el.innerHTML = `<p class="nota-alerta">
    <b>No se encontró información de TDD</b> para este documento: no se pudo
    amarrar a ningún aplicativo del inventario, y tampoco trae nada
    reconocible como ficha de aplicación.</p>`;
  el.hidden = false;
}

function pintarTdd() {
  const item = S.activos[S.indice];
  const p = propuestaTdd();
  pintarCabeceraModulo6(item.activo);
  pintarSelectorManual("6");
  pintarBotonDiagramas(item);
  const caja = $("ficha-tdd");
  const resumenEl = $("resumen-llenado-tdd");

  if (!p || !p.grupos || !p.grupos.length) {
    resumenEl.innerHTML = "";
    caja.innerHTML = `<p class="nota">No hay ninguna ficha de TDD que mostrar
      para este documento.</p>`;
    _pintarBotonNuevaVersion("6", "tdd", false,
      "No hay ninguna ficha de TDD para este documento");
    return;
  }

  _pintarBotonNuevaVersion("6", "tdd", !p.es_propuesta,
    "Este aplicativo no tiene un TDD real sembrado en la base (esto es solo una propuesta)");

  const ficha = item.activo.ficha_tdd || {};
  const cTdd = p.grupos.reduce((n, g) =>
    n + g.campos.filter((c) => String(ficha[c.clave] ?? "").trim()).length, 0);

  resumenEl.innerHTML = p.es_propuesta ? `
    <div class="dato"><b>${p.resumen.extraidos}</b><span>campos que trae el documento</span></div>`
    : `
    <div class="dato"><b>${cTdd}/${p.resumen.total}</b><span>campos TDD</span></div>
    <div class="dato"><b>${p.resumen.extraidos}</b><span>hallados en el documento</span></div>
    <div class="dato ${p.resumen.diferentes ? "alerta" : ""}"><b>${p.resumen.diferentes}</b>
         <span>con diferencia · revisar</span></div>
    <div class="dato"><b>${p.resumen.faltantes}</b><span>sin dato</span></div>`;

  caja.innerHTML = p.grupos.map((g) => `
    <section class="grupo-ficha">
      <h4>${esc(g.grupo)}</h4>
      <div class="rejilla-campos">
        ${g.campos.map((c) => {
          const est = estadoVivo(item, "tdd", c);
          const val = String(ficha[c.clave] ?? "");
          const pista = est === "propuesto" ? `propuesto: ${c.valor}`
            : est === "diferente" ? "el TDD ya tiene otro valor; revisa antes de aceptar"
            : "sin dato en el documento";
          return `
          <div class="campo-llenado est-${est}">
            <label for="ll-tdd-${c.clave}">${esc(c.etiqueta)}</label>
            <input id="ll-tdd-${c.clave}" data-clave-tdd="${c.clave}" value="${esc(val)}"
                   placeholder="${esc(pista)}">
            <span class="marca-estado">${esc(est === "heredado" ? "Ya está en el TDD" : (ESTADO_TEXTO[est] || est))}</span>
            ${c.evidencia ? `<span class="evidencia" title="${esc(c.evidencia)}">${esc(c.evidencia)}</span>` : ""}
          </div>`;
        }).join("")}
      </div>
    </section>`).join("");

  caja.querySelectorAll("[data-clave-tdd]").forEach((el) =>
    el.addEventListener("change", () => {
      item.activo.ficha_tdd = item.activo.ficha_tdd || {};
      item.activo.ficha_tdd[el.dataset.claveTdd] = el.value.trim();
      item.markdown = null;
      pintarTdd();
    }));
}

$("btn-continuar-6").addEventListener("click", async () => {
  mostrarError(6, "");
  $("carpeta-destino").value = S.modo === "carpeta"
    ? S.ruta : (S.ruta.replace(/[\\/][^\\/]*$/, "") || S.ruta);
  await refrescarPreview();
  alcanzar(7); irA(7);
});

/* ═════════ PASO 7 · EXPORTACIÓN ═════════ */

async function refrescarPreview() {
  const item = S.activos[S.indice];
  if (!item.markdown) {
    // Se regenera en el servidor para que el .md use el mismo formateador
    // que el lote, en vez de una segunda implementacion en JavaScript.
    try {
      const r = await pedir("/api/exportar", json({
        activo: item.activo, texto: item.texto || "",
        ruta_origen: item.nombre, solo_vista: true,
      }));
      item.markdown = r.markdown;
    } catch {
      item.markdown = null;
    }
  }
  $("preview-md").textContent = item.markdown || "(se generará al guardar)";
}

function descargar(nombre, contenido, tipo) {
  const url = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  const a = document.createElement("a");
  a.href = url; a.download = nombre;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

const actual = () => S.activos[S.indice];

function nombreDescarga() {
  const it = actual();
  if (it.base) return it.base;
  const limpio = String(it.nombre || "activo")
    .replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  return `${String(it.activo?.id || "activo").toLowerCase()}_${limpio || "activo"}`;
}

$("btn-md-descargar").addEventListener("click", async () => {
  await refrescarPreview();
  const it = actual();
  descargar(`${nombreDescarga()}.md`, it.markdown || "", "text/markdown");
});

$("btn-json-descargar").addEventListener("click", () => {
  const it = actual();
  descargar(`${nombreDescarga()}.json`,
    JSON.stringify(it.activo, null, 2), "application/json");
});

$("btn-md-copiar").addEventListener("click", async () => {
  await refrescarPreview();
  await navigator.clipboard.writeText(actual().markdown || "");
  confirmar("Markdown copiado al portapapeles.");
});

$("btn-json-copiar").addEventListener("click", async () => {
  await navigator.clipboard.writeText(JSON.stringify(actual().activo, null, 2));
  confirmar("JSON copiado al portapapeles.");
});

$("btn-guardar-disco").addEventListener("click", async () => {
  mostrarError(7, "");
  const carpeta = $("carpeta-destino").value.trim().replace(/^"|"$/g, "");
  if (!carpeta) return mostrarError(7, "Escribe la carpeta destino.");
  const btn = $("btn-guardar-disco");
  btn.disabled = true;
  try {
    const it = actual();
    const r = await pedir("/api/exportar", json({
      activo: it.activo, carpeta, texto: it.texto || "",
      ruta_origen: it.nombre,
    }));
    confirmar(`Guardado en ${r.carpeta}`);
  } catch (e) {
    mostrarError(7, e.message);
  } finally {
    btn.disabled = false;
  }
});

function confirmar(mensaje) {
  const el = $("confirmacion");
  el.textContent = mensaje;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 6000);
}

$("btn-reiniciar").addEventListener("click", () => {
  S.activos = []; S.alcance = null; S.loteId = null; S.archivoSubido = null;
  $("ruta").value = ""; $("input-archivo").value = "";
  [1, 2, 3, 4, 5, 6, 7].forEach((n) => mostrarError(n, ""));
  S.alcanzado = 1;          // se vuelve a cerrar el camino
  $("llenado-ok").hidden = true;
  $("diff-llenado").hidden = true;
  $("btn-ver-cambios").hidden = true;
  $("btn-deshacer-llenado").hidden = true;
  irA(1);
});

/* =========================================================================
   CONFIGURACIÓN
   La API key se escribe aquí pero NUNCA regresa del servidor: al recargar,
   el campo queda vacío con un marcador de que sí hay llave guardada. Dejarlo
   vacío al guardar conserva la que ya estaba.
   ========================================================================= */

function pintarConfig(c) {
  S.config = c;

  $("cfg-modo").innerHTML = c.modos.map((m) =>
    `<option value="${esc(m.valor)}"${m.valor === c.ai_modo ? " selected" : ""}>${esc(m.etiqueta)}</option>`).join("");

  $("cfg-modelo-claude").innerHTML = c.modelos_claude.map((m) =>
    `<option${m === c.anthropic_model ? " selected" : ""}>${esc(m)}</option>`).join("");

  $("cfg-workspace").value = c.anthropic_workspace_id || "";
  $("cfg-modelo-ollama").value = c.ollama_model || "";
  $("cfg-host").value = c.ollama_host || "";
  $("cfg-maxchars").value = c.ollama_max_chars || "";
  $("ruta-env").textContent = c.ruta_env || ".env";

  // El campo de la llave SIEMPRE arranca vacío. Solo se indica si hay una.
  $("cfg-key").value = "";
  const marca = $("estado-llave");
  if (c.tiene_llave) {
    marca.textContent = `guardada · ${c.llave_enmascarada}`;
    marca.className = "etiqueta ok-chip";
    $("cfg-key").placeholder = "Déjalo vacío para conservar la actual";
  } else {
    marca.textContent = "sin llave";
    marca.className = "etiqueta aviso-chip";
    $("cfg-key").placeholder = "sk-ant-api03-...";
  }

  alternarGrupos();
}

function alternarGrupos() {
  const modo = $("cfg-modo").value;
  const usaClaude = modo === "claude" || modo === "";
  const usaLocal = modo !== "claude";
  $("grupo-claude").classList.toggle("apagado", !usaClaude);
  $("grupo-ollama").classList.toggle("apagado", !usaLocal);
}

$("cfg-modo").addEventListener("change", alternarGrupos);

function mensajeConfig(texto, esError) {
  $("config-ok").hidden = esError || !texto;
  $("config-error").hidden = !esError || !texto;
  ($(esError ? "config-error" : "config-ok")).textContent = texto || "";
}

$("btn-config").addEventListener("click", async () => {
  mensajeConfig("", false);
  try {
    pintarConfig(await pedir("/api/config"));
  } catch (e) {
    return mostrarError(1, e.message);
  }
  abrirConfig();
});

// La configuración es una PANTALLA APARTE, no un paso del flujo: se oculta
// tambien la barra de pasos para que no parezca que estas a media consulta.
function abrirConfig() {
  for (let i = 1; i <= 7; i++) $(`paso-${i}`).hidden = true;
  $("pasos-nav").hidden = true;
  $("panel-conciliar").hidden = true;
  $("panel-tdd2").hidden = true;
  $("panel-docs").hidden = true;
  $("panel-config").hidden = false;
  $("btn-config").classList.add("activo");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function cerrarConfig() {
  $("panel-config").hidden = true;
  $("pasos-nav").hidden = false;
  $("btn-config").classList.remove("activo");
  mensajeConfig("", false);
  irA(1);
}

$("btn-cerrar-config").addEventListener("click", cerrarConfig);
$("btn-cancelar-config").addEventListener("click", cerrarConfig);

function cuerpoConfig() {
  return {
    ai_modo: $("cfg-modo").value,
    anthropic_api_key: $("cfg-key").value,
    anthropic_workspace_id: $("cfg-workspace").value,
    anthropic_model: $("cfg-modelo-claude").value,
    ollama_model: $("cfg-modelo-ollama").value,
    ollama_host: $("cfg-host").value,
    ollama_max_chars: $("cfg-maxchars").value,
  };
}

$("btn-guardar-config").addEventListener("click", async () => {
  mensajeConfig("", false);
  const btn = $("btn-guardar-config");
  btn.disabled = true;
  try {
    const r = await pedir("/api/config", json(cuerpoConfig()));
    pintarConfig(r.estado);

    const prov = $("sello-proveedor");
    prov.textContent = r.proveedor_activo === "ollama"
      ? "Modo local · sin API key" : "Claude API";

    // Guardar cierra la pantalla y regresa al inicio. El aviso aparece alla,
    // para que quede claro que el guardado si ocurrio.
    cerrarConfig();
    avisoInicio(r.cambios.length
      ? `Configuracion guardada. Proveedor activo: ${r.proveedor_activo}.`
      : "Sin cambios que guardar.");
  } catch (e) {
    mensajeConfig(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

$("btn-probar-config").addEventListener("click", async () => {
  mensajeConfig("Probando…", false);
  const btn = $("btn-probar-config");
  btn.disabled = true;
  try {
    const r = await pedir("/api/config/probar", json({ proveedor: $("cfg-modo").value }));
    mensajeConfig(`${r.ok ? "✓" : "✗"} ${r.mensaje}`, !r.ok);
  } catch (e) {
    mensajeConfig(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

$("btn-borrar-llave").addEventListener("click", async () => {
  mensajeConfig("", false);
  try {
    const r = await pedir("/api/config/borrar-llave", { method: "POST" });
    pintarConfig(r.estado);
    mensajeConfig("La llave se eliminó del .env.", false);
  } catch (e) {
    mensajeConfig(e.message, true);
  }
});


/* Aviso breve en la pantalla de inicio, tras guardar la configuracion. */
function avisoInicio(texto) {
  let caja = $("aviso-inicio");
  if (!caja) {
    caja = document.createElement("p");
    caja.id = "aviso-inicio";
    caja.className = "confirmacion";
    const p1 = $("paso-1");
    p1.insertBefore(caja, p1.children[1] || null);
  }
  caja.textContent = texto;
  caja.hidden = false;
  setTimeout(() => { caja.hidden = true; }, 7000);
}
