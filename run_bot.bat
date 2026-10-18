@echo off
title AutoFlow Studio — Signup, Gmail OTP & Smart Vision Bot
cd /d "%~dp0"

:: Auto-elevate to Administrator so Virtual Display & VM Console handoff work without UAC blocks
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [AutoFlow] Launching AutoFlow Studio with Administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)

python -c "import customtkinter, pynput, cv2, winocr, googleapiclient" >nul 2>&1
if %errorlevel% neq 0 (
    echo [AutoFlow] Installing required Python packages for first-time setup...
    pip install -r requirements.txt
)

python bot.py
pause
