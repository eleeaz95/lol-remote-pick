@echo off
setlocal enabledelayedexpansion
title LoL Remote Pick - Launcher

:: Change directory to script location
cd /d "%~dp0"

:: 1. Check if uv is installed
where uv >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] Detected 'uv' package manager. Launching application...
    uv run run.py --open %*
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Application failed to start.
        pause
    )
    goto :eof
)

:: 2. Check if python or py is installed
set "PY_CMD="
where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_CMD=py"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo.
    echo ================================================================================
    echo  [ERROR] Python is not installed or not in PATH.
    echo ================================================================================
    echo  To run LoL Remote Pick, please install Python 3.10+:
    echo    1. Download from: https://www.python.org/downloads/
    echo    2. During installation, make sure to check:
    echo       [X] "Add python.exe to PATH"
    echo    3. Re-run this start.bat file.
    echo ================================================================================
    echo.
    pause
    exit /b 1
)

:: 3. Setup Virtual Environment if not exists
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment (.venv) for the first time...
    %PY_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: 4. Activate Virtual Environment
call ".venv\Scripts\activate.bat"

:: 5. Install / Check dependencies
echo [INFO] Checking Python dependencies...
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [WARNING] Re-trying dependency installation...
    python -m pip install -r requirements.txt
)

:: 6. Launch Application
python run.py --open %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with error.
    pause
)
