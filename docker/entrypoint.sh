#!/usr/bin/env bash
set -e

echo "=================================================================="
echo "  🤖 XAU/USD Institutional SMC System - Linux Docker Container"
echo "=================================================================="

# 仮想ディスプレイ (Xvfb) の起動
Xvfb :99 -screen 0 1024x768x16 &
export DISPLAY=:99
sleep 2

# MT5が未インストールの場合は自動インストール
if [ ! -d "/root/.wine/drive_c/Program Files/MetaTrader 5" ]; then
    echo "[SETUP] MT5の初期インストールを実行中..."
    wget -q https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe -O /tmp/mt5setup.exe
    wine /tmp/mt5setup.exe /auto
    rm -f /tmp/mt5setup.exe
    echo "[SETUP] MT5のインストールが完了しました。"
fi

# クオンツ取引システムの常駐実行 (Embeddable Python)
echo "[START] 取引エンジン (main.py) を起動します..."
exec wine /root/.wine/drive_c/Python310/python.exe main.py
