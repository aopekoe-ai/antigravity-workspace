#!/usr/bin/env bash
set -e

echo "======================================================================"
echo "  🚀 XAU/USD Institutional SMC System - Linux Docker 一括セットアップ"
echo "======================================================================"
echo ""

# 1. Docker のインストール確認
if ! command -v docker &> /dev/null; then
    echo "[INFO] Docker が未検出のため、インストールを開始します..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm -f get-docker.sh
    systemctl enable docker
    systemctl start docker
    echo "[OK] Docker のインストールが完了しました。"
else
    echo "[OK] 既存の Docker 環境を検出しました。"
fi

# 2. Docker Compose の確認
if ! docker compose version &> /dev/null; then
    echo "[INFO] Docker Compose プラグインを導入します..."
    apt-get update && apt-get install -y docker-compose-plugin
fi

echo ""
echo "[BUILD] 隔離コンテナ（Docker）をビルド＆起動しています..."
echo "※他のツールと完全に隔離され、リソース上限（CPU 2コア / メモリ 2GB）内で安全に稼働します。"
docker compose up -d --build

echo ""
echo "======================================================================"
echo "  ✅ セットアップが完了し、バックグラウンドで自律稼働を開始しました！"
echo "======================================================================"
echo ""
echo "📋 よく使うコマンド一覧:"
echo "  ・リアルタイムログ確認 : docker logs -f xauusd-quant-bot"
echo "  ・コンテナの停止       : docker compose down"
echo "  ・コンテナの再起動     : docker compose restart"
echo "  ・稼働状態チェック     : docker ps"
echo ""
