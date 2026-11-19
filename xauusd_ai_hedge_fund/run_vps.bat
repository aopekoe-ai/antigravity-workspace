@echo off
chcp 65001 > nul
title 🤖 XAU/USD Institutional SMC System [VPS 24/7 Daemon]

echo ======================================================================
echo   🤖 XAU/USD Institutional SMC System - VPS 24/7 自動復旧ランチャー
echo ======================================================================
echo.

cd /d "%~dp0"

:RESTART_LOOP
echo [%date% %time%] システムを起動しています (main.py)...
python main.py

echo.
echo ======================================================================
echo [WARNING] プロセスが終了しました。5秒後に自動再起動します...
echo (完全に終了させたい場合は、このウィンドウを閉じるか Ctrl+C を押してください)
echo ======================================================================
timeout /t 5 /nobreak > nul
goto RESTART_LOOP
