@echo off
call "%~dp0WINDOWS_AGENT.bat" rollback
exit /b %errorlevel%
