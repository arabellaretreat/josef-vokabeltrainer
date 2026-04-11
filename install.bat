@echo off
chcp 65001 >nul
echo =============================================
echo   Josef's Vokabeltrainer - Erstinstallation
echo =============================================
echo.
echo Installiere benoetigte Pakete...
py -m pip install -r requirements.txt
echo.
echo ✅ Installation abgeschlossen!
echo    Du kannst die App jetzt mit "run.bat" starten.
echo.
pause
