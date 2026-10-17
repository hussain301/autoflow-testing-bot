@echo off
title AutoFlow Studio — Signup, Gmail OTP & Smart Vision Bot
cd /d "%~dp0"

python -c "import customtkinter, pynput, cv2, winocr, googleapiclient" >nul 2>&1
if %errorlevel% neq 0 (
    echo [AutoFlow] Installing required Python packages for first-time setup...
    pip install -r requirements.txt
)

python bot.py
pause
