@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
echo Dang chuan bi FoodTour. Lan dau co the can vai phut...
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m venv .venv
) else (
  py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
if errorlevel 1 goto failure
:dependencies
".venv\Scripts\python.exe" -c "from importlib.metadata import version; import sys; v=tuple(map(int,version('playwright').split('.')[:2])); sys.exit(0 if v[0]==1 and v>=(1,64) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Dang cai thanh phan trinh duyet...
  ".venv\Scripts\python.exe" -m pip install "playwright>=1.64,<2"
  if errorlevel 1 goto failure
)
".venv\Scripts\python.exe" -m foody_tool.launcher --check-browser >nul 2>&1
if errorlevel 1 (
  echo Dang tai trinh duyet Chromium...
  ".venv\Scripts\python.exe" -m playwright install chromium
  if errorlevel 1 goto failure
)
start "" ".venv\Scripts\pythonw.exe" -m foody_tool.launcher
exit /b 0
:failure
echo Khong the khoi dong. Kiem tra Python va ket noi Internet, roi mo lai.
pause
exit /b 1
