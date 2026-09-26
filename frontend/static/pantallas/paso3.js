/* =========================================================================
   paso3.js -- "Análisis - IA Ready"
   Modo carpeta / lote: el seguimiento de siempre -- barra de avance, tabla
   en vivo, y al terminar arma `resultado` para guardarlo en la sesión y
   dejar avanzar al paso 4.
   Modo "un solo documento": retoma el mismo trabajo que ya arranco
   paso1.js y que el paso 2 siguio hasta que termino la deteccion
   determinista -- aqui se ve el resto (clasificacion con IA, validacion),
   con la misma barra/pipeline (extraccion y reglas ya llegan marcadas como
   hechas) y el hallazgo del aplicativo en cuanto se liga. Al terminar,
   guarda el resultado y pasa al paso 4.
   ========================================================================= */

const loteId = Estado.get("loteId");
const vivoId = Estado.get("vivoId");
// declarados ANTES de usarse: las funciones de abajo se llaman aqui mismo,
// de forma sincrona, y una `let` en zona muerta temporal (fuera de orden)
// tira ReferenceError apenas se referencia dentro de la funcion llamada.
let temporizador = null;
let _temporizadorVivo3 = null;

if (vivoId) {
  /* ---------- modo "un solo documento": retoma el analisis en vivo ---------- */
  progreso(0, "Retomando…");
  seguirAnalisisVivo3();
} else if (!loteId) {
  mostrarError(3, "No hay ningún análisis en curso. Vuelve a Inicio.");
} else {
  /* ---------- modo carpeta: de siempre ---------- */
  $("envoltura-avance").hidden = false;
  $("btn-cancelar").hidden = false;
  $("btn-continuar-3").hidden = true;
  ["extraccion", "reglas", "modelo", "validacion"].forEach((f) => fase(f, "activa"));
  progreso(0, "Preparando…");
  seguirLote();
}

$("btn-cancelar").addEventListener("click", async () => {
  if (!loteId) return;
  try { await pedir(`/api/lote/${loteId}/cancelar`, { method: "POST" }); }
  catch (e) { mostrarError(3, e.message); }
});

async function seguirLote() {
  clearInterval(temporizador);
  temporizador = setInterval(async () => {
    let l;
    try {
      l = await pedir(`/api/lote/${loteId}`);
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
      await terminarLote();
    }
  }, 1500);
}

async function terminarLote() {
  const l = await pedir(`/api/lote/${loteId}?detalle=true`);
  const { activos, activosOmitidos } = construirActivosDeLote(l);

  const resultado = {
    modoLote: true, loteId,
    nombres: activos.map((a) => a.nombre),
    activos: [], activosOmitidos, indice: 0,
  };
  await guardarResultadoSesion(resultado);
  Estado.set("indice", 0);

  const hayAlgo = (activos.length + activosOmitidos.length) > 0;
  $("btn-continuar-3").hidden = !hayAlgo;
  if (!hayAlgo) return;

  $("btn-continuar-3").onclick = () => {
    Estado.set("alcanzado", 4);
    location.href = "/paso/4";
  };
}

async function seguirAnalisisVivo3() {
  clearInterval(_temporizadorVivo3);
  _temporizadorVivo3 = setInterval(async () => {
    let a;
    try {
      a = await pedir(`/api/analizar-vivo/${vivoId}`);
    } catch (e) {
      clearInterval(_temporizadorVivo3);
      return mostrarError(3, e.message);
    }

    const et = a.etapas || {};
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

    if (a.estado === "error") {
      clearInterval(_temporizadorVivo3);
      const etapasErr = a.error && a.error.etapas;
      if (etapasErr) pintarEtapas(etapasErr);
      const mensaje = (a.error && typeof a.error.detail === "string")
        ? a.error.detail : "El análisis no se completó.";
      mostrarError(3, mensaje);
      return;
    }

    if (a.estado === "terminado") {
      clearInterval(_temporizadorVivo3);
      progreso(100, "Listo");
      // Antes se pasaba al paso 4 apenas terminaba: el chip de "Aplicativo
      // identificado" (pintarHallazgoVivo, arriba) alcanzaba a dibujarse
      // pero no daba tiempo de verlo -- una pausa corta antes de seguir.
      await new Promise((r) => setTimeout(r, 1400));
      if (a.resultado && a.resultado.excluido) {
        // red de seguridad: no deberia pasar (paso 2 ya lo hubiera
        // detectado y mandado al paso 4 antes de llegar aqui).
        await guardarExcluidoYContinuar(a.resultado);
      } else {
        await guardarClasificadoYContinuar(a.resultado);
      }
    }
  }, 350);
}
