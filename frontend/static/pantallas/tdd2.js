/* =========================================================================
   tdd2.js
   La pantalla "Comparar TDD Nivel 2".

   Comparte con comun.js sus utilidades globales ($, esc, pedir, json,
   ESTADOS, abrirEtapa, subir) y con conciliar.js el mismo espíritu, pero
   vive en su propia página (/tdd2) en vez de un panel que se mostraba u
   ocultaba con JS.

   La diferencia de fondo con "Comparar APM": aqui NO se llena nada desde el
   APM ni desde una version anterior del TDD -- se comparan DOS documentos
   que una persona ya lleno bajo las reglas del TDD Nivel 2 (el que se sube,
   contra el que ya esta sembrado como referencia de ese aplicativo), campo
   por campo, y toda diferencia queda como conflicto abierto. La misma
   compuerta que "Comparar APM": el boton de guardar esta apagado mientras
   quede un solo campo sin decidir.
   ========================================================================= */

const T2 = {
  aplicativo: null,
  propuestas: [],
  decisiones: {},         // clave (seccion::campo) -> valor escogido
  rutaDocSubido: "",
};

function errT2(mensaje) {
  const el = $("tdd2-error");
  el.textContent = mensaje || "";
  el.hidden = !mensaje;
  if (mensaje) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

$("tdd2-subir-doc").addEventListener("change", async (e) => {
  errT2("");
  const archivos = [...e.target.files];
  if (!archivos.length) return;
  try {
    const guardados = await subir(archivos, "el TDD Nivel 2", errT2);
    if (guardados.length) {
      $("tdd2-ruta-doc").value = guardados[0].ruta;
    }
  } catch (err) { errT2(err.message); }
  e.target.value = "";
});

/* ---------- 1 · abrir el libro y sembrar la referencia ---------- */

$("tdd2-btn-abrir-apm").addEventListener("click", async () => {
  errT2("");
  const ruta = $("tdd2-ruta-apm").value.trim().replace(/^"|"$/g, "");
  if (!ruta) return errT2("Escribe la ruta del archivo .xlsx del APM.");
  const btn = $("tdd2-btn-abrir-apm");
  btn.disabled = true;
  try {
    await pedir("/api/apm/abrir", json({ ruta }));
    $("tdd2-btn-sembrar").disabled = false;
    abrirEtapa("tdd2-etapa-subir");
    verReferenciaTdd2();
  } catch (e) {
    errT2(e.message);
  } finally {
    btn.disabled = false;
  }
});

$("tdd2-btn-sembrar").addEventListener("click", async () => {
  errT2("");
  const ruta_apm = $("tdd2-ruta-apm").value.trim().replace(/^"|"$/g, "");
  if (!ruta_apm) return errT2("Abre primero el libro de APM.");
  const btn = $("tdd2-btn-sembrar");
  btn.disabled = true;
  try {
    const r = await pedir("/api/tdd2/sembrar", json({ ruta_apm }));
    const colisiones = Object.entries(r.colisiones || {});
    $("tdd2-resumen-siembra").innerHTML = `
      <div class="aviso-caja">
        <b>Referencia sembrada.</b>
        <p>${r.identificados.length} TDD Nivel 2 identificados y adoptados como línea base.</p>
        ${r.sin_identificar.length ? `<p class="nota-alerta">
          <b>${r.sin_identificar.length} no se pudieron identificar:</b>
          ${r.sin_identificar.map((s) => `${esc(s.nombre)} (${esc(s.motivo)})`).join(", ")}</p>` : ""}
        ${colisiones.length ? `<p class="nota-alerta">
          <b>Colisiones -- más de un archivo apuntó al mismo aplicativo:</b>
          ${colisiones.map(([n, arch]) => `#${esc(n)}: ${arch.map(esc).join(" · ")}`).join(" — ")}</p>` : ""}
      </div>`;
    $("tdd2-resumen-siembra").hidden = false;
    verReferenciaTdd2();
  } catch (e) {
    errT2(e.message);
  } finally {
    btn.disabled = false;
  }
});

async function verReferenciaTdd2() {
  try {
    const r = await pedir("/api/tdd2/referencia");
    const lista = r.habilitadores || [];
    const conRef = lista.filter((h) => h.tdd2_nombre);
    $("tdd2-resumen-referencia").innerHTML = `
      <div class="resumen">
        <div class="dato"><b>${conRef.length}</b><span>con TDD Nivel 2 de referencia</span></div>
        <div class="dato ${lista.length - conRef.length ? "alerta" : ""}">
          <b>${lista.length - conRef.length}</b><span>todavía sin referencia</span></div>
      </div>`;
    $("tdd2-resumen-referencia").hidden = false;
  } catch { /* la referencia es opcional: si falla, la pantalla sigue sirviendo */ }
}

/* ---------- 2 · subir y comparar ---------- */

$("tdd2-btn-comparar").addEventListener("click", async () => {
  errT2("");
  const ruta_apm = $("tdd2-ruta-apm").value.trim().replace(/^"|"$/g, "");
  const ruta_tdd2 = $("tdd2-ruta-doc").value.trim().replace(/^"|"$/g, "");
  if (!ruta_apm) return errT2("Abre primero el libro de APM (paso 1).");
  if (!ruta_tdd2) return errT2("Sube o escribe la ruta del TDD Nivel 2 a revisar.");
  const btn = $("tdd2-btn-comparar");
  btn.disabled = true;
  try {
    const r = await pedir("/api/tdd2/comparar", json({ ruta_apm, ruta_tdd2 }));
    pintarResultadoTdd2(r, ruta_tdd2);
  } catch (e) {
    errT2(e.message);
  } finally {
    btn.disabled = false;
  }
});

function pintarResultadoTdd2(r, rutaDoc) {
  const caja = $("tdd2-resultado");

  if (!r.identificado) {
    caja.innerHTML = `<div class="aviso-caja"><b>No se pudo amarrar a un aplicativo.</b>
        <p>${esc(r.mensaje)}</p></div>
      <div class="resumen">
        <div class="dato"><b>${r.documento.campos_con_dato}</b><span>campos con dato</span></div>
        <div class="dato"><b>${r.documento.campos_totales}</b><span>campos totales</span></div>
      </div>`;
    caja.hidden = false;
    return;
  }

  T2.aplicativo = r.aplicativo;
  T2.propuestas = r.propuestas;
  T2.decisiones = {};
  T2.rutaDocSubido = rutaDoc;

  caja.innerHTML = `
    <div class="resumen">
      <div class="dato"><b>#${esc(r.aplicativo.numero)}</b><span>${esc(r.aplicativo.nombre)}</span></div>
      <div class="dato"><b>${r.documento.campos_con_dato}</b><span>campos con dato</span></div>
      <div class="dato ${r.resumen.exigen_decision ? "alerta" : ""}">
        <b>${r.resumen.exigen_decision}</b><span>exigen tu decisión</span></div>
    </div>
    ${r.hay_referencia_previa
      ? `<p class="nota">Comparado contra la referencia ya sembrada de este aplicativo
           (actualizada el ${esc((r.referencia.actualizado_en || "").slice(0, 10))}).</p>`
      : `<p class="nota-alerta"><b>Este aplicativo todavía no tiene un TDD Nivel 2 de
           referencia.</b> Lo que decidas aquí abajo se adopta completo como la
           primera referencia -- no hay con qué compararlo campo por campo todavía.</p>`}
    <div id="tdd2-lista"></div>
    <p class="confirmacion" id="tdd2-ok" hidden></p>
    <div class="acciones">
      <button class="btn" id="tdd2-btn-guardar" type="button" disabled>
        Guardar como referencia</button>
      <span class="nota" id="tdd2-aviso-compuerta"></span>
    </div>`;
  caja.hidden = false;
  $("tdd2-btn-guardar").addEventListener("click", guardarTdd2);
  pintarPropuestasTdd2();
}

function pintarPropuestasTdd2() {
  const lista = $("tdd2-lista");
  if (!T2.propuestas.length) {
    lista.innerHTML = `<p class="nota">El documento subido no trae ningún campo
      con dato que comparar.</p>`;
    $("tdd2-aviso-compuerta").textContent = "Nada que guardar.";
    const btn = $("tdd2-btn-guardar");
    if (btn) btn.disabled = true;
    return;
  }

  lista.innerHTML = T2.propuestas.map((p, i) => {
    const est = ESTADOS[p.estado] || { texto: p.estado, clase: "e-gris" };
    const decidido = T2.decisiones[p.clave] !== undefined;
    const opciones = [];
    if (p.valor_actual) opciones.push({ v: p.valor_actual, t: `dejar el de la referencia: «${p.valor_actual}»` });
    for (const c of p.candidatos) opciones.push({ v: c.valor, t: `«${c.valor}» — el documento subido` });

    return `<article class="campo-conc ${est.clase} ${decidido ? "decidido" : ""}">
      <header>
        <b>${esc(p.etiqueta)}</b>
        <span class="nota">${esc(p.grupo)}</span>
        <span class="pil ${est.clase}">${esc(est.texto)}</span>
        ${decidido ? `<span class="pil e-ok">decidido</span>` : ""}
      </header>
      ${p.motivo ? `<p class="nota">${esc(p.motivo)}</p>` : ""}
      ${p.nota ? `<p class="nota nota-alerta">${esc(p.nota)}</p>` : ""}
      <div class="comparacion">
        <div><span class="etq">En la referencia</span>
             <span class="val">${esc(p.valor_actual) || "<i>vacío</i>"}</span></div>
        ${p.candidatos.map((c) => `<div><span class="etq">${esc(c.documento)}</span>
             <span class="val">${esc(c.valor)}</span>
             <span class="evidencia">${esc(c.evidencia)}</span></div>`).join("")}
      </div>
      <div class="decidir">
        <label for="tdd2-dec-${i}">Qué se guarda en la referencia</label>
        <select id="tdd2-dec-${i}" data-clave="${esc(p.clave)}">
          <option value="__nada__">— no cambiar nada —</option>
          ${opciones.map((o) => `<option value="${esc(o.v)}"${
            T2.decisiones[p.clave] === o.v ? " selected" : ""}>${esc(o.t)}</option>`).join("")}
        </select>
      </div>
    </article>`;
  }).join("");

  lista.querySelectorAll("[data-clave]").forEach((el) =>
    el.addEventListener("change", () => {
      T2.decisiones[el.dataset.clave] = el.value === "__nada__" ? "" : el.value;
      pintarPropuestasTdd2();
      revisarCompuertaTdd2();
    }));
  revisarCompuertaTdd2();
}

/* La compuerta, igual que en conciliar.js: mientras quede un campo que exige
   decision sin una, guardar esta apagado. */
function revisarCompuertaTdd2() {
  const faltan = T2.propuestas.filter(
    (p) => p.exige_decision && T2.decisiones[p.clave] === undefined);
  const btn = $("tdd2-btn-guardar");
  if (!btn) return;
  btn.disabled = faltan.length > 0;
  $("tdd2-aviso-compuerta").textContent = faltan.length
    ? `Faltan ${faltan.length} por decidir: ${faltan.slice(0, 3).map((p) => p.etiqueta).join(", ")}`
      + (faltan.length > 3 ? "…" : "")
    : "Todo revisado. Se puede guardar.";
}

async function guardarTdd2() {
  errT2("");
  const btn = $("tdd2-btn-guardar");
  btn.disabled = true;
  try {
    const r = await pedir("/api/tdd2/guardar", json({
      ruta_tdd2: T2.rutaDocSubido,
      numero: T2.aplicativo.numero,
      propuestas: T2.propuestas,
      decisiones: T2.decisiones,
    }));
    const ok = $("tdd2-ok");
    if (r.sin_cambios) {
      ok.innerHTML = esc(r.mensaje);
    } else if (r.primera_siembra) {
      ok.innerHTML = `Adoptado como la primera referencia de este aplicativo
        (<b>${esc(r.nombre)}</b>). La próxima vez que subas un TDD Nivel 2 de
        este aplicativo, se comparará contra esto.`;
    } else {
      const descarga = r.archivo
        ? ` · <a href="/api/descargar?ruta=${encodeURIComponent(r.archivo)}">Descargar</a>` : "";
      ok.innerHTML = `Guardado en <b>${esc(r.nombre)}</b> — ${r.aplicados.length} campos
        actualizados en la referencia.${descarga}`
        + ((r.rechazados || []).length
            ? `<br><b>${r.rechazados.length} rechazados:</b> `
              + r.rechazados.map((x) => esc(x.motivo)).join("; ")
            : "");
    }
    ok.hidden = false;
    verReferenciaTdd2();
  } catch (e) {
    errT2(e.message);
  } finally {
    revisarCompuertaTdd2();
  }
}

verReferenciaTdd2();
