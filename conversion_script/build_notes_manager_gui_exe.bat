@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "WORKSPACE_DIR=%%~fI"
set "VENV_PY=%WORKSPACE_DIR%\.venv\Scripts\python.exe"

if not exist "%WORKSPACE_DIR%\conversion_script\notes_manager_gui.py" (
  echo [error] Missing GUI launcher script: "%WORKSPACE_DIR%\conversion_script\notes_manager_gui.py"
  exit /b 1
)

if not exist "%WORKSPACE_DIR%\conversion_script\gui\index.html" (
  echo [error] Missing GUI HTML file: "%WORKSPACE_DIR%\conversion_script\gui\index.html"
  exit /b 1
)

if exist "%VENV_PY%" (
  set "PY_CMD=%VENV_PY%"
  set "PY_ARGS="
  goto :build
)

where py >nul 2>&1
if not errorlevel 1 goto :use_py

where python >nul 2>&1
if errorlevel 1 (
  echo [error] Python not found in PATH.
  exit /b 1
)
set "PY_CMD=python"
set "PY_ARGS="
goto :build

:use_py
set "PY_CMD=py"
set "PY_ARGS=-3"

:build
pushd "%WORKSPACE_DIR%"

"%PY_CMD%" %PY_ARGS% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo [error] PyInstaller is not installed.
  echo [hint] Install it with:
  echo        "%PY_CMD%" %PY_ARGS% -m pip install pyinstaller
  popd
  exit /b 1
)

"%PY_CMD%" %PY_ARGS% -m PyInstaller --onefile --windowed --name notes_manager_gui --add-data "conversion_script\gui;gui" conversion_script\notes_manager_gui.py
if errorlevel 1 (
  echo [error] GUI EXE build failed.
  popd
  exit /b 1
)

echo [ok] Built GUI EXE: "%WORKSPACE_DIR%\dist\notes_manager_gui.exe"
echo [info] Run it from workspace root or keep dist under this workspace.

popd
exit /b 0
