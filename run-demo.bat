@echo off
rem Try the product on a simulated network (Windows). Needs Python 3.11+ and Git for Windows.
rem   run-demo.bat            start (or carry on where you left off)
rem   run-demo.bat --reset    start again from a fresh demo network
rem Then open http://127.0.0.1:8710 and sign in as demo / demo-password. Ctrl+C stops it.
setlocal
cd /d "%~dp0backend"
where git >nul 2>nul || (echo Install Git for Windows first: config backups are kept in a git repository. & pause & exit /b 1)
set "PY=py -3"
%PY% --version >nul 2>nul || set "PY=python"
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" || (echo Python 3.11 or newer is needed: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo First run: setting up, a minute or two...
  %PY% -m venv .venv || (pause & exit /b 1)
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements-dev.txt || (pause & exit /b 1)
.venv\Scripts\python.exe -m app.demo %*
pause
