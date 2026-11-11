@echo off
setlocal
REM Rebuild the single-file library catalog.
REM Read-only on your book folder: nothing here moves, renames or deletes anything in it.
REM Usage: double click = offline rebuild (uses local Douban cache only)
REM        rebuild.bat online = also fetch missing Douban data from network

chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Locate Python on any machine. Override by setting PY_EXE before running.
if not defined PY_EXE (
  for /f "delims=" %%P in ('where py 2^>nul') do if not defined PY_EXE set "PY_EXE=%%P"
)
if not defined PY_EXE (
  for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY_EXE set "PY_EXE=%%P"
)
if not defined PY_EXE goto :nopy
echo Python: %PY_EXE%
echo.

set "FETCH_MODE=--offline"
if /i "%~1"=="online" set "FETCH_MODE=--online"

echo [1/4] Scanning book folder (read only) ...
"%PY_EXE%" scripts\scan_library.py || goto :fail1
echo [2/4] Applying Douban data (%FETCH_MODE%) ...
"%PY_EXE%" scripts\fetch_douban.py %FETCH_MODE% || goto :fail2
echo [3/4] Cleaning and merging ...
"%PY_EXE%" scripts\postprocess.py || goto :fail3
echo [4/4] Building single-file HTML ...
"%PY_EXE%" scripts\build_html.py || goto :fail4

if not exist "data\books.merged.json" goto :fail5
if not exist "data\douban_enriched.json" goto :fail5

echo.
echo DONE. Open the HTML file in Chrome or Edge.
echo Your notes and ratings follow moved files automatically.
echo.
pause
exit /b 0

:fail1
echo FAILED at step 1 (scan). Check config.local.json source_root.
pause
exit /b 1
:fail2
echo FAILED at step 2 (douban). Network may be blocked; try without "online".
pause
exit /b 2
:fail3
echo FAILED at step 3 (postprocess).
pause
exit /b 3
:fail4
echo FAILED at step 4 (build html).
pause
exit /b 4
:fail5
echo FAILED: expected output files are missing.
pause
exit /b 5
:nopy
echo Python not found. Install Python 3, or set PY_EXE to your python.exe path.
pause
exit /b 9
