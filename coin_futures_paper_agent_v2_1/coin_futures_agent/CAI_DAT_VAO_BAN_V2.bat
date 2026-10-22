@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0bootstrap_windows.py"
goto finish
:use_python
python "%~dp0bootstrap_windows.py"
:finish
pause
