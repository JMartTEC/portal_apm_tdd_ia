@echo off
title Portal APM TEC
cd /d "%~dp0"
set "LOG=%~dp0_arranque.log"
set "PUERTO=8500"
echo ===== %DATE% %TIME% ===== > "%LOG%"

rem Libera el puerto %PUERTO% si se quedo un servidor anterior corriendo --
rem de esta carpeta o de OTRA version del portal. Antes esto trataba de matar
rem el proceso viejo buscando "portal-apm-tec" (con guiones) en su linea de
rem comando, pero las carpetas de version se llaman "portal_apm_tdd_ia_vN"
rem (con guion bajo): el filtro nunca coincidia, el servidor viejo nunca se
rem detenia, y el navegador seguia viendo esa version vieja aunque se abriera
rem esta carpeta. Ahora se identifica por PUERTO, no por nombre de carpeta,
rem asi que siempre libera lo que sea que este ocupando el 8500.
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PUERTO% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 2 /nobreak >nul

rem El entorno virtual vive DENTRO de esta carpeta, en backend\venv. Punto.
set "PY=%~dp0backend\venv\Scripts\python.exe"
if not exist "%PY%" (
  where python >nul 2>&1
  if errorlevel 1 (
    echo ERROR: no se encontro Python instalado en este equipo. >> "%LOG%"
    echo ==================================================
    echo   ERROR: no se encontro Python instalado en este equipo.
    echo   Instala Python 3.10 o superior desde https://www.python.org/downloads/
    echo   ^(marca la casilla "Add python.exe to PATH" durante la instalacion^)
    echo   y vuelve a ejecutar este archivo.
    echo ==================================================
    pause
    exit /b 1
  )
  echo Creando el entorno virtual propio, un momento...
  echo Creando entorno virtual propio en backend\venv >> "%LOG%"
  python -m venv "%~dp0backend\venv" >> "%LOG%" 2>&1
)
echo Interprete: %PY% >> "%LOG%"

"%PY%" -c "import uvicorn,fastapi,docx,pypdf,pptx,openpyxl,anthropic" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Instalando dependencias, un momento...
  "%PY%" -m pip install --disable-pip-version-check --no-cache-dir --force-reinstall -q -r "%~dp0backend\requirements.txt" >> "%LOG%" 2>&1
  "%PY%" -c "import uvicorn,fastapi,docx,pypdf,pptx,openpyxl,anthropic" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo ==================================================
    echo   ERROR instalando dependencias. Revisa _arranque.log
    echo   Si el error menciona "path too long" o similar, activa
    echo   "Rutas largas" de Windows y vuelve a intentar -- pregunta
    echo   como hacerlo si hace falta.
    echo ==================================================
    pause
    exit /b 1
  )
)

if not exist "%~dp0backend\.env" copy "%~dp0backend\.env.example" "%~dp0backend\.env" >nul 2>&1

echo ==================================================
echo   Portal APM TEC
echo   Servidor:  http://localhost:%PUERTO%
echo   Las llaves se ponen en el boton Configuracion API key (arriba a la
echo   derecha). Cierra esta ventana para detenerlo.
echo ==================================================
echo.
start "" http://localhost:%PUERTO%
"%PY%" -m uvicorn app.main:app --app-dir "%~dp0backend" --host 127.0.0.1 --port %PUERTO% >> "%LOG%" 2>&1
echo.
echo El servidor se detuvo. Log: _arranque.log
pause
