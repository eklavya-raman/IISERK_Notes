@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "WORKSPACE_DIR=%%~fI"

set "REMOTE_URL_DEFAULT=https://github.com/eklavya-raman/IISERK_Notes.git"
set "REMOTE_NAME_DEFAULT=origin"
set "TARGET_BRANCH_DEFAULT=main"
set "PUBLISH_BRANCH_DEFAULT=html-subtree"
set "HTML_DIR_DEFAULT=%WORKSPACE_DIR%\html"

set "REMOTE_URL=%~1"
if "%REMOTE_URL%"=="" set "REMOTE_URL=%REMOTE_URL_DEFAULT%"

set "REMOTE_NAME=%~2"
if "%REMOTE_NAME%"=="" set "REMOTE_NAME=%REMOTE_NAME_DEFAULT%"

set "TARGET_BRANCH=%~3"
if "%TARGET_BRANCH%"=="" set "TARGET_BRANCH=%TARGET_BRANCH_DEFAULT%"

set "PUBLISH_BRANCH=%~4"
if "%PUBLISH_BRANCH%"=="" set "PUBLISH_BRANCH=%PUBLISH_BRANCH_DEFAULT%"

set "HTML_DIR=%~5"
if "%HTML_DIR%"=="" set "HTML_DIR=%HTML_DIR_DEFAULT%"

where git >nul 2>&1
if errorlevel 1 (
  echo [error] git was not found in PATH.
  exit /b 1
)

if not exist "%HTML_DIR%" (
  echo [error] HTML directory not found: "%HTML_DIR%"
  exit /b 1
)

dir /b "%HTML_DIR%\*.html" >nul 2>&1
if errorlevel 1 (
  echo [error] No .html files found in "%HTML_DIR%".
  exit /b 1
)

pushd "%WORKSPACE_DIR%"

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [error] "%WORKSPACE_DIR%" is not a git repository.
  popd
  exit /b 1
)

set "PUBLISH_DIR=%WORKSPACE_DIR%\_publish_tmp_html"
if exist "%PUBLISH_DIR%" (
  git worktree remove "%PUBLISH_DIR%" --force >nul 2>&1
  rmdir /s /q "%PUBLISH_DIR%" >nul 2>&1
)

git remote get-url "%REMOTE_NAME%" >nul 2>&1
if errorlevel 1 (
  echo [info] Adding remote "%REMOTE_NAME%"...
  git remote add "%REMOTE_NAME%" "%REMOTE_URL%"
  if errorlevel 1 goto :fail_popd
) else (
  for /f "delims=" %%U in ('git remote get-url "%REMOTE_NAME%"') do set "CURRENT_REMOTE_URL=%%U"
  if /I not "!CURRENT_REMOTE_URL!"=="%REMOTE_URL%" (
    echo [info] Updating remote "%REMOTE_NAME%" URL...
    git remote set-url "%REMOTE_NAME%" "%REMOTE_URL%"
    if errorlevel 1 goto :fail_popd
  )
)

git show-ref --verify --quiet refs/heads/%PUBLISH_BRANCH%
if not errorlevel 1 (
  git branch -D "%PUBLISH_BRANCH%" >nul 2>&1
)

echo [info] Creating isolated publish worktree...
git worktree add --detach "%PUBLISH_DIR%"
if errorlevel 1 goto :fail_popd

pushd "%PUBLISH_DIR%"

git checkout --orphan "%PUBLISH_BRANCH%"
if errorlevel 1 goto :fail_worktree

git rm -rf . >nul 2>&1

copy /Y "%HTML_DIR%\*.html" . >nul
if exist "%HTML_DIR%\index_metadata.json" (
  copy /Y "%HTML_DIR%\index_metadata.json" . >nul
)

git add *.html >nul 2>&1
if exist ".\index_metadata.json" git add index_metadata.json >nul 2>&1

git commit -m "Publish HTML and metadata snapshot"
if errorlevel 1 goto :fail_worktree

echo [info] Pushing "%PUBLISH_BRANCH%" to "%REMOTE_NAME%/%TARGET_BRANCH%"...
git push -u "%REMOTE_NAME%" "%PUBLISH_BRANCH%:%TARGET_BRANCH%" --force
if errorlevel 1 goto :fail_worktree

popd
git worktree remove "%PUBLISH_DIR%" --force >nul 2>&1
rmdir /s /q "%PUBLISH_DIR%" >nul 2>&1
popd

echo [ok] Published HTML snapshot.
echo [ok] Remote: %REMOTE_NAME% -> %REMOTE_URL%
echo [ok] Branch: %TARGET_BRANCH%
echo [ok] Source: %HTML_DIR%
exit /b 0

:fail_worktree
set "ERR=%ERRORLEVEL%"
popd
git worktree remove "%PUBLISH_DIR%" --force >nul 2>&1
rmdir /s /q "%PUBLISH_DIR%" >nul 2>&1
popd
exit /b %ERR%

:fail_popd
set "ERR=%ERRORLEVEL%"
popd
exit /b %ERR%
