@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ===========================================================================================
rem  Robocode Tank Royale lab kit - installer for one Windows user. NO admin rights needed.
rem  Installs into %USERPROFILE%\Robocode:
rem    Java 21 runtime (Eclipse Temurin 21.0.13), Robocode Tank Royale GUI 1.4.0, the Python
rem    sample bots, a starter bot (MyBot) and a Start-Robocode launcher (+ a copy on the Desktop).
rem  Installs Python 3.13.17 for this user only (if missing) and the robocode-tank-royale 1.4.0
rem  package from the wheels\ folder (works offline). Safe to run again: keeps your bots.
rem ===========================================================================================
cd /d "%~dp0"
set "KIT=%~dp0"
set "RC=%USERPROFILE%\Robocode"
set "PYDIR=%LOCALAPPDATA%\Programs\Python\Python313"
set "PY=%PYDIR%\python.exe"
set "JRE_ZIP=downloads\OpenJDK21U-jre_x64_windows_hotspot_21.0.13_9.zip"
set "PY_EXE=downloads\python-3.13.17-amd64.exe"
set "GUI_JAR=robocode-tankroyale-gui-1.4.0.jar"
set "BOTS_ZIP=downloads\sample-bots-Python-1.4.0.zip"

echo.
echo  Robocode Tank Royale lab kit
echo  Installing for %USERNAME% into %RC%
echo.

rem ---------------------------------------------------------------- 1. kit files intact?
echo [1/6] Checking the kit files (SHA256)...
for /f "usebackq tokens=1,2" %%a in ("SHA256SUMS.txt") do (
  set "want=%%a" & set "file=%%b" & set "got="
  if not exist "!file!" ( echo   MISSING: !file! & goto :fail )
  for /f "skip=1 delims=" %%h in ('certutil -hashfile "!file!" SHA256 ^| findstr /v /c:"CertUtil"') do if not defined got set "got=%%h"
  set "got=!got: =!"
  if /i not "!got!"=="!want!" ( echo   DAMAGED: !file! - copy the kit again & goto :fail )
)
echo   OK

rem ---------------------------------------------------------------- 2. Python (this user only)
echo [2/6] Python 3.13...
if exist "%PY%" (
  echo   already installed: %PY%
) else (
  echo   installing for this user only - this takes a minute...
  "%PY_EXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0
  if not exist "%PY%" (
    echo   Python did not install. Run %PY_EXE% by hand: untick "Use admin privileges",
    echo   tick "Add python.exe to PATH", click Install Now. Then run this installer again.
    goto :fail
  )
  echo   OK
)

rem ---------------------------------------------------------------- 3. robocode-tank-royale (offline)
echo [3/6] Python package robocode-tank-royale 1.4.0 (from the kit, no internet needed)...
"%PY%" -m pip install -q --disable-pip-version-check --no-index --find-links "%KIT%wheels" robocode-tank-royale==1.4.0
if errorlevel 1 ( echo   pip install failed & goto :fail )
"%PY%" -c "import robocode_tank_royale, importlib.metadata as m; print('  OK, version', m.version('robocode-tank-royale'))"
if errorlevel 1 goto :fail

rem ---------------------------------------------------------------- 4. Java runtime
echo [4/6] Java 21 runtime...
if not exist "%RC%" mkdir "%RC%"
if exist "%RC%\jre\bin\javaw.exe" (
  echo   already there
) else (
  if exist "%RC%\jre-unpack" rmdir /s /q "%RC%\jre-unpack"
  mkdir "%RC%\jre-unpack"
  tar -xf "%JRE_ZIP%" -C "%RC%\jre-unpack"
  if errorlevel 1 ( echo   could not unpack the Java zip & goto :fail )
  for /d %%d in ("%RC%\jre-unpack\*") do move "%%d" "%RC%\jre" >nul
  rmdir /s /q "%RC%\jre-unpack"
  if not exist "%RC%\jre\bin\javaw.exe" ( echo   Java unpack failed & goto :fail )
  echo   OK
)

rem ---------------------------------------------------------------- 5. GUI + bots
echo [5/6] Robocode GUI, sample bots and the starter bot...
copy /y "downloads\%GUI_JAR%" "%RC%\%GUI_JAR%" >nul || goto :fail
if not exist "%RC%\bots" mkdir "%RC%\bots"
tar -xf "%BOTS_ZIP%" -C "%RC%\bots"
if errorlevel 1 ( echo   could not unpack the sample bots & goto :fail )
if exist "%RC%\bots\MyBot\MyBot.py" (
  echo   kept your existing MyBot
) else (
  xcopy /e /i /q /y "starter\MyBot" "%RC%\bots\MyBot" >nul || goto :fail
)
echo   OK

rem ---------------------------------------------------------------- 6. launcher
echo [6/6] Start-Robocode launcher...
> "%RC%\Start-Robocode.cmd" (
  echo @echo off
  echo rem Starts the Robocode GUI with the kit's Java and Python ^(the GUI starts bots with "python"^).
  echo set "PATH=%PYDIR%;%PYDIR%\Scripts;%%PATH%%"
  echo cd /d "%RC%"
  echo start "" "%RC%\jre\bin\javaw.exe" -jar "%RC%\%GUI_JAR%"
)
if exist "%USERPROFILE%\Desktop" copy /y "%RC%\Start-Robocode.cmd" "%USERPROFILE%\Desktop\Start Robocode.cmd" >nul
for /f "usebackq tokens=2,*" %%a in (`reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" /v Desktop 2^>nul ^| findstr /i Desktop`) do set "DESK=%%b"
if defined DESK call set "DESK=!DESK!"
if defined DESK if exist "!DESK!" copy /y "%RC%\Start-Robocode.cmd" "!DESK!\Start Robocode.cmd" >nul
echo   OK

echo.
echo  ==========================================================================
echo   Done. Start Robocode with "Start Robocode" on the Desktop
echo   (or %RC%\Start-Robocode.cmd).
echo.
echo   First time in the Robocode window:
echo     Config ^> Bot Root Directories ^> Add ^> %RC%\bots ^> OK
echo   Then: Battle ^> Start Battle ^> pick MyBot + a few sample bots ^> Boot ^> Start.
echo   If Windows asks about Java and the firewall: Cancel is fine.
echo  ==========================================================================
echo.
pause
exit /b 0

:fail
echo.
echo  INSTALL STOPPED. Nothing was removed; fix the problem above and run install.cmd again.
echo.
pause
exit /b 1
