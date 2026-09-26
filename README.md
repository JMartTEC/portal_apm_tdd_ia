# Portal APM TEC

Clasificador de Activos de Conocimiento IA-Ready, para el Tecnológico de
Monterrey. Toma documentos (TDD, fichas de aplicación, diagramas) y los
clasifica con IA contra el inventario APM y la plantilla TDD, con revisión
humana en cada paso.

```
DOCUMENTOS -> EXTRACCION -> REGLAS -> IA -> VALIDACION -> REVISION HUMANA -> .md + .json
```

## Estructura

```
backend/    API en FastAPI: toda la lógica (parsers, reglas, IA, SQLite).
frontend/   La interfaz: static/ (HTML, CSS, JS) y templates/.
```

El backend sirve el frontend (no son dos servidores separados): al arrancar,
FastAPI monta `frontend/static` en `/static` y lee `frontend/templates` para
la página principal. Se separan en carpetas distintas solo para que el
código quede organizado como una aplicación con su backend, no porque corran
por separado.

Lo que **no** está en este repositorio, a propósito: los documentos TDD y
APM reales del Tec, y la base de datos (`backend/datos/`) con lo que ya se
haya escaneado. Son datos internos, no código — el `.gitignore` los excluye.
La aplicación crea esas carpetas sola la primera vez que corre.

## Arranque (Windows)

```bash
git clone https://github.com/Verxus99/Portal_APM_TEC.git
```

Entra a la carpeta y doble clic en **`INICIAR PORTAL APM TEC.bat`**. No hace
falta preparar nada antes: la primera vez crea su propio entorno virtual en
`backend/venv`, instala las dependencias solo y abre
<http://localhost:8500>. Requiere tener Python instalado (3.10 o superior);
si no lo tiene, el mismo `.bat` lo avisa con el link de descarga.

A mano:

```bash
cd Portal_APM_TEC/backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python -m uvicorn app.main:app --app-dir . --port 8500
```

## Configuración

Copia `backend/.env.example` como `backend/.env`. La app funciona sin API
key (modo local con Ollama); para el modo con Claude hace falta
`ANTHROPIC_API_KEY` (y `ANTHROPIC_WORKSPACE_ID` si el token está ligado a
una organización). También se puede configurar desde el botón
**Configuración API key** dentro de la propia app.

## Publicarlo en internet (Render, gratis)

El repo ya trae `render.yaml`, así que Render arranca el portal solo:

1. Entra a <https://render.com> y crea una cuenta con "Sign up with GitHub"
   (no pide tarjeta).
2. Dashboard → **New +** → **Blueprint**.
3. Elige el repositorio `Verxus99/Portal_APM_TEC` y dale **Apply**.
4. En unos minutos queda arriba en una URL tipo
   `https://portal-apm-tec.onrender.com`.

Dos cosas a tener en cuenta en el plan gratis de Render:

- **La base de datos no es permanente.** El disco se reinicia cada vez que
  el servicio se reinicia o se redeploya, así que lo que se escanee ahí no
  se conserva entre reinicios — sirve para que cualquiera vea y pruebe el
  portal, no como bodega de datos reales.
- **Sin llave de API por defecto**, a propósito: así cualquiera puede ver y
  navegar el portal sin que eso use tus créditos de Claude. Si más adelante
  quieres que la clasificación con IA funcione ahí, agrega
  `ANTHROPIC_API_KEY` en el dashboard de Render (Settings → Environment) —
  pero entonces cualquiera que use ese botón gastaría de tu cuenta.

## Subir cambios a GitHub

`CREAR Y SUBIR A GITHUB.bat` deja listo el repositorio y lo sube. Si no
existe todavía en GitHub, el script intenta crearlo con GitHub CLI (`gh`)
si lo tienes instalado; si no, te pide la URL de un repositorio vacío que
crees tú mismo en github.com/new.
