@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "WORKSPACE_DIR=%%~fI"

if not exist "%WORKSPACE_DIR%\conversion_script\notes_converter_cli.py" (
  echo [error] Missing launcher script: "%WORKSPACE_DIR%\conversion_script\notes_converter_cli.py"
  exit /b 1
)

where py >nul 2>&1
if not errorlevel 1 goto :use_py

where python >nul 2>&1
if errorlevel 1 (
  echo [error] Python not found in PATH.
  exit /b 1
)
set "PY_CMD=python"
goto :build

:use_py
set "PY_CMD=py -3"

:build
pushd "%WORKSPACE_DIR%"

%PY_CMD% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo [error] PyInstaller is not installed.
  echo [hint] Install it with:
  echo        %PY_CMD% -m pip install pyinstaller
  popd
  exit /b 1
)

%PY_CMD% -m PyInstaller --onefile --name notes_converter conversion_script\notes_converter_cli.py
if errorlevel 1 (
  echo [error] EXE build failed.
  popd
  exit /b 1
)

echo [ok] Built EXE: "%WORKSPACE_DIR%\dist\notes_converter.exe"
echo [info] Run it from workspace root or keep dist under this workspace.

popd
exit /b 0
