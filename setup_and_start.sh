#!/bin/bash
set -e

cd /root/xauusd_ai_hedge_fund

echo "=== 1. Starting mt5-server ==="
docker compose up -d mt5-server

echo "=== 2. Waiting for mt5-server to initialize (15s) ==="
sleep 15

echo "=== 3. Fixing lprett/mt5linux upstream bugs ==="
# Fix mkfifo FIFO pipe bug on restart
docker exec mt5-server sed -i 's|mkfifo -m 666 \$WIN_ROOT/server|rm -f \$WIN_ROOT/server; mkfifo -m 666 \$WIN_ROOT/server|' /app/src/automation.sh 2>/dev/null || true
# Fix FIRST_RUN non-zero exit code bug on restart
docker exec mt5-server sed -i 's/test \$FIRST_RUN || return/[ -n "\$FIRST_RUN" ] || return 0/' /app/src/config.sh 2>/dev/null || true
docker exec mt5-server sed -i 's/test \$FIRST_RUN || return/[ -n "\$FIRST_RUN" ] || return 0/' /app/src/mt5.sh 2>/dev/null || true
# Fix container restart loop by using sleep infinity
docker exec mt5-server sed -i 's/wait \$MT5_PID/sleep infinity/' /app/src/main.sh 2>/dev/null || true

echo "=== 4. Deploying Exness servers.dat, Bases, and master common.ini ==="
docker cp /tmp/mt5_extracted/Config/servers.dat mt5-server:/opt/wineprefix/drive_c/MT5/Config/servers.dat 2>/dev/null || true
docker cp /tmp/mt5_extracted/Bases/Exness-MT5Trial5 mt5-server:/opt/wineprefix/drive_c/MT5/Bases/Exness-MT5Trial5 2>/dev/null || true
docker cp /root/xauusd_ai_hedge_fund/config/common.ini mt5-server:/opt/wineprefix/drive_c/MT5/common.ini
docker cp /root/xauusd_ai_hedge_fund/config/common.ini mt5-server:/opt/wineprefix/drive_c/MT5/Config/common.ini

echo "=== 5. Building trading-bot container ==="
docker compose build trading-bot

echo "=== 6. Starting trading-bot ==="
docker compose up -d trading-bot

echo "=== 7. All containers started. Checking status ==="
docker compose ps
