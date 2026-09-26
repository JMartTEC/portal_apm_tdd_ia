/* =========================================================================
   paso4.js -- "Revisión y Vectorización"
   ========================================================================= */

const ETIQUETAS = {
  id: "Identificador", tipo: "Tipo de activo", descripcion: "Descripción",
  version: "Versión", estado: "Estado", responsable: "Responsable",
  fecha: "Fecha", fuente: "Fuente", confidencialidad: "Confidencialidad",
};

let resultado = null;
let item = null;
let catalogos = null;
let nombresLista = [];
let revisados = new Set();

/* Panel fijo de habilitadores (antes un <select> de uno en uno): pinta todos
   los documentos del lote con su estado, para que seleccionar uno no haga
   perder de vista a los demas pendientes. */
function renderListaHabilitadores() {
  const ul = $("lista-habilitadores");
  if (!ul) return;
  ul.innerHTML = nombresLista.map((n, i) => {
    const activo = i === (resultado?.indice ?? 0);
    const hecho = revisados.has(i);
    return `<li class="item-habilitador${activo ? " activo" : ""}${hecho ? " revisado" : ""}" data-indice="${i}">
      <span class="lh-nombre">${esc(n)}</span>
      <span class="lh-estado">${hecho ? "Revisado" : "Pendiente"}</span>
    </li>`;
  }).join("");
  ul.querySelectorAll("li").forEach((li) =>
    li.addEventListener("click", () => cambiarDocumento(Number(li.dataset.indice))));
}

function pintarOmitidos() {
  const igual = resultado.activosOmitidos.find((o) => o.mismoEnSistema);
  const resto = resultado.activosOmitidos.filter((o) => !o.mismoEnSistema);

  const tarjeta = $("tarjeta-igual-sistema");
  if (igual) {
    tarjeta.innerHTML = `
      <div class="omitido-igual">
        <div class="omitido-igual-nombre"><code>${esc(igual.nombre)}</code></div>
        ${igual.fecha ? `<div class="omitido-igual-fecha">${esc(igual.fecha)}</div>` : ""}
        <p class="omitido-igual-leyenda">Este archivo es igual al que está en el sistema.</p>
        <div class="omitido-igual-acciones">
          <button class="btn btn-sec" data-forzar-omitido type="button"
                  ${igual.ruta ? "" : "disabled title=\"Se subió desde el navegador: vuelve a Inicio y súbelo de nuevo para forzar la revisión\""}>
            Pasar solo para revisión</button>
          <button class="btn btn-sec" data-volver-inicio-omitido type="button">Volver a inicio</button>
        </div>
      </div>`;
    tarjeta.hidden = false;
    tarjeta.querySelector("[data-forzar-omitido]")
      .addEventListener("click", () => forzarRevision(igual.ruta));
    tarjeta.querySelector("[data-volver-inicio-omitido]")
      .addEventListener("click", () => { limpiarEstadoAsistente(); location.href = "/"; });
  } else {
    tarjeta.hidden = true;
    tarjeta.innerHTML = "";
  }

  $("n-omitidos").textContent = resto.length;
  $("det-omitidos").hidden = resto.length === 0;
  $("lista-omitidos").innerHTML = resto.map((o) =>
    `<li><code>${esc(o.nombre)}</code> — ${esc(o.motivo)}</li>`).join("");
}

async function forzarRevision(ruta) {
  mostrarError(4, "");
  try {
    const r = await pedir("/api/analyze-ruta", json({ ruta, ruta_apm: Estado.get("rutaApm"), forzar: true }));
    if (r.excluido) {
      // Sigue siendo el propio APM/TDD incluso forzado: no hay nada más que hacer.
      return mostrarError(4, "Este documento es el propio APM o un TDD -- no se puede revisar como fuente.");
    }
    resultado = {
      modoLote: false, loteId: null, nombres: [],
      activos: [{
        nombre: r.activo._documento?.nombre_archivo || ruta,
        activo: r.activo, texto: "", markdown: r.markdown,
        base: r.nombre_sugerido, ruta,
      }],
      activosOmitidos: [], indice: 0,
    };
    await guardarResultadoSesion(resultado);
    Estado.set("indice", 0);
    location.reload();
  } catch (e) {
    mostrarError(4, e.message);
  }
}

function pintarAplicativoRef(activo) {
  const info = activo?._apm;
  const el = $("aplicativo-ref");
  if (!info) { el.hidden = true; return; }

  if (!info.disponible) {
    // Antes esto se dejaba en blanco -- la pantalla no decia nada de a que
    // habilitador pertenece el documento, ni por que no se sabia. Ahora
    // siempre se deja alguna referencia, aunque sea para explicar que no se
    // pudo verificar (y contra que, si se sabe).
    el.innerHTML = info.sin_libro
      ? `<p class="nota-alerta">
          <b>No se verificó contra ningún habilitador:</b> esta base no tiene
          un libro de APM Portafolio configurado todavía, así que no hay
          contra qué comparar el documento.</p>`
      : `<p class="nota-alerta">
          <b>No se pudo verificar contra el inventario de APM Portafolio:</b>
          ${esc((info.error || info.motivo || "ocurrió un problema al intentar amarrar el documento a un habilitador")
            .replace(/\.+$/, ""))}.</p>`;
    el.hidden = false;
    return;
  }

  if (!info.identificado) {
    if (info.aplicacion_nueva) {
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
  if (!item) return;
  const a = item.activo;
  pintarAplicativoRef(a);
  pintarSelectorManual("4", item);

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
    const cat = catalogos[
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
    el.addEventListener("change", async () => {
      a[el.dataset.campo] = el.value;
      item.markdown = null;
      await guardarDocumentoActual(resultado, item);
      revisados.add(resultado.indice);
      renderListaHabilitadores();
    }));

  $("observaciones").hidden = !(a.observaciones?.length);
  $("lista-observaciones").innerHTML =
    (a.observaciones || []).map((o) => `<li>${esc(o)}</li>`).join("");

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

async function cambiarDocumento(indice) {
  resultado.indice = indice;
  Estado.set("indice", indice);
  item = await cargarDocumentoActual(resultado);
  pintarActivo();
  renderListaHabilitadores();
}

$("btn-aplicar-manual-4").addEventListener("click", async () => {
  const ok = await usarAplicativoManual("4", item, Estado.get("rutaApm"));
  if (ok) {
    await guardarDocumentoActual(resultado, item);
    pintarActivo();
  }
});

$("btn-continuar-4").addEventListener("click", async () => {
  mostrarError(4, "");
  if (item) {
    try { await pedir("/api/validate", json({ activo: item.activo, decision: "aceptado" })); }
    catch { /* la validacion no bloquea la continuacion */ }
  }
  Estado.set("alcanzado", 5);
  location.href = "/paso/5";
});

(async () => {
  resultado = await cargarResultadoSesion();
  catalogos = await cargarCatalogos();
  if (!resultado) {
    mostrarError(4, "No hay ningún resultado de análisis en curso. Vuelve a Inicio.");
    $("btn-continuar-4").disabled = true;
    return;
  }
  pintarOmitidos();

  const total = resultado.modoLote ? resultado.nombres.length : resultado.activos.length;
  if (total === 0) {
    $("panel-habilitadores").hidden = true;
    $("aplicativo-ref").hidden = true;
    $("nota-campos-ficha").hidden = true;
    return;
  }

  const panel = $("panel-habilitadores");
  panel.hidden = total < 2;
  if (!panel.hidden) {
    nombresLista = resultado.modoLote ? resultado.nombres : resultado.activos.map((a) => a.nombre);
    if (resultado.modoLote && resultado.loteId) {
      try {
        const r = await pedir(`/api/sesion/lote/${resultado.loteId}`);
        revisados = new Set(r.editados || []);
      } catch { revisados = new Set(); }
    }
    renderListaHabilitadores();
  }
  $("nota-campos-ficha").hidden = false;
  await cambiarDocumento(resultado.indice || 0);
})();
