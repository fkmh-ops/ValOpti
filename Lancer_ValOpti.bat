@echo off
chcp 65001 >nul
title ValOpti
setlocal
set "ROOT=%~dp0"
set "BACK=%ROOT%backend"
set "FRONT=%ROOT%frontend"
set "PY=%BACK%\.venv\Scripts\python.exe"

echo ============================================
echo   ValOpti - The Draft Maker
echo ============================================
echo.

rem --- 1. Environnement Python (premiere fois seulement) ---
if not exist "%PY%" (
    echo [1/4] Creation de l'environnement Python...
    python -m venv "%BACK%\.venv" || goto :erreur_python
    "%PY%" -m pip install -q -r "%BACK%\requirements.txt" || goto :erreur
) else (
    echo [1/4] Environnement Python : OK
)

rem --- 2. Base nettoyee (premiere fois seulement, ~4 min) ---
if not exist "%ROOT%data\valopti.db" (
    echo [2/4] Construction de la base nettoyee, environ 4 minutes...
    pushd "%BACK%"
    "%PY%" -m etl.build_db || (popd & goto :erreur)
    "%PY%" -m etl.audit
    popd
) else (
    echo [2/4] Base de donnees : OK
)

rem --- 3. Interface web compilee (premiere fois seulement) ---
if not exist "%FRONT%\dist\index.html" (
    echo [3/4] Compilation de l'interface...
    where npm >nul 2>nul || goto :erreur_node
    pushd "%FRONT%"
    if not exist node_modules call npm install || (popd & goto :erreur)
    call npm run build || (popd & goto :erreur)
    popd
) else (
    echo [3/4] Interface : OK
)

rem --- 4. Lancement : le navigateur s'ouvre quand le serveur est pret ---
echo [4/4] Demarrage du serveur sur http://localhost:8000
echo.
echo   Laissez cette fenetre ouverte. Fermez-la pour arreter ValOpti.
echo.
start "" /min powershell -NoProfile -WindowStyle Hidden -Command ^
  "for($i=0;$i -lt 60;$i++){try{Invoke-WebRequest -UseBasicParsing http://localhost:8000/api/health | Out-Null; Start-Process 'http://localhost:8000'; break}catch{Start-Sleep 1}}"
"%PY%" -m uvicorn --app-dir "%BACK%" valopti.main:app --port 8000
goto :fin

:erreur_python
echo.
echo ERREUR : Python est introuvable. Installez Python 3.12+ depuis python.org
echo (cochez "Add python.exe to PATH") puis relancez ce fichier.
goto :fin

:erreur_node
echo.
echo ERREUR : Node.js est introuvable. Installez Node.js 20+ depuis nodejs.org
echo puis relancez ce fichier.
goto :fin

:erreur
echo.
echo ERREUR : une etape a echoue, voir les messages ci-dessus.

:fin
echo.
pause
