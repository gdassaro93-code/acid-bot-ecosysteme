@echo off
title CONTROLE AVANT VOL - Ecosysteme ACID
cd /d "%~dp0"
python "controle_avant_vol.py"
if errorlevel 1 (
    echo.
    echo   Le controle s'est arrete sur une erreur.
    pause
)
