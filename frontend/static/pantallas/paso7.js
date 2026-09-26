/* =========================================================================
   paso7.js -- "Exportación de Vectorización"
   ========================================================================= */

let resultado = null;
let item = null;

async function refrescarPreview() {
  if (!item.markdown) {
    try {
      const r = await pedir("/api/exportar", json({
        activo: item.activo, texto: item.texto || "",
        ruta_origen: item.nombre, solo_vista: true,
      }));
      item.markdown = r.markdown;
      await guardarDocumentoActual(resultado, item);
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

function nombreDescarga() {
  if (item.base) return item.base;
  const limpio = String(item.nombre || "activo")
    .replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  return `${String(item.activo?.id || "activo").toLowerCase()}_${limpio || "activo"}`;
}

$("btn-md-descargar").addEventListener("click", async () => {
  await refrescarPreview();
  descargar(`${nombreDescarga()}.md`, item.markdown || "", "text/markdown");
});

$("btn-json-descargar").addEventListener("click", () => {
  descargar(`${nombreDescarga()}.json`, JSON.stringify(item.activo, null, 2), "application/json");
});

$("btn-md-copiar").addEventListener("click", async () => {
  await refrescarPreview();
  await navigator.clipboard.writeText(item.markdown || "");
  confirmar("Markdown copiado al portapapeles.");
});

$("btn-json-copiar").addEventListener("click", async () => {
  await navigator.clipboard.writeText(JSON.stringify(item.activo, null, 2));
  confirmar("JSON copiado al portapapeles.");
});

$("btn-guardar-disco").addEventListener("click", async () => {
  mostrarError(7, "");
  const carpeta = $("carpeta-destino").value.trim().replace(/^"|"$/g, "");
  if (!carpeta) return mostrarError(7, "Escribe la carpeta destino.");
  const btn = $("btn-guardar-disco");
  btn.disabled = true;
  try {
    const r = await pedir("/api/exportar", json({
      activo: item.activo, carpeta, texto: item.texto || "", ruta_origen: item.nombre,
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
  limpiarEstadoAsistente();
  location.href = "/";
});

(async () => {
  resultado = await cargarResultadoSesion();
  if (!resultado) {
    mostrarError(7, "No hay ningún documento listo para exportar. Vuelve a Inicio.");
    return;
  }
  item = await cargarDocumentoActual(resultado);
  if (!item) {
    mostrarError(7, "No hay ningún documento listo para exportar. Vuelve a Inicio.");
    return;
  }
  $("carpeta-destino").value = Estado.get("modo") === "carpeta"
    ? Estado.get("ruta") : (Estado.get("ruta").replace(/[\\/][^\\/]*$/, "") || Estado.get("ruta"));
  await refrescarPreview();
})();
