@echo off
rem ---------------------------------------------------------------------------
rem Official Windows launcher (Phase 10, P0-3).
rem ASCII-only on purpose: this file must survive any code page.
rem The real logic lives in start_dev.py -- this is only a wrapper that
rem (a) prefers the project venv interpreter and (b) keeps the window open
rem when startup fails, so the error message is actually readable.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
setlocal

set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
  set "PY=%VENV_PY%"
) else (
  set "PY=python"
)

"%PY%" "%~dp0start_dev.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo Startup failed with exit code %RC%.
  echo See the messages above; the window stays open so you can read them.
  pause
)

exit /b %RC%
