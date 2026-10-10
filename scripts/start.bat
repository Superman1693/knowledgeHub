@echo off
REM ============================================================
REM  KnowledgeHub launcher (ASCII only on purpose)
REM  Chinese output is produced by scripts\run.py, not here.
REM  Reason: cmd.exe parses .bat with the OEM codepage (GBK on
REM  Chinese Windows), so UTF-8 Chinese inside .bat breaks parsing.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0.."

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0run.py"
    goto end
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0run.py"
    goto end
)

echo.
echo [ERROR] Python not found. Please install Python 3.11+ and add it to PATH.
echo.

:end
echo.
pause
