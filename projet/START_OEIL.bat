@echo off
cd /d "%~dp0"
title ACID - L'OEIL (superviseur IA)
echo ============================================================
echo  L'OEIL - superviseur IA : journal MT5 + experts + bot
echo  Log : ia_watchdog.log  ^|  arret : fermer cette fenetre
echo ============================================================
python ia_watchdog.py
echo.
echo  L'OEIL s'est arrete - erreur ci-dessus
pause
