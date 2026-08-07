@echo off
echo.
echo  ============================================
echo   J.A.R.V.I.S. Setup
echo  ============================================
echo.

if not exist config mkdir config

:: Create config\.env if it doesn't exist
if not exist config\.env (
    copy config\.env.example config\.env
    echo  [1/4] Created config\.env file - PASTE YOUR GROK API KEY IN IT
    echo.
    notepad config\.env
) else (
    echo  [1/4] config\.env already exists
)

:: Create Python virtual environment
echo  [2/4] Creating Python virtual environment...
python -m venv venv
if errorlevel 1 (
    echo  ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

:: Install Python dependencies
echo  [3/4] Installing Python dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo  Python dependencies installed.

:: Install frontend dependencies
echo  [4/4] Installing frontend dependencies...
cd frontend
call npm install --silent
cd ..

echo.
echo  ============================================
echo   Setup complete!
echo
echo   Now run: start_jarvis.bat
echo  ============================================
echo.
pause
