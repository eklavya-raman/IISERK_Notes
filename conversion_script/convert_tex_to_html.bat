@echo off
setlocal EnableExtensions

if "%~1"=="" goto :usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%") do set "SCRIPT_DIR=%%~fI"
for %%I in ("%SCRIPT_DIR%..") do set "WORKSPACE_DIR=%%~fI"
set "DEFAULT_HTML_DIR=%WORKSPACE_DIR%\html"

set "CSS_FILE=%SCRIPT_DIR%pandoc_book_themes.css"
set "SWITCHER_FILE=%SCRIPT_DIR%pandoc_theme_switcher.html"
set "CONVERTER_FILE=%SCRIPT_DIR%temp_to_vanilla.py"
set "POSTPROCESS_FILE=%SCRIPT_DIR%postprocess_pandoc_html.py"
set "INDEXER_FILE=%SCRIPT_DIR%update_html_index.py"

if not exist "%CSS_FILE%" (
  echo [error] Missing CSS file: "%CSS_FILE%"
  exit /b 1
)

if not exist "%SWITCHER_FILE%" (
  echo [error] Missing theme switcher file: "%SWITCHER_FILE%"
  exit /b 1
)

if not exist "%CONVERTER_FILE%" (
  echo [error] Missing converter script: "%CONVERTER_FILE%"
  exit /b 1
)

if not exist "%POSTPROCESS_FILE%" (
  echo [error] Missing HTML postprocessor script: "%POSTPROCESS_FILE%"
  exit /b 1
)

if not exist "%INDEXER_FILE%" (
  echo [error] Missing HTML indexer script: "%INDEXER_FILE%"
  exit /b 1
)

where pandoc >nul 2>&1
if errorlevel 1 (
  echo [error] pandoc was not found in PATH.
  exit /b 1
)

for %%F in ("%~1") do set "INPUT_TEX=%%~fF"
if not exist "%INPUT_TEX%" (
  echo [error] Input file not found: "%~1"
  exit /b 1
)

set "CUSTOM_TITLE=%NOTES_CUSTOM_TITLE%"
set "NOTE_SECTION=%NOTES_SECTION%"

for %%F in ("%INPUT_TEX%") do set "INPUT_DIR=%%~dpF"
set "LOCAL_IMAGE_DIR=%INPUT_DIR%images"
set "GLOBAL_TEX_DIR=%WORKSPACE_DIR%\tex_files"
set "GLOBAL_IMAGE_DIR=%GLOBAL_TEX_DIR%\images"
set "PANDOC_RESOURCE_PATH=%INPUT_DIR%;%LOCAL_IMAGE_DIR%;%GLOBAL_TEX_DIR%;%GLOBAL_IMAGE_DIR%;%WORKSPACE_DIR%"

if /I not "%~x1"==".tex" (
  echo [error] Input must be a .tex file.
  exit /b 1
)

if "%~2"=="" (
  for %%F in ("%INPUT_TEX%") do set "OUTPUT_HTML=%DEFAULT_HTML_DIR%\%%~nF.html"
) else (
  for %%F in ("%~2") do set "OUTPUT_HTML=%%~fF"
)

for %%F in ("%OUTPUT_HTML%") do set "OUTPUT_DIR=%%~dpF"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%" >nul 2>&1
set "IMAGES_DIR=%OUTPUT_DIR%images_folder"
if not exist "%IMAGES_DIR%" mkdir "%IMAGES_DIR%" >nul 2>&1
set "IMAGE_PREFIX=images_folder"

set "CONVERTED_TEX=%TEMP%\%~n1_vanilla_%RANDOM%%RANDOM%.tex"
set "PANDOC_INPUT=%INPUT_TEX%"

echo [info] Input : "%INPUT_TEX%"
echo [info] Output: "%OUTPUT_HTML%"
echo [info] Preprocess: converting to pandoc-friendly vanilla LaTeX...
echo [info] Images: "%IMAGES_DIR%"

call :run_converter "%INPUT_TEX%" "%CONVERTED_TEX%"
if errorlevel 1 (
  echo [error] Pre-conversion step failed.
  exit /b 1
)

if not exist "%CONVERTED_TEX%" (
  echo [error] Pre-conversion did not produce output: "%CONVERTED_TEX%"
  exit /b 1
)

set "PANDOC_INPUT=%CONVERTED_TEX%"

pandoc "%PANDOC_INPUT%" ^
  -s ^
  --to=html5 ^
  --mathml ^
  --number-sections ^
  --toc ^
  --toc-depth=3 ^
  --resource-path="%PANDOC_RESOURCE_PATH%" ^
  --css="%CSS_FILE%" ^
  --include-after-body="%SWITCHER_FILE%" ^
  --embed-resources ^
  -o "%OUTPUT_HTML%"

if errorlevel 1 (
  echo [error] pandoc conversion failed.
  if exist "%CONVERTED_TEX%" del "%CONVERTED_TEX%" >nul 2>&1
  exit /b 1
)

echo [info] Postprocess: applying theorem list, counters, boxes, and tikz image insertion...
call :run_postprocess "%OUTPUT_HTML%"
if errorlevel 1 (
  echo [error] HTML postprocessing failed.
  if exist "%CONVERTED_TEX%" del "%CONVERTED_TEX%" >nul 2>&1
  exit /b 1
)

echo [info] Index: refreshing index.html and backlinks...
set "INDEX_HTML_DIR=%OUTPUT_DIR%"
if "%INDEX_HTML_DIR:~-1%"=="\" set "INDEX_HTML_DIR=%INDEX_HTML_DIR:~0,-1%"
call :run_indexer "%INDEX_HTML_DIR%" "%OUTPUT_HTML%" "%CUSTOM_TITLE%" "%NOTE_SECTION%"
if errorlevel 1 (
  echo [error] HTML index update failed.
  if exist "%CONVERTED_TEX%" del "%CONVERTED_TEX%" >nul 2>&1
  exit /b 1
)

if exist "%CONVERTED_TEX%" del "%CONVERTED_TEX%" >nul 2>&1

echo [ok] HTML generated with themed book style and switchable themes.
exit /b 0

:run_converter
setlocal
set "SRC=%~1"
set "DST=%~2"

where python >nul 2>&1
if not errorlevel 1 (
  python "%CONVERTER_FILE%" --input "%SRC%" --output "%DST%" --images-dir "%IMAGES_DIR%" --image-path-prefix "%IMAGE_PREFIX%" --force
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%CONVERTER_FILE%" --input "%SRC%" --output "%DST%" --images-dir "%IMAGES_DIR%" --image-path-prefix "%IMAGE_PREFIX%" --force
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

echo [error] Python was not found in PATH.
endlocal & exit /b 1

:run_postprocess
setlocal
set "HTML_FILE=%~1"

where python >nul 2>&1
if not errorlevel 1 (
  python "%POSTPROCESS_FILE%" --input "%HTML_FILE%"
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%POSTPROCESS_FILE%" --input "%HTML_FILE%"
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

echo [error] Python was not found in PATH.
endlocal & exit /b 1

:run_indexer
setlocal
set "HTML_DIR=%~1"
set "TARGET_HTML=%~2"
set "INDEX_TITLE=%~3"
set "INDEX_SECTION=%~4"

for %%F in ("%TARGET_HTML%") do set "TARGET_NAME=%%~nxF"
set "INDEX_ARGS=--html-dir "%HTML_DIR%" --target-file "%TARGET_NAME%""
if not "%INDEX_TITLE%"=="" set "INDEX_ARGS=%INDEX_ARGS% --title "%INDEX_TITLE%""
if not "%INDEX_SECTION%"=="" set "INDEX_ARGS=%INDEX_ARGS% --section "%INDEX_SECTION%""

where python >nul 2>&1
if not errorlevel 1 (
  python "%INDEXER_FILE%" %INDEX_ARGS%
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%INDEXER_FILE%" %INDEX_ARGS%
  set "RC=%ERRORLEVEL%"
  endlocal & exit /b %RC%
)

echo [error] Python was not found in PATH.
endlocal & exit /b 1

:usage
echo Usage:
echo   %~n0 input-file.tex [output-file.html]
echo   - If output-file.html is omitted, output goes to .\html\<input-name>.html
echo   - Optional metadata via env vars:
echo       set NOTES_CUSTOM_TITLE=Your Custom Title
echo       set NOTES_SECTION=course notes ^| assignments ^| personal study
echo.
echo Example:
echo   %~n0 tex_files\white\basic_algebra.tex
echo   %~n0 tex_files\white\basic_algebra.tex html\basic_algebra.html
exit /b 1
