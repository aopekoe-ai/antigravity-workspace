@echo off
chcp 65001 > nul
title Antigravity Secretary Bot Restart

cd /d "%~dp0"

set PYTHON_EXE=C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

"%PYTHON_EXE%" restart_secretary.py

timeout /t 3 > nul
