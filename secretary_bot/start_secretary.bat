@echo off
chcp 65001 > nul
title Antigravity Secretary Bot

cd /d "%~dp0"

:: 本物のPythonパスを優先
set PYTHON_EXE=C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

echo ==================================================
echo   Antigravity 専属AI秘書 (Discord常駐型) 起動中...
echo ==================================================
echo.

"%PYTHON_EXE%" secretary.py

if %errorlevel% neq 0 (
    echo.
    echo [終了] エラーまたは中断により終了しました。
    pause
)
