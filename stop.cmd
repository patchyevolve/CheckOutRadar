@echo off
REM ==============================================================================
REM Checkout Radar — Stop Script (Windows Command Prompt)
REM ==============================================================================
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python scripts\launcher.py --down
    goto :eof
)

echo [INFO] Stopping Checkout Radar containers...
docker compose down
echo [SUCCESS] Checkout Radar services stopped.
