@echo off
setlocal
cd /d "%~dp0"
title HomeworkGrader  [port 1310]

rem  usage:
rem    start.bat            start the server only, do NOT open a browser
rem    start.bat 1311       use another port
rem    start.bat -o         also open a browser (opt in)
rem
rem  The browser is deliberately NOT opened by default: on this machine the
rem  system http handler is Internet Explorer, which cannot run this page at
rem  all. Anything that "just opens the page" lands in IE.
set "PORT=1310"
set "OPEN=0"
for %%A in (%*) do (
  if /i "%%~A"=="-o" (set "OPEN=1") else if /i "%%~A"=="-n" (set "OPEN=0") else (set "PORT=%%~A")
)

rem  ---- python ----
set "PY="
if exist "E:\Python\python.exe" set "PY=E:\Python\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY (
  echo.
  echo   [x] Python not found.
  echo       Install Python, or put python.exe on PATH, then run this file again.
  echo.
  pause
  exit /b 1
)

rem  ---- 依赖目录（跟弹 / VirtuCoach 的包装在 E:\Lib，有就带上）----
if exist "E:\Lib\site-packages" set "PYTHONPATH=E:\Lib\site-packages"

if "%OPEN%"=="1" call :findbrowser

rem  ---- already running? ----
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo   A server is already running on port %PORT%.
  echo   Open this in your browser:  http://localhost:%PORT%
  echo.
  if "%OPEN%"=="1" call :openpage
  timeout /t 5 /nobreak >nul 2>nul
  exit /b 0
)

echo.
echo   HomeworkGrader - 作业检查（demo）
echo.
echo   Server starting on port %PORT% ...
echo.
echo   Open this in your browser (type or paste it):
echo.
echo       http://localhost:%PORT%
echo.
echo   The browser is NOT opened automatically on purpose - this machine's
echo   default http handler is Internet Explorer, which cannot run this page.
echo   Use Edge or Chrome.
echo.
echo   The server runs in a separate window.
echo   Close that window to stop the service.
echo.

set "HOMEWORK_PORT=%PORT%"
rem  run the server in its own window so errors stay visible
start "HomeworkGrader - server  (close this window to stop)" cmd /k call "%PY%" -X utf8 "homework\server.py"
timeout /t 2 /nobreak >nul 2>nul

if "%OPEN%"=="1" call :openpage
exit /b 0

rem ---------------------------------------------------------------------------
rem  open the page - only with -o.
rem  NOTE: never use  start "" "http://..."  -- that goes through the system
rem  default handler, and on this machine that is Internet Explorer.
rem ---------------------------------------------------------------------------
:openpage
if not defined BROWSER (
  echo   [!] Edge / Chrome not found, so nothing was opened.
  echo       Internet Explorer will NOT work for this page.
  echo       Open this URL yourself:  http://localhost:%PORT%
  echo.
  exit /b 0
)
echo   Opening in: %BROWSER%
start "" "%BROWSER%" "http://localhost:%PORT%"
exit /b 0

:findbrowser
set "BROWSER="
for %%P in (
  "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
  "%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles%\Mozilla Firefox\firefox.exe"
  "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"
) do if not defined BROWSER if exist %%P set "BROWSER=%%~P"

rem  Edge installed as EdgeCore\<version>\msedge.exe: the standard launcher
rem  folder can be empty on this machine, so look there too.
if not defined BROWSER (
  for /f "delims=" %%V in ('dir /b /ad /o-n "%ProgramFiles(x86)%\Microsoft\EdgeCore" 2^>nul') do (
    if not defined BROWSER if exist "%ProgramFiles(x86)%\Microsoft\EdgeCore\%%V\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\EdgeCore\%%V\msedge.exe"
  )
)
rem  fallback: the Chromium that ships with playwright works as a normal browser
if not defined BROWSER (
  for /f "delims=" %%C in ('dir /b /ad /o-n "%LOCALAPPDATA%\ms-playwright" 2^>nul') do (
    if not defined BROWSER if exist "%LOCALAPPDATA%\ms-playwright\%%C\chrome-win64\chrome.exe" set "BROWSER=%LOCALAPPDATA%\ms-playwright\%%C\chrome-win64\chrome.exe"
  )
)
if not defined BROWSER (
  for /f "delims=" %%C in ('dir /b /ad /o-n "E:\Lib\ms-playwright" 2^>nul') do (
    if not defined BROWSER if exist "E:\Lib\ms-playwright\%%C\chrome-win64\chrome.exe" set "BROWSER=E:\Lib\ms-playwright\%%C\chrome-win64\chrome.exe"
  )
)
exit /b 0
