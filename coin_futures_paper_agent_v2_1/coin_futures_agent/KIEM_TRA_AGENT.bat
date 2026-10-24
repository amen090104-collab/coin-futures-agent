@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" diagnose_agent.py --root "." --output "AGENT_KIEM_TRA.json"
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 diagnose_agent.py --root "." --output "AGENT_KIEM_TRA.json"
  ) else (
    python diagnose_agent.py --root "." --output "AGENT_KIEM_TRA.json"
  )
)
echo.
echo Neu co loi, gui AGENT_KIEM_TRA.json. Khong gui .env hay agent.db.
pause
