/* =========================================================================
   paso6.js -- "Llenado de TDD"
   ========================================================================= */

let resultado = null;
let item = null;

function propuestaTdd() {
  return item?.activo?._llenado?.tdd || null;
}

function pintarBotonDiagramas() {
  const imagenes = item?.activo?._imagenes || [];
  $("bloque-ver-diagramas").hidden = imagenes.length === 0;
  $("n-diagramas").textContent = `(${imagenes.length})`;
}

function abrirModalDiagramas() {
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
  const p = propuestaTdd();
  pintarCabeceraModulo6(item.activo);
  pintarSelectorManual("6", item);
  pintarBotonDiagramas();
  const caja = $("ficha-tdd");
  const resumenEl = $("resumen-llenado-tdd");

  if (!p || !p.grupos || !p.grupos.length) {
    resumenEl.innerHTML = "";
    caja.innerHTML = `<p class="nota">No hay ninguna ficha de TDD que mostrar
      para este documento.</p>`;
    pintarBotonNuevaVersion(item, "6", "tdd", false,
      "No hay ninguna ficha de TDD para este documento");
    return;
  }

  pintarBotonNuevaVersion(item, "6", "tdd", !p.es_propuesta,
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
    el.addEventListener("change", async () => {
      item.activo.ficha_tdd = item.activo.ficha_tdd || {};
      item.activo.ficha_tdd[el.dataset.claveTdd] = el.value.trim();
      item.markdown = null;
      await guardarDocumentoActual(resultado, item);
      pintarTdd();
    }));
}

$("btn-aplicar-manual-6").addEventListener("click", async () => {
  const ok = await usarAplicativoManual("6", item, Estado.get("rutaApm"));
  if (ok) {
    await guardarDocumentoActual(resultado, item);
    pintarTdd();
  }
});

$("btn-nueva-version-6").addEventListener("click", async () => {
  await hacerNuevaVersion(item, "6", "tdd", "/api/llenado/nueva-version-tdd", {});
  await guardarDocumentoActual(resultado, item);
  pintarTdd();
});

$("btn-otro-habilitador-6").addEventListener("click", () => {
  location.href = "/paso/4";
});

$("btn-continuar-6").addEventListener("click", async () => {
  mostrarError(6, "");
  Estado.set("alcanzado", 7);
  location.href = "/paso/7";
});

(async () => {
  resultado = await cargarResultadoSesion();
  if (!resultado) {
    mostrarError(6, "No hay ningún documento en revisión. Vuelve a Inicio.");
    return;
  }
  item = await cargarDocumentoActual(resultado);
  if (!item) {
    mostrarError(6, "No hay ningún documento en revisión. Vuelve a Inicio.");
    return;
  }
  pintarTdd();
})();
