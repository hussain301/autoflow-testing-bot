@echo off
title Azure and AWS EC2 Windows VM Keep-Alive
color 0B
echo Shifting active RDP session to VM Console and starting Macro Auto-Play...

:: Disable Windows sleep, monitor turn-off, and lock screen timeouts
powercfg /change monitor-timeout-ac 0 >nul 2>&1
powercfg /change monitor-timeout-dc 0 >nul 2>&1
powercfg /change standby-timeout-ac 0 >nul 2>&1
powercfg /change standby-timeout-dc 0 >nul 2>&1
powercfg /change hibernate-timeout-ac 0 >nul 2>&1
powercfg /change hibernate-timeout-dc 0 >nul 2>&1

reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v InactivityTimeoutSecs /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d "0" /f >nul 2>&1

:: Transfer active RDP session to Console so GUI/Mouse/Browser stays active 24/7
for /f "skip=1 tokens=3" %%s in ('query user %USERNAME% 2^>nul') do (
    %windir%\System32\tscon.exe %%s /dest:console >nul 2>&1
)

for /f "tokens=3" %%s in ('query session 2^>nul ^| findstr /i "Active"') do (
    %windir%\System32\tscon.exe %%s /dest:console >nul 2>&1
)

for %%i in (1 2 3 4 5) do (
    %windir%\System32\tscon.exe %%i /dest:console >nul 2>&1
)

exit /b 0
