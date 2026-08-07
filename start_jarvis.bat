@echo off
set "APP_URL=http://localhost:5173"

:: If "focus" arg passed, just open the window (skip restart)
if /i "%1"=="focus" (
    curl -s http://localhost:8000/health >nul 2>&1
    if not errorlevel 1 (
        call :open_jarvis
        exit /b
    )
)

:: Kill anything still on ports 8000 and 5173 (only JARVIS's own ports —
:: never kill all python processes, that nukes unrelated work)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5173 " ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1

if not exist "%~dp0logs" mkdir "%~dp0logs"

:: Start backend (server.py) hidden
powershell -NonInteractive -WindowStyle Hidden -Command ^
  "$b='%~dp0';" ^
  "$server = if (Test-Path ($b+'backend\server.py')) { $b+'backend\server.py' } else { $b+'server.py' };" ^
  "$hotkey = if (Test-Path ($b+'backend\hotkey.py')) { $b+'backend\hotkey.py' } else { $b+'hotkey.py' };" ^
  "Start-Process ($b+'venv\Scripts\python.exe') -ArgumentList '-u','-X','utf8',$server -WindowStyle Hidden -WorkingDirectory $b -RedirectStandardOutput ($b+'logs\server.log') -RedirectStandardError ($b+'logs\server_err.log');" ^
  "Start-Process ($b+'venv\Scripts\pythonw.exe') -ArgumentList $hotkey -WindowStyle Hidden -WorkingDirectory $b"

:: Start frontend (npm run dev) hidden
powershell -NonInteractive -WindowStyle Hidden -Command ^
  "$b='%~dp0frontend';" ^
  "Start-Process 'cmd' -ArgumentList '/c npm run dev > \"%~dp0logs\frontend.log\" 2>&1' -WindowStyle Hidden -WorkingDirectory $b"

:: Wait for backend on port 8000 (max 60s, then bail with a hint)
set /a _tries=0
:wb
timeout /t 1 /nobreak >nul
curl -s http://localhost:8000/health >nul 2>&1
if not errorlevel 1 goto wf_start
set /a _tries+=1
if %_tries% geq 60 (
    echo Backend did not start in 60s - check logs\server_err.log
    exit /b 1
)
goto wb

:: Wait for frontend on port 5173 (max 60s)
:wf_start
set /a _tries=0
:wf
timeout /t 1 /nobreak >nul
curl -s http://localhost:5173 >nul 2>&1
if not errorlevel 1 goto open
set /a _tries+=1
if %_tries% geq 60 (
    echo Frontend did not start in 60s - check logs\frontend.log
    exit /b 1
)
goto wf
:open

:: Open as standalone app window
call :open_jarvis
exit /b

:open_jarvis
powershell -NonInteractive -WindowStyle Hidden -Command ^
  "$url='%APP_URL%';" ^
  "$pf86=[Environment]::GetEnvironmentVariable('ProgramFiles(x86)');" ^
  "$chromePaths = @($env:ProgramFiles + '\Google\Chrome\Application\chrome.exe', $pf86 + '\Google\Chrome\Application\chrome.exe', $env:LocalAppData + '\Google\Chrome\Application\chrome.exe');" ^
  "$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1;" ^
  "if ($chrome) { Start-Process $chrome -ArgumentList \"--app=$url\" } else { Start-Process msedge -ArgumentList \"--app=$url\" }"
exit /b
