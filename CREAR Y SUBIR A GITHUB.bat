@echo off
setlocal EnableDelayedExpansion
title Crear y subir Portal APM TEC a GitHub
cd /d "%~dp0"
set "LOG=%~dp0_push.log"
echo ===== %DATE% %TIME% ===== > "%LOG%"

echo ==================================================
echo   Portal APM TEC -- crear repositorio y subir a GitHub
echo ==================================================
echo.

rem El gestor de credenciales de Git, por si esta maquina nunca lo activo
rem (mismo arreglo que ya se uso para el otro repositorio).
for /f "delims=" %%h in ('git config --global --get credential.helper 2^>nul') do set "HELPER=%%h"
if not defined HELPER (
  echo Activando el gestor de credenciales de Git...
  git config --global credential.helper manager
)

if not exist "%~dp0.git" (
  echo Inicializando el repositorio local...
  git init >> "%LOG%" 2>&1
  git branch -M main >> "%LOG%" 2>&1
)

rem Identidad SOLO para este repositorio -- no toca tu configuracion global.
git config user.name "JMartTEC" >> "%LOG%" 2>&1
git config user.email "juan.samperio@omnisysmx.com" >> "%LOG%" 2>&1

echo Preparando el commit...
git add -A >> "%LOG%" 2>&1
git commit -m "Portal APM TEC v3" >> "%LOG%" 2>&1

rem --- Repositorio destino (fijo para la v3). Si "origin" no existe o apunta
rem a otra URL, se corrige para que siempre suba a este repositorio. ---
set "REPO_URL=https://github.com/JMartTEC/portal_apm_tdd_ia.git"
set "URL_ACTUAL="
for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do set "URL_ACTUAL=%%u"
if not defined URL_ACTUAL (
  git remote remove origin >> "%LOG%" 2>&1
  git remote add origin "!REPO_URL!" >> "%LOG%" 2>&1
) else if /i not "!URL_ACTUAL!"=="!REPO_URL!" (
  git remote set-url origin "!REPO_URL!" >> "%LOG%" 2>&1
)
echo Repositorio: !REPO_URL!

:hacer_push
echo.
echo Subiendo. Si se abre una ventana de GitHub, inicia sesion ahi.
echo.
git push -u origin main >> "%LOG%" 2>&1
set "CODIGO=%ERRORLEVEL%"
echo --- codigo: %CODIGO% --- >> "%LOG%"

if "%CODIGO%"=="0" (
  echo ==================================================
  echo   LISTO. Ya esta en GitHub.
  for /f "delims=" %%u in ('git remote get-url origin 2^>nul') do echo   %%u
  echo ==================================================
) else (
  echo No se completo. Si el log dice "rejected" o "fetch first", el
  echo repositorio en GitHub ya tiene archivos: avisale a Claude antes de
  echo hacer cualquier otra cosa.
  echo.
  echo Log completo:
  echo --------------------------------------------------
  type "%LOG%"
  echo --------------------------------------------------
)
echo.
pause
