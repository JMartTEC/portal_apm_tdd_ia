/* =========================================================================
   paso5.js -- "Llenado de APM"
   ========================================================================= */

let resultado = null;
let item = null;

function propuesta() {
  return item?.activo?._llenado?.apm || null;
}

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
  const p = propuesta();
  const caja = $("ficha-llenado");

  pintarSelectorManual("5", item);

  if (!p) {
    pintarCabeceraModulo5(item.activo);
    $("resumen-llenado-apm").innerHTML = "";
    caja.innerHTML = `<p class="nota">Este documento no quedó identificado con
      ningún aplicativo del APM (o se analizó con una versión anterior), así
      que no hay con qué compararlo: no se propone llenar nada.</p>`;
    $("btn-llenar").disabled = true;
    pintarBotonNuevaVersion(item, "5", "apm", false,
      "Este documento no está identificado con un aplicativo real del inventario");
    return;
  }
  $("btn-llenar").disabled = false;
  pintarCabeceraModulo5(item.activo);
  pintarBotonNuevaVersion(item, "5", "apm", !!item.activo?._apm?.identificado,
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
            return `
          <div class="campo-llenado est-calculado">
            <label for="ll-apm-${c.clave}">${esc(c.etiqueta)}</label>
            <input id="ll-apm-${c.clave}" value="${esc(c.valor)}"
                   placeholder="sin valor calculado" disabled>
            <span class="marca-estado">${esc(ESTADO_TEXTO.calculado)}</span>
          </div>`;
          }
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

  caja.querySelectorAll("[data-clave]").forEach((el) =>
    el.addEventListener("change", async () => {
      item.activo.ficha_apm = item.activo.ficha_apm || {};
      item.activo.ficha_apm[el.dataset.clave] = el.value.trim();
      item.markdown = null;
      await guardarDocumentoActual(resultado, item);
      pintarLlenado();
    }));
}

$("btn-llenar").addEventListener("click", async () => {
  mostrarError(5, "");
  const btn = $("btn-llenar");
  btn.disabled = true;
  try {
    const r = await pedir("/api/llenado/aplicar", json({ activo: item.activo }));

    item.fichasPrevias = {
      apm: { ...(item.activo.ficha_apm || {}) },
      tdd: { ...(item.activo.ficha_tdd || {}) },
    };
    item.activo.ficha_apm = r.fichas.apm;
    item.activo.ficha_tdd = r.fichas.tdd;
    item.cambiosLlenado = r.cambios;
    item.markdown = null;
    await guardarDocumentoActual(resultado, item);

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
  } catch (e) {
    mostrarError(5, e.message);
  } finally {
    btn.disabled = false;
  }
});

function pintarDiff() {
  const cambios = item?.cambiosLlenado;
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

$("btn-deshacer-llenado").addEventListener("click", async () => {
  if (!item.fichasPrevias) return;
  item.activo.ficha_apm = { ...item.fichasPrevias.apm };
  item.activo.ficha_tdd = { ...item.fichasPrevias.tdd };
  item.cambiosLlenado = null;
  item.markdown = null;
  await guardarDocumentoActual(resultado, item);
  $("diff-llenado").hidden = true;
  $("btn-ver-cambios").hidden = true;
  $("btn-deshacer-llenado").hidden = true;
  $("llenado-ok").textContent = "Se deshizo el llenado. Las fichas volvieron a como estaban.";
  pintarLlenado();
});

$("btn-aplicar-manual-5").addEventListener("click", async () => {
  const ok = await usarAplicativoManual("5", item, Estado.get("rutaApm"));
  if (ok) {
    await guardarDocumentoActual(resultado, item);
    pintarLlenado();
  }
});

$("btn-nueva-version-5").addEventListener("click", async () => {
  await hacerNuevaVersion(item, "5", "apm", "/api/llenado/nueva-version-apm", { ruta_apm: Estado.get("rutaApm") });
  await guardarDocumentoActual(resultado, item);
  pintarLlenado();
});

$("btn-otro-habilitador-5").addEventListener("click", () => {
  // Vuelve al paso 4, donde vive el selector "Comparar contra": ahi se
  // puede elegir otro de los habilitadores que menciona el documento y
  // repetir el llenado para ese otro.
  location.href = "/paso/4";
});

$("btn-continuar-5").addEventListener("click", () => {
  mostrarError(5, "");
  Estado.set("alcanzado", 6);
  location.href = "/paso/6";
});

(async () => {
  resultado = await cargarResultadoSesion();
  if (!resultado) {
    mostrarError(5, "No hay ningún documento en revisión. Vuelve a Inicio.");
    $("btn-llenar").disabled = true;
    return;
  }
  item = await cargarDocumentoActual(resultado);
  if (!item) {
    mostrarError(5, "No hay ningún documento en revisión. Vuelve a Inicio.");
    return;
  }
  pintarLlenado();
  if (item.cambiosLlenado) {
    pintarDiff();
    $("btn-ver-cambios").hidden = false;
    $("btn-deshacer-llenado").hidden = false;
  }
})();
