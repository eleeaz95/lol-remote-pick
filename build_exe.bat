@echo off
setlocal
title LoL Remote Pick - Windows Executable Builder

echo ================================================================================
echo   Building Standalone Windows Executable (.exe) for LoL Remote Pick
echo ================================================================================

cd /d "%~dp0"

:: Check if uv is available
where uv >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] Building with uv...
    uv run python build_windows.py
    pause
    goto :eof
)

:: Check if python is available
where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo [ERROR] Python not found. Please install Python 3.10+ to build.
        pause
        exit /b 1
    )
    set "PY_CMD=py"
) else (
    set "PY_CMD=python"
)

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    python build_windows.py
) else (
    %PY_CMD% build_windows.py
)

pause
