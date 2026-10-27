@echo off
title Arret ecosysteme ACID
color 0C

REM ============================================================
REM  29/09 - CE FICHIER NE TUAIT RIEN.
REM  Il cherchait uniquement "python.exe", alors que TOUS les bots sont
REM  lances en "pythonw.exe" (la version sans fenetre). Le patron le lancait,
REM  croyait avoir tout coupe, et les bots continuaient - en rappelant MT5 a
REM  chaque cycle via mt5.initialize(). D'ou : "j'ai tout ferme et ca trouve
REM  le moyen de revenir".
REM  Corrige : les DEUX noms de processus, et la liste complete des scripts
REM  (les 6 yeux, le sniper, l'arene et le Centre y manquaient aussi).
REM ============================================================

echo ============================================================
echo    ARRET DE L'ECOSYSTEME ACID BOT
echo ============================================================
echo.

REM --- 04/10 : on efface le temoin. Un arret VOLONTAIRE veut dire
REM     «…». C'est ce fichier
REM     qui distingue un arret propre d'un crash.
if exist "ecosysteme_actif.flag" del /q "ecosysteme_actif.flag"
echo Temoin efface : aucun redemarrage automatique au prochain boot.
echo.

echo [1/4] Arret des bots et serveurs Python...
powershell -NoProfile -Command "$m='ia_watchdog|server_ml_v2|BOT_MAMMOUTH|dashboard_server|Server\.py|sniper_ml|model_arena|ia_dialogue|yeux[\\/]oeil'; $p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match $m }; if ($p) { $p | ForEach-Object { Write-Host ('    - ' + (($_.CommandLine -split '[\\ ]')[-1])); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Host '    (aucun bot en cours)' }"

echo [2/4] Arret du Centre de controle...
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'acid_center' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host '    Centre ferme.' } else { Write-Host '    (Centre deja ferme)' }"

echo [3/4] Fermeture des fenetres ACID...
taskkill /FI "WINDOWTITLE eq ACID*" /F >nul 2>&1

echo [4/4] Arret du tunnel Cloudflare (si actif)...
taskkill /IM cloudflared.exe /F >nul 2>&1

echo.
echo Verification - ce qui tourne encore :
powershell -NoProfile -Command "$m='ia_watchdog|server_ml_v2|BOT_MAMMOUTH|dashboard_server|Server\.py|sniper_ml|model_arena|ia_dialogue|acid_center|yeux[\\/]oeil'; $p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match $m }; if ($p) { Write-Host '    ATTENTION, encore en vie :' -ForegroundColor Red; $p | ForEach-Object { Write-Host ('      pid ' + $_.ProcessId + '  ' + (($_.CommandLine -split '[\\ ]')[-1])) } } else { Write-Host '    Plus aucun bot ACID en memoire.' -ForegroundColor Green }"

echo.
echo (MetaTrader 5 et l'EA ACID IA restent ouverts par defaut)
echo.

set /p CLOSEMT5=Fermer aussi MetaTrader 5 ? (o/N) :
if /i "%CLOSEMT5%"=="o" (
    taskkill /IM terminal64.exe /F >nul 2>&1
    echo MetaTrader 5 ferme.
) else (
    echo MetaTrader 5 laisse ouvert.
)

echo.
echo ============================================================
echo    ECOSYSTEME ARRETE.
echo ============================================================
echo.
pause
