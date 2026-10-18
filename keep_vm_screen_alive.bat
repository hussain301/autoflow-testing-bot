@echo off
title Azure / AWS EC2 Windows VM Keep-Alive & Console Auto-Play
set "TARGET_SID=%~1"
set "TARGET_W=%~2"
set "TARGET_H=%~3"
set "AUTO_MODE=%~4"

if "%TARGET_W%"=="" set "TARGET_W=1920"
if "%TARGET_H%"=="" set "TARGET_H=1080"

:: 1. Disable Windows sleep, monitor turn-off, lock screen & inactivity timeouts
powercfg /change monitor-timeout-ac 0 >nul 2>&1
powercfg /change monitor-timeout-dc 0 >nul 2>&1
powercfg /change standby-timeout-ac 0 >nul 2>&1
powercfg /change standby-timeout-dc 0 >nul 2>&1
powercfg /change hibernate-timeout-ac 0 >nul 2>&1
powercfg /change hibernate-timeout-dc 0 >nul 2>&1

reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v InactivityTimeoutSecs /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d "0" /f >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v SCRNSAVE.EXE /t REG_SZ /d "" /f >nul 2>&1

:: 2. Find exact active Session ID if not passed from Python
if "%TARGET_SID%"=="" (
    for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "(Get-Process -Id $PID).SessionId"`) do (
        set "TARGET_SID=%%i"
    )
)

if "%TARGET_SID%"=="" (
    for /f "tokens=1,2,3,4" %%a in ('query session') do (
        echo %%a | findstr /b ">" >nul && (
            set "TARGET_SID=%%c"
        )
    )
)

echo Shifting Active Session ID [%TARGET_SID%] to VM Console...
if not "%TARGET_SID%"=="" (
    %windir%\System32\tscon.exe %TARGET_SID% /dest:console
)

:: 3. Wait 2 seconds for Console Display Driver handoff, then lock Console Resolution to match Recording (e.g. 1920x1080)
timeout /t 2 /nobreak >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Set-DisplayResolution -Width %TARGET_W% -Height %TARGET_H% -Force -ErrorAction SilentlyContinue } catch {}" >nul 2>&1

if /i not "%AUTO_MODE%"=="AUTO" (
    echo.
    echo Done! VM Session [%TARGET_SID%] is now active on Console (%TARGET_W%x%TARGET_H%).
    timeout /t 2 >nul 2>&1
)
