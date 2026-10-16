@echo off
REM ==============================================================================
REM Checkout Radar — One-Command Startup Script (Windows Command Prompt)
REM ==============================================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"

REM 1. Prefer Python launcher if Python is installed
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python scripts\launcher.py %*
    goto :eof
)
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3 scripts\launcher.py %*
    goto :eof
)

REM 2. Fallback: Pure Batch File Startup
echo [INFO] Python not found in PATH; proceeding with Docker batch launcher...

REM Check Docker
where docker >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker is not installed or not found in PATH.
    echo Please install Docker Desktop for Windows: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

docker info >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker Desktop is not running.
    echo Please start Docker Desktop from the Start Menu and wait for the engine to initialize.
    pause
    exit /b 1
)

REM Prepare .env
if not exist .env (
    if exist .env.example (
        echo [INFO] No .env found. Cloning default from .env.example (Mock Mode enabled)...
        copy .env.example .env >nul
    )
)

echo [INFO] Building and starting Checkout Radar containers...
docker compose up --build -d
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Docker Compose failed to build or start containers.
    docker compose logs --tail 40
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo  CHECKOUT RADAR IS READY
echo ======================================================================
echo   * Auditor Dashboard:       http://localhost:8000
echo   * Demo Merchant Harness:   http://localhost:8001
echo   * Interactive API Docs:    http://localhost:8000/docs
echo ======================================================================
echo   To stop services: run stop.cmd or docker compose down
echo.

if not "%1"=="--no-browser" (
    start "" "http://localhost:8000"
)

endlocal
