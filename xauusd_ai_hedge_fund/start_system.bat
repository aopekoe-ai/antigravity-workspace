@echo off
chcp 65001 > nul
title 🤖 XAU/USD AI Hedge Fund System Launcher
echo ============================================================
echo   🤖 XAU/USD AI Hedge Fund System 一括起動ランチャー
echo ============================================================
echo.
echo [INFO] 作業フォルダに移動中...
cd /d "C:\Users\user\.gemini\antigravity\scratch\xauusd_ai_hedge_fund"

echo [1/2] Discord 対話型 AI Bot を起動しています...
start "Discord AI Bot" /min python discord_chat_bot.py

echo [2/2] 毎時自動分析 & トレードスケジューラー を起動しています...
echo.
echo ============================================================
echo ※この黒い画面を開いたままにしておくと、毎時00分に自動で
echo   相場分析・トレード判定・Discord通知が実行されます。
echo ============================================================
echo.
python scheduler.py

pause
