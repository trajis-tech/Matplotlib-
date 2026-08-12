@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM =============================================================================
REM  Offline PyInstaller packager for 離線繪圖工具 v5
REM  - Build toolchain: SYSTEM Python + SYSTEM PyInstaller (no pip by this bat)
REM  - Runtime package: full project tree including portable_python
REM  - Place this bat (and launcher.py) in the project root when packaging.
REM  - While developing under ..\exe\, the sibling project folder is auto-detected.
REM =============================================================================

cd /d "%~dp0"
set "SCRIPT_DIR=%CD%"

echo.
echo === Offline portable EXE build ===
echo Script dir : %SCRIPT_DIR%
echo.

REM ----- Resolve project root -----
set "PROJ="
if exist "%SCRIPT_DIR%\app\backend\server.py" (
  set "PROJ=%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%\..\離線繪圖工具 v5.0\app\backend\server.py" (
  pushd "%SCRIPT_DIR%\..\離線繪圖工具 v5.0" >nul
  set "PROJ=!CD!"
  popd >nul
)

if not defined PROJ (
  echo ERROR: Cannot find project root ^(app\backend\server.py^).
  echo Put this bat inside the project folder, or keep it next to "離線繪圖工具 v5.0".
  goto :fail
)

if not exist "%SCRIPT_DIR%\launcher.py" (
  echo ERROR: launcher.py missing next to this bat: %SCRIPT_DIR%\launcher.py
  goto :fail
)

echo Project    : %PROJ%

REM ----- Output / work dirs (outside project tree when bat lives in ..\exe) -----
if /i "%PROJ%"=="%SCRIPT_DIR%" (
  set "OUT_ROOT=%PROJ%\dist_portable_exe"
  set "WORK_ROOT=%PROJ%\_pyi_work"
) else (
  set "OUT_ROOT=%SCRIPT_DIR%\dist_portable_exe"
  set "WORK_ROOT=%SCRIPT_DIR%\_pyi_work"
)

set "STAGE=%OUT_ROOT%\PortablePlotTool"
set "PYI_DIST=%WORK_ROOT%\dist"
set "PYI_BUILD=%WORK_ROOT%\build"
set "PYI_SPEC=%WORK_ROOT%"

echo Stage      : %STAGE%
echo Work       : %WORK_ROOT%
echo.

REM ----- Build toolchain: SYSTEM Python + SYSTEM PyInstaller only -----
REM (Do not install into / use project's portable_python for packaging.)
set "PY_EXE="

REM Prefer Windows py launcher real install (skip Store stub when possible)
where py >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined PY_EXE set "PY_EXE=%%P"
  )
)

if not defined PY_EXE (
  where python >nul 2>nul
  if not errorlevel 1 for /f "delims=" %%P in ('where python') do (
    echo %%P | findstr /i "WindowsApps" >nul
    if errorlevel 1 if not defined PY_EXE set "PY_EXE=%%P"
  )
)

if not defined PY_EXE (
  where python >nul 2>nul
  if not errorlevel 1 for /f "delims=" %%P in ('where python') do (
    if not defined PY_EXE set "PY_EXE=%%P"
  )
)

if not defined PY_EXE (
  echo ERROR: System Python not found in PATH.
  echo Install Python on the system and ensure "python" or "py" works, then re-run.
  goto :fail
)

REM Refuse to use project portable_python as the build interpreter
echo %PY_EXE% | findstr /i "portable_python" >nul
if not errorlevel 1 (
  echo ERROR: Resolved Python is portable_python — packaging must use SYSTEM Python.
  echo Fix PATH / py launcher so system python comes first.
  goto :fail
)

echo Build Python: %PY_EXE%
"%PY_EXE%" -c "import sys; print('  version   :', sys.version)" || goto :fail

"%PY_EXE%" -c "import PyInstaller; print('  PyInstaller:', PyInstaller.__version__)" 1>nul 2>nul
if errorlevel 1 (
  echo ERROR: PyInstaller not found in SYSTEM Python.
  echo Install it on the system yourself ^(e.g. pip install pyinstaller^), then re-run.
  echo This bat will not install packages into portable_python.
  goto :fail
)
"%PY_EXE%" -c "import PyInstaller; print('  PyInstaller:', PyInstaller.__version__)"

REM ----- Clean previous stage/work -----
echo.
echo [1/4] Preparing folders...
if exist "%STAGE%" rd /s /q "%STAGE%"
if exist "%WORK_ROOT%" rd /s /q "%WORK_ROOT%"
mkdir "%STAGE%" 2>nul
mkdir "%WORK_ROOT%" 2>nul
mkdir "%PYI_DIST%" 2>nul
mkdir "%PYI_BUILD%" 2>nul

REM ----- Stage full project (exclude junk / docs / superseded bats) -----
echo [2/4] Copying project into stage ^(exclusions applied^)...
robocopy "%PROJ%" "%STAGE%" /E /NFL /NDL /NJH /NJS /nc /ns /np ^
  /XD ".git" ".hg" ".svn" ".idea" ".vscode" ".cursor" ^
      "__pycache__" ".pytest_cache" ".mypy_cache" ".ruff_cache" ".cache" "cache" ^
      "tests" "test" "Test" ^
      "build" "vendor" ^
      "temp" "output" "workspace" ^
      "dist" "dist_portable_exe" "_pyi_work" "_pyi_dist" ^
      "node_modules" ".tox" "htmlcov" "coverage" ^
  /XF "點此開始.bat" ^
      "build_portable_exe.bat" "launcher.py" ^
      "*.md" "*.MD" ^
      ".gitignore" ".gitattributes" ".editorconfig" ^
      "Thumbs.db" "desktop.ini" ^
  >nul

set "RC=!ERRORLEVEL!"
if !RC! GEQ 8 (
  echo ERROR: robocopy failed with code !RC!
  goto :fail
)

REM Recreate empty runtime dirs expected by the app
mkdir "%STAGE%\output" 2>nul
mkdir "%STAGE%\temp" 2>nul
mkdir "%STAGE%\workspace" 2>nul
mkdir "%STAGE%\workspace\uploads" 2>nul

REM Drop leftover root docs / setup bats that robocopy might still copy by name patterns
for %%F in (
  "README.txt" "README_DECISION.txt" "CHANGELOG.txt" "LICENSE.txt"
) do if exist "%STAGE%\%%~F" del /f /q "%STAGE%\%%~F" >nul 2>nul

if exist "%STAGE%\build" rd /s /q "%STAGE%\build" >nul 2>nul
if exist "%STAGE%\vendor" rd /s /q "%STAGE%\vendor" >nul 2>nul
if exist "%STAGE%\tests" rd /s /q "%STAGE%\tests" >nul 2>nul

if not exist "%STAGE%\app\backend\server.py" (
  echo ERROR: Staging incomplete — server.py missing.
  goto :fail
)
if not exist "%STAGE%\portable_python\python.exe" (
  echo WARNING: portable_python\python.exe not in stage.
  echo          Build will continue; launcher will need frozen deps to work.
)

REM Copy launcher into work dir for PyInstaller
copy /y "%SCRIPT_DIR%\launcher.py" "%WORK_ROOT%\launcher.py" >nul

REM ----- PyInstaller: thin onedir launcher -----
echo [3/4] Running PyInstaller ^(offline, onedir^)...
set "EXE_NAME=離線繪圖工具"

"%PY_EXE%" -m PyInstaller ^
  --noconfirm --clean --onedir --console ^
  --name "%EXE_NAME%" ^
  --distpath "%PYI_DIST%" ^
  --workpath "%PYI_BUILD%" ^
  --specpath "%PYI_SPEC%" ^
  "%WORK_ROOT%\launcher.py"

if errorlevel 1 (
  echo ERROR: PyInstaller failed.
  goto :fail
)

if not exist "%PYI_DIST%\%EXE_NAME%\%EXE_NAME%.exe" (
  echo ERROR: Expected exe not found: %PYI_DIST%\%EXE_NAME%\%EXE_NAME%.exe
  goto :fail
)

echo [4/4] Merging launcher into stage...
xcopy /e /y /q "%PYI_DIST%\%EXE_NAME%\*" "%STAGE%\" >nul
if errorlevel 1 (
  echo ERROR: Failed to copy PyInstaller output into stage.
  goto :fail
)

if not exist "%STAGE%\%EXE_NAME%.exe" (
  echo ERROR: Final exe missing in stage.
  goto :fail
)

REM Optional short starter next to exe (not the old project bat)
(
  echo @echo off
  echo cd /d "%%~dp0"
  echo start "" "%%~dp0%EXE_NAME%.exe"
) > "%STAGE%\啟動.bat"

echo.
echo === DONE ===
echo Package folder:
echo   %STAGE%
echo.
echo Run:
echo   %STAGE%\%EXE_NAME%.exe
echo.
echo Notes:
echo   - Build toolchain: SYSTEM Python + SYSTEM PyInstaller ^(no pip install by this bat^).
echo   - Runtime package still includes portable_python for the shipped app.
echo   - Excluded: tests/build/cache/vendor, *.md, 點此開始.bat, git metadata, temp/output/workspace contents.
echo   - Included: app, portable_python, stats_kb, data, commands, configs, etc.
echo.
pause
exit /b 0

:fail
echo.
echo *** BUILD FAILED ***
pause
exit /b 1
