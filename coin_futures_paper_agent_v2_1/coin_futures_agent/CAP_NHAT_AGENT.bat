@echo off
call "%~dp0WINDOWS_AGENT.bat" update
exit /b %errorlevel%
