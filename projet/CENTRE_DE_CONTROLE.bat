@echo off
cd /d "%~dp0"
start "" pythonw acid_center.py
if errorlevel 1 start "" python acid_center.py
