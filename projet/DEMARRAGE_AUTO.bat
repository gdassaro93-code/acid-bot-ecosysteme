@echo off
REM ============================================================
REM  REPRISE APRES CRASH — ET SEULEMENT APRES UN CRASH.
REM
REM  LE PATRON, 02/10 : «…
REM  …
REM  …
REM  …»
REM
REM  LA REGLE, DONC :
REM    ecosysteme_actif.flag present  = il tournait quand la machine est tombee
REM                                     -> on relance, EN SILENCE
REM    flag absent                    = il avait ete arrete proprement
REM                                     -> ON NE FAIT RIEN, pas une fenetre
REM
REM  Le flag est pose par DEMARRER_ECOSYSTEME.bat et efface par
REM  ARRETER_ECOSYSTEME.bat. C'est donc l'intention du patron qui commande,
REM  pas une devinette.
REM
REM  SILENCE : tout part en pythonw (aucune console) et ce .bat lui-meme est
REM  appele par demarrage_auto.vbs en fenetre cachee. Rien ne clignote.
REM ============================================================
cd /d "%~dp0"

REM ─────────────────────────────────────────────────────────────────────
REM  17/10 — LE TEMOIN DOIT ETRE FRAIS, PAS SEULEMENT PRESENT.
REM  LE PATRON : «…
REM  …
REM  …».
REM  Mon erreur de conception : le temoin etait pose UNE FOIS au demarrage
REM  du cerveau et seul ARRETER_ECOSYSTEME.bat l'effacait. Le patron arrete
REM  ses bots autrement (le Centre, le gestionnaire de taches, en fermant
REM  les fenetres) -> le temoin restait la pour toujours -> relance a CHAQUE
REM  ouverture de session. Trace : 3 relances les 16 et 17/10.
REM  Le cerveau le rafraichit maintenant en continu. Un temoin de plus de
REM  FRAICHEUR_MIN minutes veut donc dire «…» : on ne
REM  relance pas. Peu importe COMMENT il a arrete ses bots.
REM ─────────────────────────────────────────────────────────────────────
set FRAICHEUR_MIN=15

if not exist "ecosysteme_actif.flag" (
    echo [%date% %time%] temoin absent : arret propre precedent, je ne lance RIEN >> demarrage_auto.log
    exit /b 0
)

for /f %%A in ('powershell -NoProfile -Command "[int]((Get-Date) - (Get-Item 'ecosysteme_actif.flag').LastWriteTime).TotalMinutes"') do set AGE=%%A
if %AGE% GEQ %FRAICHEUR_MIN% (
    echo [%date% %time%] temoin vieux de %AGE% min : l'ecosysteme etait deja arrete, je ne lance RIEN >> demarrage_auto.log
    del /q "ecosysteme_actif.flag"
    exit /b 0
)

echo [%date% %time%] temoin frais (%AGE% min) : il tournait quand la machine est tombee, reprise >> demarrage_auto.log

REM --- MT5 d'abord : les bots ne le lancent jamais eux-memes ---
tasklist /FI "IMAGENAME eq terminal64.exe" | find /I "terminal64.exe" >nul
if errorlevel 1 (
    for /f "delims=" %%i in ('python -c "import portabilite;print(portabilite.terminal_exe() or '')"') do start "" "%%i"
    timeout /t 45 /nobreak >nul
)

REM --- les briques, sans aucune console (pythonw) ---
start "" /B pythonw Server.py
timeout /t 8 /nobreak >nul
start "" /B pythonw server_ml_v2.py
timeout /t 8 /nobreak >nul
start "" /B pythonw ia_watchdog.py
timeout /t 6 /nobreak >nul
start "" /B pythonw BOT_MAMMOUTH_COMPLETE_V7.py
timeout /t 5 /nobreak >nul
start "" /B pythonw dashboard\dashboard_server.py
timeout /t 3 /nobreak >nul
start "" /B pythonw sniper_ml.py
timeout /t 2 /nobreak >nul
for %%O in (oeil1_crypto oeil2_metaux oeil3_range oeil4_choc oeil5_devises oeil6_risque) do (
    start "" /B pythonw yeux\%%O.py
)

REM --- trace : qui est vivant 20 s plus tard ---
timeout /t 20 /nobreak >nul
powershell -NoProfile -WindowStyle Hidden -Command "$m='ia_watchdog|server_ml_v2|BOT_MAMMOUTH|dashboard_server|Server\.py|sniper_ml|yeux'; $p=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match $m }; $t=(Get-Date).ToString('dd/MM HH:mm:ss'); Add-Content 'demarrage_auto.log' \"[$t] reprise terminee : $(($p|Measure-Object).Count) brique(s)\" -Encoding utf8"
exit /b 0
