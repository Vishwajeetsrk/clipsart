@echo off
setlocal enabledelayedexpansion
title Clipsart Video Studio
echo ============================================================
echo   Starting Clipsart Video Studio...
echo ============================================================
echo.

cd /d "%~dp0"

:: 1. Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python was not found on your system PATH!
    echo Please install Python 3.10 or newer from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: 2. Check FFmpeg
where ffmpeg >nul 2>nul
if %ERRORLEVEL% neq 0 (
    if not exist "%~dp0bin\ffmpeg.exe" (
        echo [NOTICE] FFmpeg was not detected in PATH.
        echo Clipsart will attempt to launch, but installing FFmpeg is recommended:
        echo   winget install Gyan.FFmpeg
        echo.
    ) else (
        set "PATH=%~dp0bin;%PATH%"
    )
)

:: 3. Setup Virtual Environment
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment (.venv)...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: 4. Activate & Check Dependencies
call .venv\Scripts\activate.bat

if not exist ".venv\.installed" (
    echo [2/3] Installing / updating required packages...
    python -m pip install -q -r requirements.txt
    if %ERRORLEVEL% eq 0 (
        echo. > .venv\.installed
    )
)

:: 5. Launch Studio Server & Open Browser
echo [3/3] Launching Clipsart Studio on http://127.0.0.1:8765/app ...
start "" http://127.0.0.1:8765/app
python -m studio.server

pause
