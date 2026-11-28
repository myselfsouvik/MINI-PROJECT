@echo off
rem Start the Street Dog Monitoring dashboard (Windows). Double-click, or run:
rem     start.bat            dashboard + phone QR connection
rem     start.bat --demo     also play the backup demo video
rem     start.bat --source 1 also watch webcam / USB phone number 1
rem The first run sets everything up by itself (needs internet once). Only Python is needed.
setlocal
cd /d "%~dp0"
title DogWatch

if exist .venv\Scripts\python.exe (
    set "PY=.venv\Scripts\python.exe"
    goto :setup
)

rem Find Python: the py launcher with a tested version first, then any "python" on the PATH.
set "PY="
for %%V in (3.11 3.12 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=py -3"
)
if defined PY goto :setup

echo Python is not installed on this computer. DogWatch needs Python 3.11.
where winget >nul 2>&1
if errorlevel 1 goto :nopython
choice /c YN /m "Install Python 3.11 now with winget (from python.org)"
if errorlevel 2 goto :nopython
winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :nopython
echo.
echo Python is installed. Close this window and double-click start.bat again.
pause
exit /b 0

:nopython
echo.
echo Install Python 3.11 from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer), then double-click start.bat again.
pause
exit /b 1

:setup
%PY% backend\setup_env.py
if errorlevel 1 (
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
rem The dashboard comes ready-built. This rebuilds it only if its code changed and Node.js is installed.
python -m backend.build_frontend
python -m backend.server --open --phone %*
pause
