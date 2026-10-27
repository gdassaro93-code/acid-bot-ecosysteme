@echo off
title ACID BOT Lanceur
cd /d "%~dp0"
color 0A

REM ============================================================
REM  04/10 — PLUS AUCUNE FENETRE QUI S'OUVRE DANS TOUS LES SENS.
REM  LE PATRON : «…
REM  …». Ce lanceur ouvrait CINQ consoles cmd (une par
REM  brique). Elles ne servaient a rien : le Centre de controle affiche deja
REM  la sortie de chaque bot dans ses onglets, et lui ne cree aucune fenetre
REM  (il lance en pythonw avec CREATE_NO_WINDOW).
REM  Tout part donc en pythonw : les bots tournent, on ne les voit pas.
REM
REM  Ce lanceur pose aussi ecosysteme_actif.flag : c'est lui qui dit a la
REM  tache planifiee «…».
REM  ARRETER_ECOSYSTEME.bat l'efface. Donc apres un arret propre, un
REM  demarrage de PC ne lance RIEN.
REM ============================================================

echo ============================================================
echo    DEMARRAGE DE L'ECOSYSTEME ACID BOT
echo ============================================================
echo.

echo Fermeture des anciennes instances ACID (si presentes)...
powershell -NoProfile -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'ia_watchdog|server_ml_v2|BOT_MAMMOUTH|dashboard_server|model_arena|Server\.py|sniper_ml|yeux' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
echo.

REM --- 1. MetaTrader 5 : les bots ne le lancent JAMAIS eux-memes ---
tasklist /FI "IMAGENAME eq terminal64.exe" | find /I "terminal64.exe" >nul
if errorlevel 1 (
    echo [1/7] MetaTrader 5 non detecte - lancement...
    for /f "delims=" %%i in ('python -c "import portabilite;print(portabilite.terminal_exe() or '')"') do start "" "%%i"
    echo       attente de la connexion ^(25 s^)...
    timeout /t 25 /nobreak >nul
) else (
    echo [1/7] MetaTrader 5 : deja ouvert - OK
)

echo [2/7] Serveur News 5001...
start "" /B pythonw Server.py
timeout /t 7 /nobreak >nul

echo [3/7] Serveur ML 8001...
start "" /B pythonw server_ml_v2.py
timeout /t 7 /nobreak >nul

echo [4/7] LE CERVEAU...
start "" /B pythonw ia_watchdog.py
timeout /t 5 /nobreak >nul

echo [5/7] Bot Python MAMMOUTH...
start "" /B pythonw BOT_MAMMOUTH_COMPLETE_V7.py
timeout /t 4 /nobreak >nul

echo [6/7] Dashboard 8050...
start "" /B pythonw dashboard\dashboard_server.py
timeout /t 3 /nobreak >nul

echo [7/7] Sniper ML et les 6 yeux...
start "" /B pythonw sniper_ml.py
for %%O in (oeil1_crypto oeil2_metaux oeil3_range oeil4_choc oeil5_devises oeil6_risque) do (
    start "" /B pythonw yeux\%%O.py
)
timeout /t 4 /nobreak >nul

REM --- le temoin : «…» ---
echo demarre le %date% a %time% > ecosysteme_actif.flag

echo.
echo ============================================================
echo    ECOSYSTEME LANCE - et sans aucune fenetre parasite.
echo.
powershell -NoProfile -Command "$m='ia_watchdog|server_ml_v2|BOT_MAMMOUTH|dashboard_server|Server\.py|sniper_ml|yeux'; $p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match $m }; Write-Host ('    ' + ($p|Measure-Object).Count + ' brique(s) en vie :'); $p | ForEach-Object { Write-Host ('      - ' + (($_.CommandLine -split '[\\ ]')[-1])) }"
echo.
echo    Telegram  : LE CERVEAU te parle et pilote tout
echo    Centre    : pythonw acid_center.py  (les logs de chaque bot)
echo    Dashboard : http://127.0.0.1:8050
echo.
echo    Pour tout couper : ARRETER_ECOSYSTEME.bat
echo ============================================================
echo.
REM 10/10 — le patron : «…
REM …». La derniere,
REM c'etait CE lanceur : il finissait par «…» et attendait une touche.
REM Il se ferme maintenant tout seul. Plus rien a fermer a la main.
echo Cette fenetre se ferme dans 6 secondes.
timeout /t 6 /nobreak >nul
exit
