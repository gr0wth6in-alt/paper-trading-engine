@echo off
setlocal
cd /d "%~dp0"
title Paper Trading Engine

if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found. Follow the installation steps in README.md.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m paper_engine.configure
if errorlevel 1 (
    echo Could not load the local configuration. See the error above.
    pause
    exit /b 1
)

if not exist "frontend\dist\index.html" (
    echo Frontend build missing. Building the local terminal...
    call build-frontend.cmd
    if errorlevel 1 (
        echo Frontend build failed. See the error above.
        pause
        exit /b 1
    )
)

echo.
echo Trading terminal: http://127.0.0.1:8000
echo API documentation: http://127.0.0.1:8000/docs
echo Keep this window open while using the backend. Press Ctrl+C to stop.
echo This address works only on this computer, not on your VPS or phone.
echo.
".venv\Scripts\python.exe" -m paper_engine
set "SERVER_EXIT=%ERRORLEVEL%"
echo.
echo Backend stopped. Review any errors above before restarting.
pause
exit /b %SERVER_EXIT%