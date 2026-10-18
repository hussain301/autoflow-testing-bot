@echo off
setlocal EnableDelayedExpansion
title Azure and AWS EC2 Windows VM Keep-Alive + Virtual Display
color 0B
cd /d "%~dp0"

echo [AutoFlow] Preparing Virtual Display ^& shifting active RDP session to VM Console...

:: 1. Disable Windows sleep, monitor turn-off, and lock screen timeouts
powercfg /change monitor-timeout-ac 0 >nul 2>&1
powercfg /change monitor-timeout-dc 0 >nul 2>&1
powercfg /change standby-timeout-ac 0 >nul 2>&1
powercfg /change standby-timeout-dc 0 >nul 2>&1
powercfg /change hibernate-timeout-ac 0 >nul 2>&1
powercfg /change hibernate-timeout-dc 0 >nul 2>&1

reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v DisableLockWorkstation /t REG_DWORD /d 1 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v InactivityTimeoutSecs /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Lsa" /v LimitBlankPasswordUse /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d "0" /f >nul 2>&1

:: 2. Ensure Virtual Monitor Driver (usbmmidd_v2) is enabled so EC2 Console has a 1920x1080 display
if exist "C:\usbmmidd_v2\deviceinstaller64.exe" (
    pushd "C:\usbmmidd_v2"
    deviceinstaller64.exe enableidd 1 >nul 2>&1
    popd
)

:: 3. Transfer exact Session ID (if passed as %1) and all active RDP sessions to Console
if not "%~1"=="" (
    %windir%\System32\tscon.exe %~1 /dest:console >nul 2>&1
)

for /f "usebackq tokens=*" %%s in (`powershell -NoProfile -Command "(Get-Process -Id $PID).SessionId" 2^>nul`) do (
    if not "%%s"=="" (
        %windir%\System32\tscon.exe %%s /dest:console >nul 2>&1
    )
)

for /f "tokens=2,3,4" %%a in ('query session 2^>nul') do (
    echo %%b | findstr /r "^[0-9][0-9]*$" >nul && (
        %windir%\System32\tscon.exe %%b /dest:console >nul 2>&1
    )
    echo %%a | findstr /r "^[0-9][0-9]*$" >nul && (
        %windir%\System32\tscon.exe %%a /dest:console >nul 2>&1
    )
)

for %%i in (1 2 3 4 5) do (
    %windir%\System32\tscon.exe %%i /dest:console >nul 2>&1
)

exit /b 0
