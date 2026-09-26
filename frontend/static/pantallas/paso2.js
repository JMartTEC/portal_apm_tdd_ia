/* =========================================================================
   paso2.js -- "Esto es lo que se va a procesar"
   Modo carpeta: la tabla de alcance de siempre (explorar, revisar la lista,
   Analizar -> arranca el lote y pasa al paso 3).
   Modo "un solo documento": el trabajo ya lo arranco paso1.js (ver
   /api/analizar-vivo en main.py); aqui solo se sigue el avance real de las
   primeras 2 etapas -- extraccion y deteccion determinista, SIN IA todavia
   -- con su propia barra y su pipeline. En cuanto la deteccion determinista
   termina bien, se pasa solo al paso 3, donde sigue la IA.
   ========================================================================= */

function pintarAlcance(a, proveedor) {
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

  const seg = proveedor === "ollama" ? 28 : 12;
  const total = a.n_aceptados * seg;
  $("aviso-tiempo").textContent = a.n_aceptados
    ? `Estimado: ~${Math.max(1, Math.round(total / 60))} min `
      + `(${seg}s por documento en ${proveedor === "ollama" ? "modo local" : "modo API"}). `
      + `Puedes cancelar a medias; lo ya procesado se conserva.`
    : "";
}

const vivoId = Estado.get("vivoId");
let _temporizadorVivo2 = null;

if (vivoId) {
  /* ---------- modo "un solo documento": avance en vivo, sin IA ---------- */
  $("alcance-carpeta").hidden = true;
  $("btn-continuar-2").hidden = true;
  $("progreso-vivo-2").hidden = false;
  $("texto-identificacion").hidden = false;
  $("texto-identificacion").textContent = "Verificando el documento…";
  progreso(0, "Preparando…");
  seguirAnalisisVivo();
} else {
  /* ---------- modo carpeta: de siempre ---------- */
  (async () => {
    const alcance = await cargarSesion("alcance");
    const catalogos = await cargarCatalogos();
    if (!alcance) {
      mostrarError(2, "No hay ninguna exploración de carpeta en curso. Vuelve a Inicio.");
      $("btn-continuar-2").disabled = true;
      return;
    }
    pintarAlcance(alcance, catalogos.proveedor);
  })();

  $("btn-continuar-2").addEventListener("click", async () => {
    mostrarError(2, "");
    const escribir = $("escribir").checked;
    Estado.setBool("escribir", escribir);
    const btn = $("btn-continuar-2");
    btn.disabled = true;
    try {
      const r = await pedir("/api/lote", json({
        ruta: Estado.get("ruta"), recursivo: Estado.getBool("recursivo", true),
        escribir, ruta_apm: Estado.get("rutaApm"),
      }));
      Estado.set("loteId", r.lote.id);
      Estado.set("alcanzado", 3);
      location.href = "/paso/3";
    } catch (e) {
      mostrarError(2, e.message);
    } finally {
      btn.disabled = false;
    }
  });
}

function seguirAnalisisVivo() {
  clearInterval(_temporizadorVivo2);
  _temporizadorVivo2 = setInterval(async () => {
    let a;
    try {
      a = await pedir(`/api/analizar-vivo/${vivoId}`);
    } catch (e) {
      clearInterval(_temporizadorVivo2);
      return mostrarError(2, e.message);
    }

    const et = a.etapas || {};

    if (et.identificacion) {
      if (et.identificacion.es_fuente) {
        $("texto-identificacion").hidden = true;
        $("envoltura-barra").hidden = false;
        $("progreso-texto").hidden = false;
        $("pipeline").hidden = false;
      } else {
        $("texto-identificacion").hidden = false;
        $("texto-identificacion").textContent =
          "Ya se reconoce este documento como parte del sistema…";
      }
    }

    pintarEtapas(et);
    const esFuente = et.identificacion && et.identificacion.es_fuente;
    const hechas = ORDEN_ETAPAS.filter((n) => et[n] && et[n].estado === "ok").length;
    if (a.estado === "corriendo" && esFuente) {
      const siguiente = ORDEN_ETAPAS.find((n) => !et[n]);
      let textoEtapa = "Analizando…";
      if (siguiente && (siguiente === "extraccion"
          || (et[ORDEN_ETAPAS[ORDEN_ETAPAS.indexOf(siguiente) - 1]] || {}).estado === "ok")) {
        fase(siguiente, "activa");
        textoEtapa = ETIQUETAS_ETAPA[siguiente] || textoEtapa;
      }
      progreso(Math.min(92, 10 + hechas * 22), textoEtapa);
    }

    if (a.estado === "error") {
      clearInterval(_temporizadorVivo2);
      const etapasErr = a.error && a.error.etapas;
      if (etapasErr) pintarEtapas(etapasErr);
      const mensaje = (a.error && typeof a.error.detail === "string")
        ? a.error.detail : "El análisis no se completó.";
      mostrarError(2, mensaje);
      return;
    }

    if (a.estado === "terminado") {
      clearInterval(_temporizadorVivo2);
      if (a.resultado && a.resultado.excluido) {
        await guardarExcluidoYContinuar(a.resultado);
      } else {
        // caso raro: el trabajo entero (incluida la IA) ya termino mientras
        // seguiamos en el paso 2 -- se guarda igual y se sigue al paso 4,
        // sin pasar por el paso 3 porque ya no hay nada que ver ahi.
        await guardarClasificadoYContinuar(a.resultado);
      }
      return;
    }

    // la deteccion determinista (reglas) termino bien: ya toca clasificar
    // con IA, y eso se ve en el paso 3.
    if (esFuente && et.reglas && et.reglas.estado === "ok") {
      clearInterval(_temporizadorVivo2);
      Estado.set("alcanzado", 3);
      location.href = "/paso/3";
    }
  }, 350);
}
