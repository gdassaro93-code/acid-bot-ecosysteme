@echo off
cd /d "%~dp0"
title ACID BOT - Lien public
echo ============================================================
echo   Lien public a partager (mot de passe : DASH_PASSWORD de secrets_acid.py)
echo   (patiente quelques secondes, le lien s'affiche seul)
echo ============================================================
echo.
rem Tout le log part dans tunnel.log (pour le bouton "Lien tunnel" du
rem Centre), et on n'affiche ICI que la ligne du lien (pas la fioriture).
powershell -NoProfile -Command "& '.\cloudflared.exe' tunnel --url http://127.0.0.1:8050 2>&1 | Tee-Object -FilePath tunnel.log | Select-String 'trycloudflare.com' | ForEach-Object { $_.Line.Trim() }"
