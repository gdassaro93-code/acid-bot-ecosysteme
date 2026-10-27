@echo off
cd /d "%~dp0"
title ACID - Serveur ML (port 8001)
echo ============================================================
echo  ACID - Serveur ML  --  http://127.0.0.1:8001
echo  Log fichier : ml_server.log  (visible aussi sur le dashboard)
echo ============================================================
python server_ml_v2.py
echo.
echo ============================================================
echo  LE SERVEUR ML S'EST ARRETE — l'erreur est affichee ci-dessus
echo  (si "address already in use" : il tourne deja ailleurs)
echo ============================================================
pause
