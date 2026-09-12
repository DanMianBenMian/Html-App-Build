@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM  Html App Build - build single-file EXE (deps bundled inside)
REM  Just double-click this file.
REM
REM  IMPORTANT 1: this file is PURE ASCII on purpose.
REM  Chinese text in a .bat plus "chcp 65001" makes cmd's parser
REM  misread UTF-8 bytes and execute line fragments as commands.
REM  Keep this file ASCII-only.
REM
REM  IMPORTANT 2: every path passed to PyInstaller is ABSOLUTE
REM  (%~dp0...). Reason: --specpath moves the generated .spec into
REM  .build\, and PyInstaller resolves RELATIVE paths inside a spec
REM  relative to the SPEC's directory, not the current directory.
REM  A relative "assets\icon.png" was therefore looked up as
REM  ".build\assets\icon.png" and failed with:
REM    ERROR: Unable to find '...\.build\assets\icon.png'
REM ============================================================

set "APPNAME=Html App Build"
set "ROOT=%~dp0"
set "DEPS=%~dp0.deps"
set "CLEAN="
REM  For a clean full rebuild, change the line above to:  set "CLEAN=--clean"

echo ============================================================
echo   Html App Build  -  build single-file EXE
echo ============================================================
echo.

REM ---------------- 1/4  locate python ----------------
set "PY="
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions" (
  for /f "delims=" %%D in ('dir /b /ad /o-n "%USERPROFILE%\.workbuddy\binaries\python\versions" 2^>nul') do (
    if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\%%D\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\%%D\python.exe"
  )
)
if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
)
if not defined PY (
  echo [ERROR] Python not found.
  echo         Install Python 3.11+ and check "Add python.exe to PATH",
  echo         or edit this script and set PY to the full path of python.exe
  echo.
  pause
  exit /b 1
)
echo [1/4] Python : !PY!
set "PYTHONPATH=%DEPS%"

REM ---------------- 2/4  dependencies ----------------
"!PY!" -c "import PyQt6, PIL, PyInstaller" >nul 2>&1
if errorlevel 1 (
  echo [2/4] Installing PyQt6 / pillow / pyinstaller into .deps ...
  "!PY!" -m pip install --target "%DEPS%" PyQt6 pillow pyinstaller
  if errorlevel 1 (
    echo [ERROR] pip install failed. If the download stalls, retry with the mirror:
    echo         "!PY!" -m pip install --target "%DEPS%" -i https://pypi.tuna.tsinghua.edu.cn/simple PyQt6 pillow pyinstaller
    echo.
    pause
    exit /b 1
  )
) else (
  echo [2/4] Dependencies OK : %DEPS%
)

REM ---------------- 3/4  icon ----------------
if not exist "assets\icon.ico" (
  echo [3/4] Generating assets\icon.png / assets\icon.ico ...
  "!PY!" "tools\make_icon.py"
  if errorlevel 1 (
    echo [ERROR] icon generation failed.
    echo.
    pause
    exit /b 1
  )
) else (
  echo [3/4] Icon already exists - skip. Delete assets\icon.ico to redo it.
)

REM ---------------- 4/4  package ----------------
echo [4/4] Packaging now - takes about 1-3 minutes, do not close this window.
echo.
"!PY!" -m PyInstaller --noconfirm %CLEAN% --onefile --windowed --noupx ^
  --name "%APPNAME%" ^
  --icon "%ROOT%assets\icon.ico" ^
  --add-data "%ROOT%assets\icon.png;assets" ^
  --paths "%DEPS%" ^
  --distpath "%ROOT%dist" ^
  --workpath "%ROOT%.build\pyi" ^
  --specpath "%ROOT%.build" ^
  "%ROOT%main.py"

if errorlevel 1 (
  echo.
  echo ============================================================
  echo   [ERROR] build failed - send a screenshot of the output above
  echo ============================================================
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   DONE
echo   output : %ROOT%dist\%APPNAME%.exe
echo ============================================================
dir /b "dist\*.exe"
echo.
echo Note: this exe is unsigned. Windows Defender may flag it - that is
echo       normal for PyInstaller builds, just allow it. First launch is
echo       slow because onefile unpacks itself to a temp folder.
echo.
pause
