@echo off
title Species ID Tool - Setup and Launch
cd /d "%~dp0"

echo ============================================
echo   Species ID Tool - Launcher
echo ============================================
echo.

:: ---- Step 1: Check for Python ----
echo [1/3] Checking for Python...
python --version 2>nul
if %errorlevel% equ 0 (
    echo       Python found.
    goto :python_ok
)

:: Python not on PATH - check common install locations
for %%V in (313 312 311 314 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        echo       Python found at %LOCALAPPDATA%\Programs\Python\Python%%V
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python%%V;%LOCALAPPDATA%\Programs\Python\Python%%V\Scripts;%PATH%"
        python --version 2>nul
        if %errorlevel% equ 0 goto :python_ok
    )
)
for %%V in (313 312 311 314 310) do (
    if exist "C:\Python%%V\python.exe" (
        echo       Python found at C:\Python%%V
        set "PATH=C:\Python%%V;C:\Python%%V\Scripts;%PATH%"
        python --version 2>nul
        if %errorlevel% equ 0 goto :python_ok
    )
)

:: Not found anywhere - download and install
echo       Python not found. Downloading and installing...
echo.

set "INSTALLER=%TEMP%\python_installer.exe"
set "PY_URL=https://www.python.org/ftp/python/3.13.2/python-3.13.2-amd64.exe"

:: Download using PowerShell (built into every Windows 10/11)
echo       Downloading Python 3.13 installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%INSTALLER%' -UseBasicParsing } catch { exit 1 }"

if %errorlevel% neq 0 (
    :: Fallback: try curl (built into Windows 10 1803+)
    echo       PowerShell download failed, trying curl...
    curl -L -o "%INSTALLER%" "%PY_URL%" 2>nul
)

if not exist "%INSTALLER%" (
    echo.
    echo       [ERROR] Could not download Python installer.
    echo       Please check your internet connection, or install Python manually:
    echo         1. Open https://www.python.org/downloads/
    echo         2. Download Python 3.11 or newer
    echo         3. IMPORTANT: Tick "Add Python to PATH" during install
    echo         4. Re-run this script
    echo.
    pause
    exit /b 1
)

:: Try silent install first (no admin needed for per-user install)
echo       Installing Python - this may take a minute...
"%INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0

if %errorlevel% neq 0 (
    :: Silent install failed - open interactive installer with guidance
    echo       Silent install needs confirmation. Opening installer...
    echo.
    echo       =============================================
    echo        IMPORTANT: On the first screen, tick the
    echo        checkbox "Add Python to PATH" at the bottom,
    echo        then click "Install Now"
    echo       =============================================
    echo.
    "%INSTALLER%" PrependPath=1 Include_pip=1
)

del "%INSTALLER%" 2>nul

:: Refresh PATH from registry so the new install is visible
echo       Refreshing environment...
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USER_PATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%B"
set "PATH=%USER_PATH%;%SYS_PATH%"

:: Check default install locations if PATH refresh didn't work
python --version 2>nul
if %errorlevel% neq 0 (
    for %%V in (313 312 311 314) do (
        if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
            set "PATH=%LOCALAPPDATA%\Programs\Python\Python%%V;%LOCALAPPDATA%\Programs\Python\Python%%V\Scripts;%PATH%"
            goto :check_after_install
        )
    )
)
:check_after_install
python --version 2>nul
if %errorlevel% neq 0 (
    echo.
    echo       [ERROR] Python installed but cannot be found yet.
    echo       Please close this window, reopen it, and run again.
    echo       Windows needs a restart of the terminal to update PATH.
    echo.
    pause
    exit /b 1
)
echo       Python installed successfully.

:python_ok
echo.

:: ---- Step 2: Update pip and install dependencies ----
echo [2/3] Checking dependencies...

:: Update pip
python -m pip install --upgrade pip --quiet 2>nul

:: Smart install: hash requirements.txt via Python to skip if unchanged
set "HASH_FILE=.deps_hash"
set NEEDS_INSTALL=1

:: Get hash of requirements.txt using Python (avoids certutil parsing issues)
python -c "import hashlib,pathlib;print(hashlib.md5(pathlib.Path('requirements.txt').read_bytes()).hexdigest())" > "%TEMP%\req_hash.txt" 2>nul

if exist "%HASH_FILE%" (
    fc /b "%HASH_FILE%" "%TEMP%\req_hash.txt" >nul 2>nul
    if not errorlevel 1 (
        echo       All packages up to date.
        set NEEDS_INSTALL=0
    )
)

if %NEEDS_INSTALL% equ 1 (
    echo       Installing packages [first run takes a few minutes]...
    echo.
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo       [ERROR] Package install failed.
        echo       Check the errors above and your internet connection.
        echo.
        pause
        exit /b 1
    )
    copy /y "%TEMP%\req_hash.txt" "%HASH_FILE%" >nul 2>nul
    echo.
    echo       Packages installed OK.
)
echo.

:: ---- Step 3: Launch ----
echo [3/3] Starting Species ID Tool...
echo.
:: Prevent Python from creating __pycache__ and delete any existing ones
set PYTHONDONTWRITEBYTECODE=1
if exist "species_id\__pycache__" rmdir /s /q "species_id\__pycache__" 2>nul
if exist "__pycache__" rmdir /s /q "__pycache__" 2>nul
python -B main.py
set EXIT_CODE=%errorlevel%
echo.
echo ============================================
echo   Application closed (exit code: %EXIT_CODE%)
echo ============================================
echo.
if %EXIT_CODE% neq 0 (
    echo   Something went wrong. Checking crash log...
    echo.
    if exist crash_log.txt (
        echo --- crash_log.txt ---
        type crash_log.txt
        echo.
        echo --- end of crash log ---
    )
    if exist crash_error.txt (
        echo --- crash_error.txt ---
        type crash_error.txt
        echo.
        echo --- end of crash error ---
    )
    echo.
)
pause
