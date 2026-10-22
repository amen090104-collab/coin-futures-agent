@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
set "agent_action=update"
if "update"=="run" if "%~1"=="--check" set "agent_action=check"
if exist ".venv\Scripts\python.exe" goto venv
where py >nul 2>nul
if not errorlevel 1 goto py
python ".agent-updater\update_driver.py" %agent_action% --root "%~dp0."
goto finish
:venv
".venv\Scripts\python.exe" ".agent-updater\update_driver.py" %agent_action% --root "%~dp0."
goto finish
:py
py -3 ".agent-updater\update_driver.py" %agent_action% --root "%~dp0."
:finish
set "agent_exit=%errorlevel%"
if not "%AGENT_BATCH_NO_PAUSE%"=="1" pause
exit /b %agent_exit%
