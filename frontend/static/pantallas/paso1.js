/* =========================================================================
   paso1.js -- "¿Qué quieres clasificar?"
   Modo archivo: arranca el trabajo de analisis en el servidor y entra al
   paso 2, donde se ve el avance real etapa por etapa (nunca salta directo
   al resultado). Modo carpeta: explora y pasa al paso 2 con la vista previa
   de archivos encontrados.
   ========================================================================= */

let archivoSubido = null;
let modo = Estado.get("modo", "archivo");

function fijarModo(m) {
  modo = m;
  Estado.set("modo", m);
  $("modo-archivo").classList.toggle("activo", m === "archivo");
  $("modo-carpeta").classList.toggle("activo", m === "carpeta");
  $("ruta-label").textContent = m === "carpeta"
    ? "Ruta de la carpeta" : "Ruta del documento";
  $("ruta").placeholder = m === "carpeta"
    ? "C:\\Users\\...\\HI entregables" : "C:\\Users\\...\\documento.docx";
  $("ruta-nota").innerHTML = m === "carpeta"
    ? "Pega la ruta de la carpeta. En el Explorador: clic derecho sobre la carpeta → <em>Copiar como ruta</em>."
    : "Pega la ruta completa. En el Explorador: clic derecho sobre el archivo → <em>Copiar como ruta</em>.";
  $("check-recursivo").hidden = (m !== "carpeta");
  mostrarError(1, "");
}

$("modo-archivo").addEventListener("click", () => fijarModo("archivo"));
$("modo-carpeta").addEventListener("click", () => fijarModo("carpeta"));

$("input-archivo").addEventListener("change", (e) => {
  archivoSubido = e.target.files[0] || null;
  if (archivoSubido) $("ruta").value = "";
});
$("ruta").addEventListener("input", () => { archivoSubido = null; });
$("ruta").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btn-continuar-1").click();
});

/* Aviso breve tras guardar la configuración (lo deja escrito config.js antes
   de volver aquí). */
function _pintarAvisoInicio() {
  const texto = Estado.get("avisoInicio", "");
  if (!texto) return;
  Estado.borrar("avisoInicio");
  const caja = document.createElement("p");
  caja.id = "aviso-inicio";
  caja.className = "confirmacion";
  const p1 = $("paso-1");
  p1.insertBefore(caja, p1.children[1] || null);
  caja.textContent = texto;
  caja.hidden = false;
  setTimeout(() => { caja.hidden = true; }, 7000);
}

/* Igual que antes: este mismo boton, sin que la persona tenga que hacer
   nada mas, arranca el trabajo de analisis en el servidor y entra al paso 2
   -- ahi se ve el avance real (extraccion, deteccion determinista) y, en
   cuanto empieza a clasificar con IA, pasa solo al paso 3, donde se ve el
   resto (clasificacion con IA, validacion) hasta terminar y entrar al
   paso 4. Nunca se salta directo del paso 1 al 4. */
async function iniciarAnalisisYContinuar(rutaApm, forzar = false) {
  const btn = $("btn-continuar-1");
  btn.disabled = true;
  btn.textContent = "Analizando…";
  mostrarError(1, "");

  try {
    let r;
    if (archivoSubido) {
      const fd = new FormData();
      fd.append("file", archivoSubido);
      fd.append("ruta_apm", rutaApm || "");
      if (forzar) fd.append("forzar", "1");
      r = await pedir("/api/analizar-vivo/subir", { method: "POST", body: fd });
    } else {
      r = await pedir("/api/analizar-vivo",
        json({ ruta: Estado.get("ruta"), ruta_apm: rutaApm, forzar }));
    }
    Estado.set("vivoId", r.id);
    Estado.set("loteId", "");
    Estado.set("indice", 0);
    Estado.set("alcanzado", 2);
    location.href = "/paso/2";
  } catch (e) {
    mostrarError(1, e.message);
    btn.disabled = false;
    btn.textContent = "Continuar";
  }
}

$("btn-continuar-1").addEventListener("click", async () => {
  mostrarError(1, "");
  const ruta = $("ruta").value.trim().replace(/^"|"$/g, "");
  Estado.set("ruta", ruta);
  const recursivo = $("recursivo").checked;
  Estado.setBool("recursivo", recursivo);

  const rutaApmAuto = await detectarApmAutomatico();
  Estado.set("rutaApm", rutaApmAuto);

  if (modo === "archivo") {
    if (!ruta && !archivoSubido) {
      return mostrarError(1, "Escribe una ruta o elige un archivo.");
    }
    return iniciarAnalisisYContinuar(rutaApmAuto);
  }

  if (!ruta) return mostrarError(1, "Escribe la ruta de la carpeta.");

  const btn = $("btn-continuar-1");
  btn.disabled = true; btn.textContent = "Explorando…";
  try {
    const alcance = await pedir("/api/explorar", json({ ruta, recursivo }));
    await guardarSesion("alcance", alcance);
    Estado.set("alcanzado", 2);
    location.href = "/paso/2";
  } catch (e) {
    mostrarError(1, e.message);
  } finally {
    btn.disabled = false; btn.textContent = "Continuar";
  }
});

fijarModo(modo);
_pintarAvisoInicio();
