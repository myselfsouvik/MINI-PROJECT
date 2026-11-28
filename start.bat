@echo off
rem Start the Street Dog Monitoring dashboard (Windows). Double-click, or run:
rem     start.bat            dashboard + phone QR connection
rem     start.bat --demo     also play the backup demo video
rem     start.bat --source 1 also watch webcam / USB phone number 1
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo No .venv folder found. First-time setup:
    echo     python -m venv .venv
    echo     .venv\Scripts\activate
    echo     pip install -r requirements.txt
    pause
    exit /b 1
)
rem Builds the dashboard the first time and after a git pull changes it (needs Node.js).
python -m backend.build_frontend
python -m backend.server --open --phone %*
pause
