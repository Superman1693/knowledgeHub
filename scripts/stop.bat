@echo off
REM ============================================================
REM  KnowledgeHub stopper (ASCII only on purpose)
REM  Chinese output is produced by scripts\stop.py, not here.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0.."

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0stop.py"
    goto end
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0stop.py"
    goto end
)

echo.
echo [ERROR] Python not found. Please install Python 3.11+ and add it to PATH.
echo.

:end
echo.
pause
