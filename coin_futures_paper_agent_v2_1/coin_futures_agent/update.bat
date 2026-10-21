@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
title Trading Bot V5.0 - Update V2
if not exist ".v5-update\v5_update.py" goto missing
if exist ".venv\Scripts\python.exe" goto venv
where py >nul 2>nul
if not errorlevel 1 goto py
python ".v5-update\v5_update.py" update --from-package --root "%~dp0."
goto finish
:venv
".venv\Scripts\python.exe" ".v5-update\v5_update.py" update --from-package --root "%~dp0."
goto finish
:py
py -3 ".v5-update\v5_update.py" update --from-package --root "%~dp0."
goto finish
:missing
echo [V5] Can giai nen day du goi V5 da kiem chung vao folder Agent cu.
echo Khong pull main. Khong xoa DB, .env, reports hoac backups.
set "v5_exit=1"
goto end
:finish
set "v5_exit=%errorlevel%"
:end
if not "%AGENT_BATCH_NO_PAUSE%"=="1" pause
exit /b %v5_exit%
