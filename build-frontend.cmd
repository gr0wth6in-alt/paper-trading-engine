@echo off
setlocal
pushd "%~dp0frontend"
where node >nul 2>nul
if errorlevel 1 (
    echo Node.js 22 or newer is required to build the frontend.
    popd
    exit /b 1
)
if not exist "node_modules\.bin\vite.cmd" (
    if exist "package-lock.json" (
        call npm ci --no-audit --no-fund
    ) else (
        call npm install --no-audit --no-fund
    )
    if errorlevel 1 (
        popd
        exit /b 1
    )
)
call npm run build
set "BUILD_EXIT=%ERRORLEVEL%"
popd
exit /b %BUILD_EXIT%