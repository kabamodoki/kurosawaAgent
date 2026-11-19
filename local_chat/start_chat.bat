@echo off
rem ==================================================================
rem  Kurosawa Quest chat UI (Streamlit)  ->  http://127.0.0.1:8501
rem  The first run creates .venv and installs requirements.txt.
rem ==================================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creating a Python virtual environment ^(.venv^) ...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo [error] Could not create .venv. Install Python 3.10 or later and try again.
    pause
    exit /b 1
  )
  echo [setup] Installing packages ...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo [error] pip install failed.
    pause
    exit /b 1
  )
)

echo Starting the chat UI. Close this window or press Ctrl+C to stop.
".venv\Scripts\python.exe" -m streamlit run chat_app.py --server.address 127.0.0.1 --server.port 8501
pause
