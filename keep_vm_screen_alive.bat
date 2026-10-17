@echo off
title Azure / AWS EC2 Windows VM Keep-Alive (Detach RDP Safely)
color 0B
echo ============================================================================
echo   AZURE / AWS EC2 WINDOWS VM KEEP-ALIVE (DETACH RDP TO VIRTUAL CONSOLE)
echo ============================================================================
echo.
echo  Jab aap RDP ko normal [X] button se close karte hain, toh Windows session
echo  Lock/Disconnect ho jata hai aur Mouse/Keyboard automation ruk jati hai.
echo.
echo  Yeh script aapke RDP session ko VM ke internal "console" screen par shift
echo  kar degi taake RDP band hone ke baad bhi VM ki screen 100%% ON rahe!
echo ============================================================================
echo.

:: Disable Windows sleep & screen turn-off timeouts
powercfg /change monitor-timeout-ac 0 >nul 2>&1
powercfg /change monitor-timeout-dc 0 >nul 2>&1
powercfg /change standby-timeout-ac 0 >nul 2>&1
powercfg /change standby-timeout-dc 0 >nul 2>&1

:: Transfer active RDP sessions to Console so GUI/Mouse/Browser stays active 24/7
for /f "skip=1 tokens=3" %%s in ('query user %USERNAME%') do (
    echo Shifting session ID %%s to Console...
    %windir%\System32\tscon.exe %%s /dest:console
)

for %%i in (1 2 3 4 5) do (
    %windir%\System32\tscon.exe %%i /dest:console >nul 2>&1
)

echo.
echo Done! If your RDP window did not close, right-click this file and select
echo "Run as administrator" inside your Azure / EC2 Windows VM.
timeout /t 4
