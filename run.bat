@echo off
chcp 65001 >nul
title Josef's Vokabeltrainer
echo =============================================
echo   Josef's Vokabeltrainer DE ^<^> IT
echo =============================================
echo.
echo Starte App... Browser oeffnet sich automatisch.
echo Dieses Fenster offen lassen!
echo (Zum Beenden: Fenster schliessen oder Strg+C)
echo.
cd /d "%~dp0"
py app.py
pause
