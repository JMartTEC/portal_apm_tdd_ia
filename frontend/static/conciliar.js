/* =========================================================================
   conciliar.js -- v6
   La pantalla de comparación manual del APM ("Comparar APM").

   El TDD Nivel 2 se comparaba aquí mismo hasta la v5; ahora vive aparte, en
   tdd2.js y su propio botón "Comparar TDD Nivel 2" -- son dos formularios
   distintos (uno contra el libro de APM, otro entre dos TDD Nivel 2) y
   mezclarlos volvia ilegibles los dos. El TDD_V3 (`/api/conciliar/tdd`,
   `/api/conciliar/guardar-tdd`) ya no se usa desde ningún botón del front.

   Vive en un archivo aparte de app.js a proposito: es un flujo distinto, con
   otro vocabulario y otras reglas, y mezclarlo con el asistente de
   clasificacion habria vuelto ilegibles los dos.

   La regla que gobierna la pantalla entera: **el boton de guardar esta
   deshabilitado mientras quede un solo campo sin decidir.** No es un aviso que
   se pueda ignorar; es una compuerta. Un conflicto que se guarda "para no
   detener el trabajo" es un dato malo que entra al inventario sin que nadie
   vuelva a mirarlo.
   ========================================================================= */

const C = {
  libro: null,            // respuesta de /api/apm/abrir
  fuentes: [],            // documentos aceptados, con su aplicativo
  aplicativo: null,
  propuestas: [],         // del paso APM
  decisiones: {},         // clave -> valor escogido por la persona
  subidos: [],            // rutas de lo que se subio por el navegador
};

/* ---------- subida de archivos ----------
   El navegador NO entrega la ruta real de un archivo: por seguridad la esconde,
   y solo da el contenido. Por eso subir y escribir la ruta son dos mecanismos
   distintos, no dos formas de lo mismo. Subir copia el archivo a la carpeta de
   la app y devuelve una ruta que el resto del flujo ya puede usar igual. */

async function subir(archivos, etiqueta) {
  if (!archivos || !archivos.length) return [];
  const cuerpo = new FormData();
  for (const a of archivos) cuerpo.append("files", a, a.name);

  const r = await fetch("/api/conciliar/subir", { method: "POST", body: cuerpo });
  let datos;
  try { datos = await r.json(); } catch { datos = {}; }
  if (!r.ok) throw new Error(datos.detail || `Error ${r.status} al subir`);

  if ((datos.rechazados || []).length) {
    errC(`${datos.rechazados.length} de ${etiqueta} no se pudieron usar: `
      + datos.rechazados.map((x) => `${x.nombre} (${x.motivo})`).join("; "));
  }
  return datos.archivos || [];
}

const ESTADOS = {
  coincide:          { texto: "Ya coincide",            clase: "e-ok" },
  propuesto:         { texto: "Propuesto",              clase: "e-prop" },
  sobre_sin_info:    { texto: "Pisa «Sin información»", clase: "e-ambar" },
  conflicto_fuentes: { texto: "Los documentos difieren", clase: "e-rojo" },
  conflicto_apm:     { texto: "Difiere del APM",        clase: "e-rojo" },
  bloqueado:         { texto: "No se puede escribir",   clase: "e-gris" },
};

function errC(mensaje) {
  const el = $("error-conciliar");
  el.textContent = mensaje || "";
  el.hidden = !mensaje;
  if (mensaje) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

function abrirEtapa(id) { $(id).classList.remove("apagada"); }

/* ---------- entrar y salir ---------- */

$("btn-conciliar").addEventListener("click", () => {
  errC("");
  for (let i = 1; i <= 7; i++) $(`paso-${i}`).hidden = true;
  $("panel-config").hidden = true;
  $("panel-docs").hidden = true;
  $("panel-tdd2").hidden = true;
  $("btn-tdd2").classList.remove("activo");
  $("pasos-nav").hidden = true;
  $("panel-conciliar").hidden = false;
  $("btn-conciliar").classList.add("activo");
  window.scrollTo({ top: 0, behavior: "smooth" });
});

function cerrarConciliar() {
  $("panel-conciliar").hidden = true;
  $("pasos-nav").hidden = false;
  $("btn-conciliar").classList.remove("activo");
  errC("");
  irA(1);
}
$("btn-cerrar-conciliar").addEventListener("click", cerrarConciliar);
$("btn-volver-conciliar").addEventListener("click", cerrarConciliar);

/* Subir el APM o el TDD llena el campo de ruta con la copia que quedo en la
   app. Se muestra la ruta completa a proposito: asi queda claro que la version
   nueva va a nacer ahi y no junto al archivo original del usuario. */
function conectarSubidaSimple(idInput, idCampo, etiqueta) {
  $(idInput).addEventListener("change", async (e) => {
    errC("");
    const archivos = [...e.target.files];
    if (!archivos.length) return;
    try {
      const guardados = await subir(archivos, etiqueta);
      if (guardados.length) {
        $(idCampo).value = guardados[0].ruta;
        $(idCampo).dispatchEvent(new Event("input"));
      }
    } catch (err) { errC(err.message); }
    e.target.value = "";
  });
}
conectarSubidaSimple("subir-apm", "ruta-apm", "el libro de APM");

async function subirFuentes(e, etiqueta) {
  errC("");
  const archivos = [...e.target.files];
  if (!archivos.length) return;
  const btnTexto = $("aviso-subidos");
  btnTexto.textContent = `Subiendo ${archivos.length} archivos…`;
  btnTexto.hidden = false;
  try {
    const guardados = await subir(archivos, etiqueta);
    C.subidos = C.subidos.concat(guardados.map((g) => g.ruta));
    btnTexto.innerHTML = `<b>${guardados.length} archivos listos</b> de los `
      + `${archivos.length} que elegiste. Ya puedes darle a «Revisar los documentos».`;
  } catch (err) {
    btnTexto.hidden = true;
    errC(err.message);
  }
  e.target.value = "";
}
$("subir-archivos").addEventListener("change", (e) => subirFuentes(e, "los archivos"));
$("subir-carpeta").addEventListener("change", (e) => subirFuentes(e, "la carpeta"));

/* ---------- 1 · abrir el libro ---------- */

$("btn-abrir-apm").addEventListener("click", async () => {
  errC("");
  const ruta = $("ruta-apm").value.trim().replace(/^"|"$/g, "");
  if (!ruta) return errC("Escribe la ruta del archivo .xlsx del APM.");
  const btn = $("btn-abrir-apm");
  btn.disabled = true;
  try {
    C.libro = await pedir("/api/apm/abrir", json({ ruta }));
    const r = C.libro.resumen;

    // Se muestra QUE NO se va a poder escribir y por que. Enterarse de eso al
    // guardar, cuando ya se revisaron cuarenta campos, es tarde.
    $("resumen-apm").innerHTML = `
      <div class="resumen">
        <div class="dato"><b>${r.aplicaciones}</b><span>aplicativos</span></div>
        <div class="dato"><b>${r.columnas}</b><span>columnas</span></div>
        <div class="dato"><b>${r.escribibles}</b><span>se pueden escribir</span></div>
        <div class="dato ${r.bloqueadas.length ? "alerta" : ""}">
          <b>${r.bloqueadas.length}</b><span>intocables</span></div>
      </div>
      <p class="nota"><b>No se escriben nunca:</b> ${r.bloqueadas.map((b) =>
        `${esc(b.etiqueta)} <span class="nota">(${esc(b.motivo)})</span>`).join(" · ")}</p>
      ${(r.con_nota || []).length ? `<div class="aviso-caja">
        <b>Ojo con esto en el libro:</b><ul>${r.con_nota.map((n) =>
          `<li>[${esc(n.grupo)}] <b>${esc(n.etiqueta)}</b>: ${esc(n.nota)}</li>`).join("")}</ul>
      </div>` : ""}`;
    $("resumen-apm").hidden = false;

    $("sel-aplicativo").innerHTML = C.libro.aplicaciones.map((a) =>
      `<option value="${esc(a.numero)}">#${esc(a.numero)} · ${esc(a.nombre)}`
      + ` — ${a.vacios} campos vacíos</option>`).join("");

    $("btn-sembrar").disabled = false;
    $("campo-tdd-carpeta").hidden = false;
    abrirEtapa("etapa-fuentes");
    abrirEtapa("etapa-apm");
    verBase();
  } catch (e) {
    errC(e.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- 2 · los documentos fuente ---------- */

$("btn-revisar-fuentes").addEventListener("click", async () => {
  errC("");
  const crudo = $("ruta-fuentes").value.trim();
  const lineas = crudo ? crudo.split("\n").map((l) => l.trim().replace(/^"|"$/g, "")).filter(Boolean) : [];
  if (!lineas.length && !C.subidos.length) {
    return errC("Sube archivos, o pega una URL o una ruta.");
  }
  const cuerpo = { ruta_apm: $("ruta-apm").value.trim().replace(/^"|"$/g, "") };
  // Una sola linea sin extension y sin http se toma como carpeta del disco.
  const esCarpeta = lineas.length === 1 && !C.subidos.length
    && !/\.[a-z0-9]{2,5}$/i.test(lineas[0]) && !/^https?:/i.test(lineas[0]);
  if (esCarpeta) cuerpo.carpeta = lineas[0];
  else cuerpo.rutas = lineas.concat(C.subidos);

  const btn = $("btn-revisar-fuentes");
  btn.disabled = true;
  try {
    const r = await pedir("/api/conciliar/fuentes", json(cuerpo));
    C.fuentes = r.fuentes;
    const sinId = r.fuentes.filter((f) => !f.identificado);
    const sinInfo = r.fuentes.filter((f) => f.identificado && f.aporta_informacion === false);
    const utiles = r.fuentes.length - sinId.length - sinInfo.length;

    $("tabla-fuentes").innerHTML = `
      <div class="resumen">
        <div class="dato"><b>${r.fuentes.length}</b><span>documentos fuente</span></div>
        <div class="dato"><b>${utiles}</b><span>con aplicativo y datos</span></div>
        <div class="dato ${sinId.length ? "alerta" : ""}"><b>${sinId.length}</b>
             <span>sin identificar</span></div>
        <div class="dato ${sinInfo.length ? "alerta" : ""}"><b>${sinInfo.length}</b>
             <span>sin información útil</span></div>
        <div class="dato"><b>${r.reusados || 0}</b><span>ya estaban en la base</span></div>
        <div class="dato"><b>${r.descartados.length}</b><span>descartados</span></div>
      </div>
      ${r.reusados ? `<p class="nota"><b>${r.reusados} no se volvieron a leer:</b>
        su contenido ya estaba en la base, así que se reusó lo que aportaron la
        primera vez. Se reconocen por su huella, no por el nombre — un archivo
        renombrado o copiado sigue siendo el mismo documento.</p>` : ""}
      ${r.fuentes.length ? `<div class="tabla-envoltura"><table class="tabla">
        <thead><tr><th>Documento</th><th>Aplicativo</th><th>Por qué</th></tr></thead>
        <tbody>${r.fuentes.map((f) => `<tr class="${!f.identificado || f.aporta_informacion === false ? "fila-alerta" : ""}">
          <td>${esc(f.nombre)}</td>
          <td>${f.identificado
              ? `#${esc(f.numero)} · <b>${esc(f.nombre_aplicativo)}</b>`
              : `<span class="pil e-rojo">sin identificar</span>`}</td>
          <td><span class="nota">${esc(f.evidencia || "no se encontró ninguna señal")}</span>
              ${f.identificado && f.aporta_informacion === false
                ? `<br><span class="pil e-rojo">sin información útil · no cuenta como aporte,
                   no pasa a Revisión</span>`
                : ""}
              ${f.de_memoria ? `<br><span class="pil e-ok">de la base · ${esc(
                (f.leido_en || "").slice(0, 10))}${f.campos_recordados
                  ? ` · ${f.campos_recordados} campos` : " · sin cambios"}</span>` : ""}</td>
        </tr>`).join("")}</tbody></table></div>` : ""}
      ${r.descartados.length ? `<details class="alterno"><summary>
        ${r.descartados.length} archivos descartados</summary><ul class="lista-fina">
        ${r.descartados.map((d) => `<li><b>${esc(d.nombre)}</b> — ${esc(d.motivo)}</li>`).join("")}
        </ul></details>` : ""}
      ${sinId.length ? `<p class="nota"><b>Los que no se identificaron no se usan.</b>
        Un documento cuyo aplicativo no se puede determinar no aporta datos: repartirlo
        “a lo que se parezca” mete información de un sistema en la ficha de otro.</p>` : ""}
      ${sinInfo.length ? `<p class="nota"><b>Los que no traen información útil tampoco se usan.</b>
        Se identificó a qué aplicativo pertenecen, pero no dicen nada que corresponda a un
        campo del APM ni del TDD — no cuentan como fuente y no pasan a la revisión.</p>` : ""}`;
    $("tabla-fuentes").hidden = false;
  } catch (e) {
    errC(e.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- 3 · el APM ---------- */

$("btn-analizar-apm").addEventListener("click", async () => {
  errC("");
  const numero = $("sel-aplicativo").value;
  const rutas = C.fuentes.filter((f) => f.identificado && f.numero === numero)
                         .map((f) => f.ruta);
  const btn = $("btn-analizar-apm");
  btn.disabled = true;
  try {
    const r = await pedir("/api/conciliar/aplicativo", json({
      ruta_apm: $("ruta-apm").value.trim().replace(/^"|"$/g, ""),
      numero, rutas,
    }));
    C.aplicativo = r.aplicativo;
    C.propuestas = r.propuestas;
    C.decisiones = {};
    pintarAPM(r, rutas.length);
  } catch (e) {
    errC(e.message);
  } finally {
    btn.disabled = false;
  }
});

function pintarAPM(r, nDocs) {
  const caja = $("resultado-apm");
  if (!r.propuestas.length) {
    caja.innerHTML = `<p class="nota">Los ${nDocs} documentos de este aplicativo no
      aportaron ningún dato que corresponda a una columna del APM.</p>`;
    caja.hidden = false;
    return;
  }
  caja.innerHTML = `
    <div class="resumen">
      <div class="dato"><b>${nDocs}</b><span>documentos leídos</span></div>
      <div class="dato"><b>${r.resumen.total}</b><span>campos con algo que decir</span></div>
      <div class="dato ${r.resumen.exigen_decision ? "alerta" : ""}">
        <b>${r.resumen.exigen_decision}</b><span>exigen tu decisión</span></div>
    </div>
    <div id="lista-apm"></div>
    <p class="confirmacion" id="ok-apm" hidden></p>
    <div class="acciones">
      <button class="btn" id="btn-guardar-apm" type="button" disabled>
        Guardar versión nueva del APM</button>
      <span class="nota" id="aviso-compuerta"></span>
    </div>`;
  caja.hidden = false;
  $("btn-guardar-apm").addEventListener("click", guardarAPM);
  pintarPropuestas();
}

function pintarPropuestas() {
  $("lista-apm").innerHTML = C.propuestas.map((p, i) => {
    const est = ESTADOS[p.estado] || { texto: p.estado, clase: "e-gris" };
    // Una decision que esta persona ya tomo antes sobre ESTE mismo conflicto se
    // trae puesta. Solo se reaplica cuando las opciones son identicas: si un
    // documento nuevo trajo otra, la decision vieja no responde la pregunta
    // nueva y hay que volver a preguntarla.
    if (p.decision_previa !== undefined && C.decisiones[p.clave] === undefined) {
      C.decisiones[p.clave] = p.decision_previa;
    }
    const decidido = C.decisiones[p.clave] !== undefined;
    const opciones = [];
    if (p.valor_actual) opciones.push({ v: p.valor_actual, t: `dejar lo del APM: «${p.valor_actual}»` });
    for (const c of p.candidatos) opciones.push({ v: c.valor, t: `«${c.valor}» — ${c.documento}` });

    return `<article class="campo-conc ${est.clase} ${decidido ? "decidido" : ""}">
      <header>
        <b>${esc(p.etiqueta)}</b>
        <span class="nota">${esc(p.grupo)}</span>
        <span class="pil ${est.clase}">${esc(est.texto)}</span>
        ${decidido ? `<span class="pil e-ok">decidido</span>` : ""}
        ${p.decision_previa !== undefined
          ? `<span class="pil e-prop">ya lo decidiste el ${esc((p.decidido_en || "").slice(0, 10))}</span>`
          : ""}
        ${p.cambio_el_conflicto
          ? `<span class="pil e-ambar">apareció una opción nueva · vuelve a decidir</span>`
          : ""}
      </header>
      ${p.motivo ? `<p class="nota">${esc(p.motivo)}</p>` : ""}
      ${p.nota ? `<p class="nota nota-alerta">${esc(p.nota)}</p>` : ""}
      <div class="comparacion">
        <div><span class="etq">En el APM</span>
             <span class="val">${esc(p.valor_actual) || "<i>vacío</i>"}</span></div>
        ${p.candidatos.map((c) => `<div><span class="etq">${esc(c.documento)}</span>
             <span class="val">${esc(c.valor)}</span>
             <span class="evidencia">${esc(c.evidencia)}</span></div>`).join("")}
      </div>
      ${p.estado === "bloqueado" ? `<p class="nota">Esta columna no se toca. El valor
         que traen los documentos se muestra solo para que lo veas.</p>`
       : `<div class="decidir">
            <label for="dec-${i}">Qué se escribe</label>
            <select id="dec-${i}" data-clave="${esc(p.clave)}">
              <option value="__nada__">— no cambiar nada —</option>
              ${opciones.map((o) => `<option value="${esc(o.v)}"${
                C.decisiones[p.clave] === o.v ? " selected" : ""}>${esc(o.t)}</option>`).join("")}
            </select>
            ${p.lookup.length ? `<span class="nota">Valores válidos del catálogo:
               ${p.lookup.map(esc).join(" · ")}</span>` : ""}
          </div>`}
    </article>`;
  }).join("");

  $("lista-apm").querySelectorAll("[data-clave]").forEach((el) =>
    el.addEventListener("change", () => {
      C.decisiones[el.dataset.clave] = el.value === "__nada__" ? "" : el.value;
      pintarPropuestas();
      revisarCompuerta();
    }));
  revisarCompuerta();
}

/* La compuerta. Cuenta cuantos campos que EXIGEN decision siguen sin una, y
   mientras haya uno, guardar esta apagado. */
function revisarCompuerta() {
  const faltan = C.propuestas.filter(
    (p) => p.exige_decision && C.decisiones[p.clave] === undefined);
  const btn = $("btn-guardar-apm");
  if (!btn) return;
  btn.disabled = faltan.length > 0;
  $("aviso-compuerta").textContent = faltan.length
    ? `Faltan ${faltan.length} por decidir: ${faltan.slice(0, 3).map((p) => p.etiqueta).join(", ")}`
      + (faltan.length > 3 ? "…" : "")
    : "Todo revisado. Se puede guardar.";
}

async function guardarAPM() {
  errC("");
  const btn = $("btn-guardar-apm");
  btn.disabled = true;
  try {
    const r = await pedir("/api/conciliar/guardar-apm", json({
      ruta_apm: $("ruta-apm").value.trim().replace(/^"|"$/g, ""),
      numero: C.aplicativo.numero,
      propuestas: C.propuestas,
      decisiones: C.decisiones,
    }));
    const ok = $("ok-apm");
    ok.innerHTML = r.sin_cambios
      ? "No quedó ningún cambio que escribir."
      : `Guardado en <b>${esc(r.nombre)}</b> — ${r.aplicados.length} celdas.
         El original quedó intacto. Carpeta de versiones nuevas del APM:
         <code>${esc((r.archivo || "").replace(/[\\/][^\\/]+$/, ""))}</code>
         · <a href="/api/descargar?ruta=${encodeURIComponent(r.archivo)}">Descargar</a>
         ${r.decisiones_recordadas ? `<br>Se recordaron ${r.decisiones_recordadas}
            decisiones: la próxima vez no te las vuelve a preguntar.` : ""}
         ${r.rechazados.length ? `<br><b>${r.rechazados.length} rechazados:</b> `
           + r.rechazados.map((x) => `${esc(x.etiqueta || x.clave)} (${esc(x.motivo)})`).join("; ") : ""}`;
    ok.hidden = false;
    verBase();
  } catch (e) {
    errC(e.message);
  } finally {
    revisarCompuerta();
  }
}

/* ---------- la base ---------- */

$("btn-sembrar").addEventListener("click", async () => {
  errC("");
  const btn = $("btn-sembrar");
  btn.disabled = true;
  try {
    const r = await pedir("/api/almacen/sembrar", json({
      ruta_apm: $("ruta-apm").value.trim().replace(/^"|"$/g, ""),
      carpeta_tdd: $("carpeta-tdd").value.trim().replace(/^"|"$/g, ""),
    }));
    $("resumen-base").innerHTML = `
      <div class="aviso-caja">
        <b>Línea base guardada.</b>
        <p>${r.apm.aplicativos} aplicativos y ${r.apm.campos} campos del APM,
           más ${r.tdd.length} TDD. Contra esto se compara lo que llegue.</p>
        ${r.tdd_sin_amarrar.length ? `<p class="nota-alerta">
          <b>${r.tdd_sin_amarrar.length} TDD no se amarraron a ningún aplicativo:</b>
          ${r.tdd_sin_amarrar.map(esc).join(", ")}. No declaran su APM #
          y su nombre no coincide con nada del inventario.</p>` : ""}
      </div>`;
    $("resumen-base").hidden = false;
    verBase();
    // El asistente de 6 pasos liga cada escaneo al APM ya sembrado sin que
    // el usuario tenga que copiar ninguna ruta; al sembrar una base nueva
    // aqui, se le avisa para que lo detecte de inmediato.
    if (window.detectarApmAutomatico) window.detectarApmAutomatico();
  } catch (e) {
    errC(e.message);
  } finally {
    btn.disabled = false;
  }
});

async function verBase() {
  try {
    const r = await pedir("/api/almacen/resumen");
    const b = r.resumen;
    const conTdd = r.cobertura.filter((c) => c.tdds > 0).length;
    const conDocs = r.cobertura.filter((c) => c.docs > 0).length;
    $("estado-base").innerHTML = `
      <div class="resumen">
        <div class="dato"><b>${b.aplicativos}</b><span>aplicativos en base</span></div>
        <div class="dato"><b>${b.campos_base}</b><span>campos de línea base</span></div>
        <div class="dato"><b>${b.tdd}</b><span>TDD guardados</span></div>
        <div class="dato"><b>${b.documentos}</b><span>documentos leídos</span></div>
        <div class="dato"><b>${b.decisiones}</b><span>decisiones tuyas</span></div>
        <div class="dato"><b>${b.kb} KB</b><span>tamaño</span></div>
      </div>
      ${b.aplicativos ? `<p class="nota">${conTdd} aplicativos tienen TDD y
        ${conDocs} tienen documentos leídos. La base vive en
        <code>${esc(b.archivo)}</code>.</p>` : `<p class="nota">La base está vacía.
        Abre el libro y dale a <b>Sembrar</b>.</p>`}
      ${b.referencia_apm ? `<p class="nota nota-referencia">
        <b>Referencia interna del APM</b> — creada el
        ${_fechaLegible(b.referencia_apm.creado_en)}, actualizada por
        última vez el ${_fechaLegible(b.referencia_apm.actualizado_en)}.
        </p>` : ""}`;
  } catch { /* la base es opcional: si falla, la pantalla sigue sirviendo */ }
}

$("btn-ver-base").addEventListener("click", verBase);

$("btn-reporte-base").addEventListener("click", async () => {
  errC("");
  const btn = $("btn-reporte-base");
  btn.disabled = true;
  try {
    const r = await pedir("/api/almacen/reporte", json({}));
    const filas = r.cobertura.map((c) => `
      <tr><td>#${esc(c.numero)}</td><td>${esc(c.nombre)}</td>
          <td>${c.llenos}/${c.total}</td>
          <td>${c.tdds}</td><td>${c.docs}</td><td>${c.decisiones}</td></tr>`).join("");
    $("reporte-base").innerHTML = `
      <div class="tabla-envoltura"><table class="tabla">
        <thead><tr><th>#</th><th>Aplicativo</th><th>APM lleno</th>
          <th>TDD</th><th>Documentos</th><th>Decisiones</th></tr></thead>
        <tbody>${filas}</tbody></table></div>
      ${r.archivo ? `<p class="nota">Guardado en <code>${esc(r.archivo)}</code>
        · <a href="/api/descargar?ruta=${encodeURIComponent(r.archivo)}">Descargar el .md</a></p>` : ""}`;
    $("reporte-base").hidden = false;
  } catch (e) {
    errC(e.message);
  } finally {
    btn.disabled = false;
  }
});

$("btn-exportar-base").addEventListener("click", async () => {
  errC("");
  const btn = $("btn-exportar-base");
  btn.disabled = true;
  try {
    const r = await pedir("/api/almacen/exportar", json({}));
    const total = Object.values(r.filas).reduce((a, b) => a + b, 0);
    $("ok-base").innerHTML = `Exportado a <code>${esc(r.carpeta)}</code> — `
      + `${total} registros en ${r.archivos.length} archivos `
      + `(un JSON con todo y un CSV por tabla).`;
    $("ok-base").hidden = false;
  } catch (e) {
    errC(e.message);
  } finally {
    btn.disabled = false;
  }
});

