@echo off
where py >nul 2>nul
if errorlevel 1 (
  python "%~dp0launch.py" --stop %*
) else (
  py -3 "%~dp0launch.py" --stop %*
)
if errorlevel 1 pause
