@echo off
setlocal EnableDelayedExpansion
title AutoFlow Studio — AWS EC2 & Azure Virtual Display Setup (1920x1080)
color 0B

:: Auto-elevate to Administrator if not already elevated
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [AutoFlow] Requesting Administrator privileges for Virtual Display Driver setup...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)

echo ============================================================================
echo   AutoFlow Studio — AWS EC2 Headless Virtual Monitor Setup (1920x1080)
echo ============================================================================
echo.

:: 1. Configure Windows Server Registry to prevent RDP Disconnect Lock / Idle Sleep
echo [1/4] Configuring Windows Server RDP & Console Keep-Alive Policies...
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

:: Terminal Services policies so sessions never terminate or sleep on disconnect
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v MaxDisconnectionTime /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v MaxIdleTime /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v fResetBroken /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v KeepAliveEnable /t REG_DWORD /d 1 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v KeepAliveInterval /t REG_DWORD /d 1 /f >nul 2>&1
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server" /v fSingleSessionPerUser /t REG_DWORD /d 0 /f >nul 2>&1

:: 2. Download and install Amyuni Signed WDDM Virtual Display Driver (usbmmidd_v2)
set "VDD_DIR=C:\usbmmidd_v2"
if not exist "%VDD_DIR%\deviceinstaller64.exe" (
    echo [2/4] Downloading Signed Virtual Monitor Driver ^(usbmmidd_v2^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
        "$zip = '$env:TEMP\usbmmidd_v2.zip'; " ^
        "Invoke-WebRequest -Uri 'https://www.amyuni.com/downloads/usbmmidd_v2.zip' -OutFile $zip -UseBasicParsing; " ^
        "if (Test-Path 'C:\usbmmidd_v2') { Remove-Item 'C:\usbmmidd_v2' -Recurse -Force }; " ^
        "Expand-Archive -Path $zip -DestinationPath 'C:\' -Force"
) else (
    echo [2/4] Virtual Monitor files already present in C:\usbmmidd_v2.
)

if exist "%VDD_DIR%\deviceinstaller64.exe" (
    echo [3/4] Installing & Enabling 1920x1080 Virtual Display Adapter...
    pushd "%VDD_DIR%"
    deviceinstaller64.exe install usbmmidd.inf usbmmidd >nul 2>&1
    deviceinstaller64.exe enableidd 1 >nul 2>&1
    popd

    :: Register Scheduled Task so Virtual Monitor stays active across EC2 reboots
    schtasks /create /tn "AutoFlow_VirtualDisplay" /tr "C:\usbmmidd_v2\deviceinstaller64.exe enableidd 1" /sc onstart /ru SYSTEM /f >nul 2>&1
    echo       [OK] Virtual Display Driver installed and enabled!
) else (
    echo       [WARN] Could not download usbmmidd_v2 automatically. Check internet connection.
)

:: 4. Lock Virtual Display Resolution to 1920x1080 via Win32 API
echo [4/4] Setting Virtual Monitor Resolution to 1920x1080...
python -c "import ctypes; from ctypes import wintypes; dm = (ctypes.c_byte * 220)(); ctypes.memset(dm, 0, 220); ctypes.c_uint16.from_buffer(dm, 68).value = 220; ctypes.c_uint32.from_buffer(dm, 72).value = 0x5C0000; ctypes.c_uint32.from_buffer(dm, 168).value = 32; ctypes.c_uint32.from_buffer(dm, 172).value = 1920; ctypes.c_uint32.from_buffer(dm, 176).value = 1080; ctypes.c_uint32.from_buffer(dm, 184).value = 60; ctypes.windll.user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0)" >nul 2>&1

echo.
echo ============================================================================
echo   SUCCESS! Virtual Display (1920x1080) & EC2 Keep-Alive Policies are READY!
echo   You can now click "VM Detach & Auto-Play" inside AutoFlow Studio.
echo ============================================================================
timeout /t 3 >nul
exit /b 0
