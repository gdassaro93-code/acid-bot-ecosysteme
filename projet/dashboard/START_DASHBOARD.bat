@echo off
cd /d "%~dp0"
title ACID BOT - Dashboard
start "" http://127.0.0.1:8050
python dashboard_server.py
pause
