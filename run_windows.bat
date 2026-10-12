@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Creating Python environment...
 py -3 -m venv .venv
 if errorlevel 1 goto error
)
echo Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo Starting Sepandar System Tavana Cloud...
echo Open http://127.0.0.1:5000 in your browser.
".venv\Scripts\python.exe" app.py
pause
goto end
:error
echo Could not start. Install Python 3.11+ and select Add Python to PATH.
pause
:end
