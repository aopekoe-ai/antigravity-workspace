def get_dashboard_html() -> str:
    """
    スマホ＆PC完全対応・ダークモード単一ページクオンツ運用ダッシュボード (v9.2)
    外部CDN障害に左右されないネイティブCanvasチャート＆レスポンシブUI内蔵
    """
    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>XAU/USD AI Quant Hedge Fund v9.2 Cockpit</title>
<style>
  :root {
    --bg: #0b0f17;
    --card: #131a27;
    --card-alt: #182132;
    --border: #233047;
    --text: #f1f5f9;
    --muted: #94a3b8;
    --gold: #f59e0b;
    --bull: #10b981;
    --bear: #f43f5e;
    --accent: #6366f1;
    --violet: #8b5cf6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Hiragino Sans", "Noto Sans JP", sans-serif;
    font-size: 14px;
    line-height: 1.45;
    padding-bottom: 76px;
    font-variant-numeric: tabular-nums;
  }
  .topbar {
    position: sticky; top: 0; z-index: 40;
    background: rgba(11, 15, 23, 0.92);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
    padding: 10px 14px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  }
  .brand { font-weight: 800; font-size: 15px; display: flex; align-items: center; gap: 8px; color: var(--gold); }
  .badge {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;
    background: var(--card-alt); border: 1px solid var(--border); color: var(--text);
  }
  .badge.bull { background: rgba(16,185,129,0.15); border-color: rgba(16,185,129,0.4); color: #34d399; }
  .badge.bear { background: rgba(244,63,94,0.15); border-color: rgba(244,63,94,0.4); color: #fb7185; }
  .badge.gold { background: rgba(245,158,11,0.15); border-color: rgba(245,158,11,0.4); color: #fbbf24; }
  .badge.violet { background: rgba(139,92,246,0.18); border-color: rgba(139,92,246,0.45); color: #c4b5fd; }

  .container { max-width: 1160px; margin: 0 auto; padding: 12px; }
  .grid-4 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 12px; }
  .grid-3 { display: grid; grid-template-columns: 1fr; gap: 10px; margin-bottom: 12px; }
  .grid-2 { display: grid; grid-template-columns: 1fr; gap: 12px; margin-bottom: 12px; }
  @media (min-width: 768px) {
    .grid-4 { grid-template-columns: repeat(4, 1fr); }
    .grid-3 { grid-template-columns: repeat(3, 1fr); }
    .grid-2 { grid-template-columns: repeat(2, 1fr); }
  }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 13px;
    margin-bottom: 12px;
  }
  .card-title {
    font-size: 13px; font-weight: 700; color: var(--muted);
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 10px;
  }
  .kpi-val { font-size: 20px; font-weight: 800; margin-top: 2px; }
  .kpi-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .text-bull { color: var(--bull); }
  .text-bear { color: var(--bear); }
  .text-gold { color: var(--gold); }

  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    padding: 9px 13px; border-radius: 8px; font-size: 13px; font-weight: 700;
    border: 1px solid var(--border); background: var(--card-alt); color: var(--text);
    cursor: pointer; transition: 0.15s;
  }
  .btn:hover { filter: brightness(1.12); }
  .btn:active { transform: scale(0.98); }
  .btn-primary { background: var(--accent); border-color: #818cf8; color: #fff; }
  .btn-gold { background: var(--gold); border-color: #fbbf24; color: #0b0f17; }
  .btn-bull { background: rgba(16,185,129,0.2); border-color: var(--bull); color: #34d399; }
  .btn-bear { background: rgba(244,63,94,0.2); border-color: var(--bear); color: #fb7185; }
  .btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 6px; }
  .btn-block { width: 100%; }

  .meter-row { margin-bottom: 9px; }
  .meter-head { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }
  .meter-bar { height: 7px; background: #0b0f17; border-radius: 99px; overflow: hidden; border: 1px solid var(--border); }
  .meter-fill { height: 100%; transition: width 0.3s ease; }

  .pos-slot {
    background: var(--card-alt); border: 1px solid var(--border); border-radius: 10px; padding: 11px;
  }
  .pos-slot.active-buy { border-color: rgba(16,185,129,0.55); background: rgba(16,185,129,0.06); }
  .pos-slot.active-sell { border-color: rgba(244,63,94,0.55); background: rgba(244,63,94,0.06); }

  .tab-pane { display: none; }
  .tab-pane.active { display: block; }

  .bottom-nav {
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 50;
    background: rgba(15, 21, 33, 0.96); backdrop-filter: blur(10px);
    border-top: 1px solid var(--border);
    display: grid; grid-template-columns: repeat(4, 1fr);
    padding: 6px 4px;
  }
  .nav-btn {
    background: none; border: none; color: var(--muted);
    display: flex; flex-direction: column; align-items: center; gap: 3px;
    font-size: 11px; font-weight: 700; padding: 6px 2px; cursor: pointer; border-radius: 8px;
  }
  .nav-btn.active { color: var(--gold); background: rgba(245,158,11,0.1); }
  .nav-icon { font-size: 17px; }

  .form-group { margin-bottom: 10px; }
  .form-label { display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }
  .form-input, .form-select, .form-textarea {
    width: 100%; padding: 8px 10px; border-radius: 8px;
    background: #0b0f17; border: 1px solid var(--border); color: var(--text);
    font-size: 13px;
  }
  .form-textarea { min-height: 68px; resize: vertical; }
  input[type="range"] { width: 100%; accent-color: var(--gold); cursor: pointer; }

  .stance-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 12px; }
  @media (min-width: 640px) { .stance-grid { grid-template-columns: repeat(4, 1fr); } }
  .stance-btn {
    padding: 10px 8px; border-radius: 10px; border: 1px solid var(--border);
    background: var(--card-alt); color: var(--text); font-weight: 700; font-size: 12px;
    cursor: pointer; text-align: center;
  }
  .stance-btn.active { border-color: var(--gold); background: rgba(245,158,11,0.16); color: #fbbf24; }

  .toggle-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 0; border-bottom: 1px solid rgba(35,48,71,0.5);
  }
  .toggle-row:last-child { border-bottom: none; }
  input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--bull); cursor: pointer; }

  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 7px 6px; text-align: left; border-bottom: 1px solid rgba(35,48,71,0.6); }
  th { color: var(--muted); font-weight: 600; }

  canvas { width: 100%; height: 190px; display: block; background: #0b0f17; border-radius: 8px; border: 1px solid var(--border); }

  #toast {
    position: fixed; top: 58px; right: 14px; z-index: 100;
    padding: 10px 14px; border-radius: 8px; font-weight: 700; font-size: 12px;
    background: #1e293b; border: 1px solid var(--gold); color: #fff;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5); display: none;
  }
</style>
</head>
<body>

<div id="toast"></div>

<header class="topbar">
  <div class="brand">⚡ XAU/USD Quant Fund <span style="font-size:11px;color:var(--muted);">v9.2</span></div>
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
    <span id="badge-source" class="badge">📡 読込中...</span>
    <span id="badge-regime" class="badge violet">🎛️ REGIME</span>
    <span id="badge-spread" class="badge">Sp: --</span>
    <button class="btn btn-sm" onclick="refreshAll()">🔄 更新</button>
  </div>
</header>

<main class="container">
  <!-- 共通KPIリボン -->
  <div class="grid-4">
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">💵 現在価格 (<span id="kpi-symbol">XAUUSD</span>)</div>
      <div id="kpi-price" class="kpi-val text-gold">$----.--</div>
      <div id="kpi-mtf" class="kpi-sub">H1: -- / M15: --</div>
    </div>
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">🏦 口座残高 / 有効証拠金</div>
      <div id="kpi-balance" class="kpi-val">¥---,---</div>
      <div id="kpi-broker" class="kpi-sub">Exness #---</div>
    </div>
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">📈 直近24h確定損益</div>
      <div id="kpi-today-pnl" class="kpi-val">¥0</div>
      <div id="kpi-today-stats" class="kpi-sub">0戦 0勝0敗0BE (PF --)</div>
    </div>
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">🔥 保有中含み損益</div>
      <div id="kpi-open-pnl" class="kpi-val">¥0</div>
      <div id="kpi-open-count" class="kpi-sub">保有: 0 / 3 ポジション</div>
    </div>
  </div>

  <!-- ==================== TAB 1: LIVE COCKPIT ==================== -->
  <section id="tab-live" class="tab-pane active">
    <div class="card">
      <div class="card-title">
        <span>🎯 3系統エンジン・ライブスロット（最大3ポジション順張りピラミッディング）</span>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-sm btn-bull" onclick="posAction('lock_be_all')">🔒 含み益を建値ロック</button>
          <button class="btn btn-sm btn-bear" onclick="posAction('close_all')">🚨 全ポジ一括決済</button>
        </div>
      </div>
      <div id="live-slots" class="grid-3"></div>
    </div>

    <div class="grid-2">
      <div class="card" style="margin-bottom:0;">
        <div class="card-title">📡 リアルタイム先行指標メーター（TradingView / MT5 M1）</div>
        <div class="meter-row">
          <div class="meter-head"><span>💵 ドル指数 (DXY) 3-5m Zスコア</span><strong id="m-dxy-val">0.00σ</strong></div>
          <div class="meter-bar"><div id="m-dxy-bar" class="meter-fill" style="width:50%;background:var(--gold);"></div></div>
        </div>
        <div class="meter-row">
          <div class="meter-head"><span>🏛️ 米金利 (US10Y / USDJPY) Zスコア</span><strong id="m-yield-val">0.00σ</strong></div>
          <div class="meter-bar"><div id="m-yield-bar" class="meter-fill" style="width:50%;background:var(--accent);"></div></div>
        </div>
        <div class="meter-row">
          <div class="meter-head"><span>🛢️ 原油 (USOIL) / 📈 米株 (USTEC) Z</span><strong id="m-oil-val">0.00σ / 0.00σ</strong></div>
        </div>
        <div class="meter-row" style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border);">
          <div class="meter-head"><span>🔥 ゴールド統合マクロバイアス (-1.0〜+1.0)</span><strong id="m-bias-val">+0.00</strong></div>
          <div class="meter-bar"><div id="m-bias-bar" class="meter-fill" style="width:50%;background:var(--bull);"></div></div>
        </div>
      </div>

      <div class="card" style="margin-bottom:0;">
        <div class="card-title">📉 直近1分足ゴールド価格 ＆ マクロバイアス推移 (SQLite DB)</div>
        <canvas id="chart-live-m1" width="520" height="190"></canvas>
      </div>
    </div>
  </section>

  <!-- ==================== TAB 2: LAB (本格検証) ==================== -->
  <section id="tab-lab" class="tab-pane">
    <div class="card">
      <div class="card-title">
        <span>🎛️ 「もしも（What-If）」スライダー高速バックテスト（現行 vs 変更後シミュレーション）</span>
        <button class="btn btn-sm btn-gold" onclick="applySimParamsToLive()">✨ この検証設定を本番BOTへ即適用</button>
      </div>
      <div class="grid-2">
        <div>
          <div class="form-group">
            <div class="form-label"><span>型A マクロ発火Zスコア閾値</span><strong id="lbl-sim-z">1.50</strong></div>
            <input type="range" id="sim-z" min="1.20" max="2.00" step="0.05" value="1.50" oninput="updateSimLabels();runBacktest();">
          </div>
          <div class="form-group">
            <div class="form-label"><span>型A マクロ最小リスクリワード比 (RR)</span><strong id="lbl-sim-mrr">1.80</strong></div>
            <input type="range" id="sim-mrr" min="1.50" max="2.50" step="0.05" value="1.80" oninput="updateSimLabels();runBacktest();">
          </div>
          <div class="form-group">
            <div class="form-label"><span>系統3 SMC 最小リスクリワード比 (RR)</span><strong id="lbl-sim-srr">1.50</strong></div>
            <input type="range" id="sim-srr" min="1.30" max="2.40" step="0.05" value="1.50" oninput="updateSimLabels();runBacktest();">
          </div>
          <div class="form-group">
            <div class="form-label"><span>ATR SL倍率（損切り幅の余裕度）</span><strong id="lbl-sim-atr">1.30</strong></div>
            <input type="range" id="sim-atr" min="1.00" max="2.00" step="0.05" value="1.30" oninput="updateSimLabels();runBacktest();">
          </div>
          <div class="form-group">
            <div class="form-label"><span>最大同時保有ポジション数（ピラミッディング）</span><strong id="lbl-sim-pos">3</strong></div>
            <input type="range" id="sim-pos" min="1" max="3" step="1" value="3" oninput="updateSimLabels();runBacktest();">
          </div>
        </div>
        <div>
          <div id="sim-summary" style="margin-bottom:8px;font-size:12px;"></div>
          <canvas id="chart-backtest" width="520" height="190"></canvas>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>🛡️ シャドートレード検証（「見送ったシグナル」が本当にSLだったか自動答え合わせ）</span>
        <span class="badge violet">SQLite 自動採点中</span>
      </div>
      <div id="shadow-scorecard" style="margin-bottom:10px;"></div>
      <div style="overflow-x:auto;">
        <table>
          <thead><tr><th>時刻</th><th>エンジン</th><th>売買</th><th>見送り理由</th><th>仮想Entry/SL/TP</th><th>答え合わせ結果</th></tr></thead>
          <tbody id="shadow-tbody"></tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>🔬 週末クオンツ研究室（2026年最新相関・複合シナリオ・M1リードラグ時間差）</span>
        <button class="btn btn-sm btn-primary" onclick="triggerLabTask('weekend_study')">🔄 今すぐ再検証＆Discord送信</button>
      </div>
      <div id="weekend-study-box" style="font-size:12px;"></div>
    </div>
  </section>

  <!-- ==================== TAB 3: ANALYTICS (戦績) ==================== -->
  <section id="tab-analytics" class="tab-pane">
    <div class="card">
      <div class="card-title">📈 確定トレード資産推移（エクイティカーブ）</div>
      <canvas id="chart-equity" width="800" height="190"></canvas>
    </div>

    <div class="card">
      <div class="card-title">⚙️ 3系統エンジン別 ＆ セッション別（東京・ロンドン・NY）パフォーマンス比較</div>
      <div id="engine-perf-grid" class="grid-3"></div>
      <div id="session-perf-bar" style="margin-top:8px;font-size:12px;"></div>
    </div>

    <div class="card">
      <div class="card-title">📜 直近トレード履歴（MT5完全突合済）</div>
      <div style="overflow-x:auto;">
        <table>
          <thead><tr><th>日時</th><th>エンジン</th><th>売買/Lot</th><th>セットアップ</th><th>Entry → Close</th><th>損益(JPY)</th></tr></thead>
          <tbody id="trades-tbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- ==================== TAB 4: CONTROL & BROKER ==================== -->
  <section id="tab-control" class="tab-pane">
    <div class="card">
      <div class="card-title">⚡ 運用スタンス（ワンタップでロジック改修方針を一括切替）</div>
      <div class="stance-grid">
        <button class="stance-btn" id="st-AGGRESSIVE" onclick="setStance('AGGRESSIVE')">🔥 積極トレンド追撃<br><span style="font-size:10px;color:var(--muted);">Z閾値1.35 / 最大3ポジ</span></button>
        <button class="stance-btn" id="st-BALANCED" onclick="setStance('BALANCED')">⚖️ 標準バランス<br><span style="font-size:10px;color:var(--muted);">Z閾値1.50 / 最大3ポジ</span></button>
        <button class="stance-btn" id="st-DEFENSIVE" onclick="setStance('DEFENSIVE')">🛡️ 厳選・資金防衛<br><span style="font-size:10px;color:var(--muted);">Z閾値1.70 / 最大1ポジ</span></button>
        <button class="stance-btn" id="st-PAUSED" onclick="setStance('PAUSED')">⏸️ 新規エントリー停止<br><span style="font-size:10px;color:var(--muted);">保有中ポジのみ管理</span></button>
      </div>
    </div>

    <div class="grid-2">
      <div class="card" style="margin-bottom:0;">
        <div class="card-title">🎛️ 3系統エンジンON/OFF ＆ リスク・フィルター詳細設定</div>
        <div class="toggle-row"><span>🚀 系統1：型A マクロモメンタム (FVG不要)</span><input type="checkbox" id="cfg-en-a" checked></div>
        <div class="toggle-row"><span>🎯 系統2：型B SMTダイバージェンス (FVG不要)</span><input type="checkbox" id="cfg-en-b" checked></div>
        <div class="toggle-row"><span>🏛️ 系統3：既存SMC 3トリガー (Fractal/FVG/EMA)</span><input type="checkbox" id="cfg-en-smc" checked></div>
        <div class="toggle-row"><span>🌏 東京セッション (08:00-15:00 JST) 取引許可</span><input type="checkbox" id="cfg-sess-asia" checked></div>
        <div class="toggle-row"><span>🇬🇧 ロンドンセッション (15:00-24:00 JST) 取引許可</span><input type="checkbox" id="cfg-sess-lon" checked></div>
        <div class="toggle-row"><span>🗽 NYセッション (21:00-06:00 JST) 取引許可</span><input type="checkbox" id="cfg-sess-ny" checked></div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;">
          <div class="form-group">
            <div class="form-label"><span>最大同時保有ポジ数</span></div>
            <select id="cfg-max-pos" class="form-select"><option value="1">1ポジ (単ポジ)</option><option value="2">2ポジ</option><option value="3" selected>3ポジ (3系統)</option></select>
          </div>
          <div class="form-group">
            <div class="form-label"><span>1トレードリスク (%)</span></div>
            <input type="number" id="cfg-risk-pct" class="form-input" step="0.1" min="0.3" max="3.0" value="1.5">
          </div>
          <div class="form-group">
            <div class="form-label"><span>日次最大DD停止 (%)</span></div>
            <input type="number" id="cfg-dd-pct" class="form-input" step="0.5" min="1.0" max="6.0" value="3.0">
          </div>
          <div class="form-group">
            <div class="form-label"><span>最大ロット上限 (Lot)</span></div>
            <input type="number" id="cfg-max-lot" class="form-input" step="0.05" min="0.01" max="1.00" value="0.50">
          </div>
          <div class="form-group">
            <div class="form-label"><span>許容スプレッド (pips)</span></div>
            <input type="number" id="cfg-max-sp" class="form-input" step="0.2" min="1.5" max="5.0" value="3.0">
          </div>
          <div class="form-group">
            <div class="form-label"><span>連敗防止待機 (分)</span></div>
            <input type="number" id="cfg-sl-cool" class="form-input" step="5" min="5" max="60" value="15">
          </div>
        </div>
      </div>

      <div>
        <div class="card">
          <div class="card-title">🤖 AI自己最適化（Step 3）へのオーナー改修方針指示</div>
          <div class="form-group">
            <div class="form-label"><span>毎朝06:00のGemini自己最適化に反映させたい方針・要望</span></div>
            <textarea id="cfg-owner-dir" class="form-textarea" placeholder="例：今週はトレンドが伸びやすいので利確RR比を広めにし、FVG条件は緩めて機会損失を防いでほしい"></textarea>
          </div>
          <div class="card-title" style="margin-top:8px;">🔔 Discord通知設定 ＆ 手動送信</div>
          <div class="toggle-row"><span>毎時00分 AI合議体レポート通知</span><input type="checkbox" id="cfg-notif-hourly" checked></div>
          <div class="toggle-row"><span>毎週土曜08:00 週末クオンツ研究室レポート通知</span><input type="checkbox" id="cfg-notif-weekend" checked></div>
          <div class="form-group" style="margin-top:8px;">
            <div class="form-label"><span>日次運用ブリーフィング配信時刻 (JST)</span></div>
            <select id="cfg-daily-hour" class="form-select"><option value="6">毎朝 06:00 JST (NYクローズ直後)</option><option value="7">毎朝 07:00 JST</option><option value="8">毎朝 08:00 JST</option></select>
          </div>
          <div style="display:flex;gap:8px;margin-top:10px;">
            <button class="btn btn-gold btn-block" onclick="saveControlConfig()">💾 設定・改修方針を保存 (即反映)</button>
            <button class="btn btn-primary" style="white-space:nowrap;" onclick="triggerLabTask('daily_report')">📨 日次レポート今すぐ送信</button>
          </div>
        </div>

        <div class="card" style="margin-bottom:0;">
          <div class="card-title">
            <span>🏦 MT5アカウント（証券会社・口座）変更 ＆ 銘柄自動マッピング</span>
            <span id="broker-conn-badge" class="badge bull">接続中</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div class="form-group">
              <div class="form-label"><span>MT5 ログイン番号</span></div>
              <input type="number" id="brk-login" class="form-input" placeholder="277984494">
            </div>
            <div class="form-group">
              <div class="form-label"><span>ブローカーサーバー名</span></div>
              <input type="text" id="brk-server" class="form-input" placeholder="Exness-MT5Trial5">
            </div>
            <div class="form-group">
              <div class="form-label"><span>MT5 パスワード</span></div>
              <input type="password" id="brk-pass" class="form-input" placeholder="変更時のみ入力">
            </div>
            <div class="form-group">
              <div class="form-label"><span>ゴールド銘柄名 (空欄で自動検出)</span></div>
              <input type="text" id="brk-symbol" class="form-input" placeholder="XAUUSD / GOLD">
            </div>
          </div>
          <div id="brk-detected-info" style="font-size:11px;color:var(--muted);margin-bottom:8px;"></div>
          <button class="btn btn-primary btn-block" onclick="switchBrokerAccount()">🔄 MT5口座を即時切替 ＆ シンボル自動検出</button>
        </div>
      </div>
    </div>
  </section>
</main>

<nav class="bottom-nav">
  <button class="nav-btn active" onclick="switchTab('live', this)"><span class="nav-icon">⚡</span><span>LIVE監視</span></button>
  <button class="nav-btn" onclick="switchTab('lab', this)"><span class="nav-icon">🧪</span><span>LAB検証</span></button>
  <button class="nav-btn" onclick="switchTab('analytics', this)"><span class="nav-icon">📊</span><span>戦績分析</span></button>
  <button class="nav-btn" onclick="switchTab('control', this)"><span class="nav-icon">⚙️</span><span>制御・口座</span></button>
</nav>

<script>
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('key')) {
  localStorage.setItem('xau_dash_key', urlParams.get('key'));
}
function getKey() {
  let k = localStorage.getItem('xau_dash_key') || '';
  if (!k) {
    k = prompt('ダッシュボードのアクセスキーを入力してください:') || '';
    if (k) localStorage.setItem('xau_dash_key', k);
  }
  return k;
}

function showToast(msg, isErr=false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = isErr ? 'var(--bear)' : 'var(--gold)';
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 3500);
}

async function apiCall(path, method='GET', body=null) {
  const k = getKey();
  const headers = {'X-Dashboard-Key': k};
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(path + (path.includes('?') ? '&' : '?') + 'key=' + encodeURIComponent(k), {
    method, headers, body: body ? JSON.stringify(body) : null
  });
  if (res.status === 401) {
    localStorage.removeItem('xau_dash_key');
    showToast('認証キーが無効です。再入力してください。', true);
    throw new Error('Unauthorized');
  }
  return await res.json();
}

function switchTab(name, btn) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (name === 'lab') runBacktest();
}

let lastState = null;

function drawLineChart(canvasId, labels, seriesList) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  let allVals = [];
  seriesList.forEach(s => { allVals = allVals.concat(s.data.filter(v => Number.isFinite(v))); });
  if (allVals.length < 2) {
    ctx.fillStyle = '#94a3b8'; ctx.font = '12px sans-serif';
    ctx.fillText('データ蓄積中...', 20, h / 2);
    return;
  }
  let minV = Math.min(...allVals), maxV = Math.max(...allVals);
  if (maxV === minV) { maxV += 1; minV -= 1; }
  const padL = 48, padR = 14, padT = 18, padB = 22;
  const pw = w - padL - padR, ph = h - padT - padB;

  ctx.strokeStyle = '#1e293b'; ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = padT + (ph * i / 3);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    const val = maxV - ((maxV - minV) * i / 3);
    ctx.fillStyle = '#64748b'; ctx.font = '10px sans-serif';
    ctx.fillText(Math.abs(val) >= 100 ? Math.round(val).toLocaleString() : val.toFixed(2), 4, y + 3);
  }

  seriesList.forEach((s, idx) => {
    const d = s.data;
    if (d.length < 2) return;
    ctx.strokeStyle = s.color; ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < d.length; i++) {
      const x = padL + (pw * i / (d.length - 1));
      const y = padT + ph - ((d[i] - minV) / (maxV - minV)) * ph;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.fillStyle = s.color; ctx.font = 'bold 11px sans-serif';
    ctx.fillText(s.label, padL + idx * 140, 13);
  });
}

async function refreshAll() {
  try {
    const st = await apiCall('/api/state');
    lastState = st;
    renderCockpit(st);
    renderShadowAndStudy(st);
    renderAnalytics(st);
    populateControls(st);
  } catch (e) {
    console.error(e);
  }
}

function renderCockpit(st) {
  const m = st.market || {};
  const mac = st.macro || {};
  const brk = st.broker || {};
  const td = st.today_metrics || {};
  const positions = st.open_positions || [];

  document.getElementById('kpi-symbol').textContent = brk.symbol || 'XAUUSD';
  document.getElementById('kpi-price').textContent = '$' + Number(m.current_ask || 0).toFixed(2);
  document.getElementById('kpi-mtf').textContent = `H1: ${m.h1_trend || '--'} / M15: ${m.m15_trend || '--'} (ATR: $${Number(m.atr_m5_dollars||0).toFixed(2)})`;

  document.getElementById('kpi-balance').textContent = '¥' + Math.round(brk.balance || 0).toLocaleString();
  document.getElementById('kpi-broker').textContent = `${brk.server || ''} #${brk.login || ''} [${brk.trade_mode || 'DEMO'}]`;

  const tpnl = Math.round(td.total_profit || 0);
  const elTpnl = document.getElementById('kpi-today-pnl');
  elTpnl.textContent = (tpnl >= 0 ? '¥+' : '¥') + tpnl.toLocaleString();
  elTpnl.className = 'kpi-val ' + (tpnl >= 0 ? 'text-bull' : 'text-bear');
  document.getElementById('kpi-today-stats').textContent = `${td.total_count||0}戦 ${td.true_wins||0}勝 ${td.true_losses||0}敗 ${td.be_count||0}BE (PF ${td.profit_factor||1.0})`;

  const openPnl = positions.reduce((a, p) => a + (p.profit_jpy || 0), 0);
  const elOpnl = document.getElementById('kpi-open-pnl');
  elOpnl.textContent = (openPnl >= 0 ? '¥+' : '¥') + Math.round(openPnl).toLocaleString();
  elOpnl.className = 'kpi-val ' + (openPnl >= 0 ? 'text-bull' : 'text-bear');
  document.getElementById('kpi-open-count').textContent = `保有: ${positions.length} / ${st.max_positions || 3} ポジション`;

  const src = mac.source || 'MT5_M1';
  const bSrc = document.getElementById('badge-source');
  bSrc.textContent = src === 'TV_WEBHOOK' ? '🟢 TV_WEBHOOK 主系直結' : '🟡 MT5_M1 自律稼働';
  bSrc.className = 'badge ' + (src === 'TV_WEBHOOK' ? 'bull' : 'gold');

  document.getElementById('badge-regime').textContent = '🎛️ ' + (st.active_regime || 'REGIME_NORMAL_FLOW').replace('REGIME_', '');
  document.getElementById('badge-spread').textContent = `Sp: ${m.spread_pips || '--'}p`;

  // メーター更新
  const dxyZ = Number(mac.dxy_z || 0);
  const yldZ = Number(mac.yield_z || 0);
  const bias = Number(mac.macro_bias_score || 0);
  document.getElementById('m-dxy-val').textContent = (dxyZ >= 0 ? '+' : '') + dxyZ.toFixed(2) + 'σ';
  document.getElementById('m-dxy-bar').style.width = Math.min(100, Math.max(5, 50 + dxyZ * 18)) + '%';
  document.getElementById('m-yield-val').textContent = (yldZ >= 0 ? '+' : '') + yldZ.toFixed(2) + 'σ';
  document.getElementById('m-yield-bar').style.width = Math.min(100, Math.max(5, 50 + yldZ * 18)) + '%';
  document.getElementById('m-oil-val').textContent = `Oil: ${Number(mac.oil_z||0).toFixed(2)}σ / Equity: ${Number(mac.equity_z||0).toFixed(2)}σ`;
  document.getElementById('m-bias-val').textContent = (bias >= 0 ? '+' : '') + bias.toFixed(2) + (bias >= 0.35 ? ' (BUY優勢)' : (bias <= -0.35 ? ' (SELL優勢)' : ' (中立)'));
  document.getElementById('m-bias-bar').style.width = Math.min(100, Math.max(5, 50 + bias * 48)) + '%';
  document.getElementById('m-bias-bar').style.background = bias >= 0 ? 'var(--bull)' : 'var(--bear)';

  // 3系統スロット描画
  const slotDefs = [
    {key: 'MACRO_MOMENTUM', title: '🚀 系統1：型A マクロモメンタム', desc: 'DXY+米金利 2市場急変 (FVG不要)'},
    {key: 'SMT_DIVERGENCE', title: '🎯 系統2：型B SMTダイバージェンス', desc: 'DXY×XAU 機関吸収検知 (FVG不要)'},
    {key: 'SMC', title: '🏛️ 系統3：SMC テクニカル', desc: 'フラクタルスイープ / FVG / EMA20'}
  ];
  const slotsBox = document.getElementById('live-slots');
  slotsBox.innerHTML = slotDefs.map(sd => {
    const pos = positions.find(p => p.engine === sd.key);
    if (!pos) {
      return `<div class="pos-slot">
        <div style="font-weight:700;font-size:13px;margin-bottom:4px;">${sd.title}</div>
        <div style="font-size:11px;color:var(--muted);margin-bottom:8px;">${sd.desc}</div>
        <span class="badge">⚪ シグナル待機・スキャン中</span>
      </div>`;
    }
    const isBuy = pos.action === 'BUY';
    const pColor = pos.profit_jpy >= 0 ? 'text-bull' : 'text-bear';
    return `<div class="pos-slot ${isBuy ? 'active-buy' : 'active-sell'}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <span style="font-weight:800;font-size:13px;">${sd.title}</span>
        <span class="badge ${isBuy ? 'bull' : 'bear'}">${pos.action} ${pos.volume} Lot</span>
      </div>
      <div style="font-size:18px;font-weight:800;" class="${pColor}">
        ${pos.profit_jpy >= 0 ? '¥+' : '¥'}${pos.profit_jpy.toLocaleString()} <span style="font-size:12px;">(${pos.pips >= 0 ? '+' : ''}${pos.pips} pips)</span>
      </div>
      <div style="font-size:11px;color:var(--muted);margin:6px 0;">
        約定: $${pos.price_open} → 現在: $${pos.price_current}<br>
        SL: $${pos.sl} / TP: $${pos.tp} ${pos.is_be_locked ? '｜ <strong class="text-bull">🛡️建値ロック済</strong>' : ''}
      </div>
      <button class="btn btn-sm btn-bear btn-block" onclick="posAction('close_ticket', ${pos.ticket})">✖ このポジション (#${pos.ticket}) を決済</button>
    </div>`;
  }).join('');

  // M1ライブチャート
  const m1Series = st.m1_series || [];
  if (m1Series.length > 1) {
    drawLineChart('chart-live-m1', m1Series.map(r => r.time_str.slice(11,16)), [
      {label: 'XAUUSD 価格 ($)', color: '#f59e0b', data: m1Series.map(r => Number(r.xau_close))}
    ]);
  }
}

function renderShadowAndStudy(st) {
  const sc = st.shadow_scorecard || {};
  const byR = sc.by_reason || {};
  const keys = Object.keys(byR);
  const box = document.getElementById('shadow-scorecard');
  if (keys.length === 0) {
    box.innerHTML = `<div style="font-size:12px;color:var(--muted);">まだ見送りシグナルの採点データがありません。今後ガードやクールダウンが見送ったシグナルが自動的にここへ記録・採点されます。</div>`;
  } else {
    box.innerHTML = `<div class="grid-3">` + keys.map(k => {
      const d = byR[k];
      const acc = d.accuracy_pct !== null ? `${d.accuracy_pct}%` : '採点中';
      return `<div class="pos-slot">
        <div style="font-weight:700;font-size:12px;">🛡️ ${k}</div>
        <div style="font-size:16px;font-weight:800;margin:4px 0;">防御正解率: <span class="text-gold">${acc}</span></div>
        <div style="font-size:11px;color:var(--muted);">発動:${d.total}回 (SL回避:${d.defense_win} / 機会損失:${d.missed_tp} / 追跡中:${d.pending})<br>推定回避損失: <strong class="text-bull">¥+${Math.round(d.net_saved_jpy).toLocaleString()}</strong></div>
      </div>`;
    }).join('') + `</div>`;
  }

  const recentSh = sc.recent_shadows || [];
  document.getElementById('shadow-tbody').innerHTML = recentSh.map(r => {
    let badge = `<span class="badge">⏳ 追跡中</span>`;
    if (r.status === 'WOULD_LOSE_SL') badge = `<span class="badge bull">✅ 防御成功 (SL回避 +¥${Math.round(r.saved_jpy_est).toLocaleString()})</span>`;
    if (r.status === 'WOULD_WIN_TP') badge = `<span class="badge bear">⚠️ 機会損失 (TP到達)</span>`;
    return `<tr>
      <td>${(r.time_str||'').slice(5,16)}</td>
      <td>${r.entry_engine}</td>
      <td><strong>${r.action}</strong></td>
      <td>${r.block_reason}</td>
      <td>$${Number(r.entry_price).toFixed(1)} / SL:$${Number(r.sl_price).toFixed(1)} / TP:$${Number(r.tp_price).toFixed(1)}</td>
      <td>${badge}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="6" style="color:var(--muted);">記録待ち...</td></tr>`;

  // 週末研究室データ
  const ws = st.weekend_study || {};
  const corrs = ws.correlations_15m || {};
  const wts = ws.recommended_weights || {};
  const ll = (ws.lead_lag_profile || {}).horizon_breakdown || {};
  document.getElementById('weekend-study-box').innerHTML = `
    <div style="margin-bottom:6px;"><strong>最新15分相関 (対XAUUSD):</strong> ${Object.entries(corrs).map(([k,v]) => `<span class="badge">${k}: ${v >= 0 ? '+' : ''}${v}</span>`).join(' ')}</div>
    <div style="margin-bottom:6px;"><strong>自動適用バイアス重み:</strong> ドル指数(DXY) = <strong class="text-gold">${wts.dxy_weight || 0.7}</strong> ／ 米金利(US10Y/USDJPY) = <strong class="text-gold">${wts.yield_weight || 0.3}</strong></div>
    <div><strong>M1リードラグ（ショック後の順行勝率）:</strong> ${Object.entries(ll).map(([k,v]) => `<span class="badge violet">${k.replace('t_plus_','+')}: 勝率${v.directional_hit_rate_pct}% (${v.avg_favorable_pips>=0?'+':''}${v.avg_favorable_pips}p)</span>`).join(' ')}</div>
  `;
}

function renderAnalytics(st) {
  const wm = st.weekly_metrics || {};
  const engs = wm.engines || {};
  const sess = wm.sessions || {};
  const trades = st.recent_trades || [];

  document.getElementById('engine-perf-grid').innerHTML = Object.entries(engs).map(([k, e]) => {
    const pnl = Math.round(e.pnl || 0);
    return `<div class="pos-slot">
      <div style="font-weight:700;">${e.label || k}</div>
      <div class="kpi-val ${pnl >= 0 ? 'text-bull' : 'text-bear'}">${pnl >= 0 ? '¥+' : '¥'}${pnl.toLocaleString()}</div>
      <div style="font-size:11px;color:var(--muted);">${e.wins}勝 ${e.losses}敗 ${e.be}建値撤退 (直近7日)</div>
    </div>`;
  }).join('');

  document.getElementById('session-perf-bar').innerHTML = `<strong>時間帯別 (直近7日):</strong> ` + Object.entries(sess).map(([k, s]) => {
    const pnl = Math.round(s.pnl || 0);
    return `<span class="badge">${s.label}: ${s.wins}勝${s.losses}敗 (¥${pnl>=0?'+':''}${pnl.toLocaleString()})</span>`;
  }).join(' ');

  // 資産推移チャート
  let cum = 0;
  const eqCurve = [0];
  const closedAsc = [...trades].reverse().filter(t => t.profit !== null);
  closedAsc.forEach(t => { cum += Number(t.profit || 0); eqCurve.push(cum); });
  drawLineChart('chart-equity', eqCurve.map((_,i)=>String(i)), [
    {label: '累計確定損益 (JPY)', color: '#10b981', data: eqCurve}
  ]);

  document.getElementById('trades-tbody').innerHTML = trades.slice(0, 25).map(t => {
    const p = t.profit !== null ? Math.round(Number(t.profit)) : null;
    const pTxt = p === null ? '<span class="badge gold">OPEN</span>' : `<strong class="${p >= 0 ? 'text-bull' : 'text-bear'}">${p >= 0 ? '¥+' : '¥'}${p.toLocaleString()}</strong>`;
    return `<tr>
      <td>${(t.time||'').slice(5,16)}</td>
      <td><span class="badge">${t.entry_engine || 'SMC'}</span></td>
      <td><strong>${t.action}</strong> (${t.volume}L)</td>
      <td>${t.setup_name || ''}</td>
      <td>$${Number(t.price||0).toFixed(1)} → ${t.close_price ? '$'+Number(t.close_price).toFixed(1) : '--'}</td>
      <td>${pTxt}</td>
    </tr>`;
  }).join('');
}

let controlsInitialized = false;
function populateControls(st) {
  const c = st.control_config || {};
  const brk = st.broker || {};

  document.querySelectorAll('.stance-btn').forEach(b => b.classList.remove('active'));
  const activeSt = document.getElementById('st-' + (c.stance || 'BALANCED'));
  if (activeSt) activeSt.classList.add('active');

  if (controlsInitialized) return;
  controlsInitialized = true;

  document.getElementById('cfg-en-a').checked = c.enable_type_a !== false;
  document.getElementById('cfg-en-b').checked = c.enable_type_b !== false;
  document.getElementById('cfg-en-smc').checked = c.enable_smc !== false;
  document.getElementById('cfg-sess-asia').checked = c.session_asia !== false;
  document.getElementById('cfg-sess-lon').checked = c.session_london !== false;
  document.getElementById('cfg-sess-ny').checked = c.session_ny !== false;

  document.getElementById('cfg-max-pos').value = String(c.max_concurrent_positions || 3);
  document.getElementById('cfg-risk-pct').value = c.risk_per_trade_percent || 1.5;
  document.getElementById('cfg-dd-pct').value = c.max_daily_drawdown_percent || 3.0;
  document.getElementById('cfg-max-lot').value = c.max_lot_size || 0.50;
  document.getElementById('cfg-max-sp').value = c.max_allowed_spread_pips || 3.0;
  document.getElementById('cfg-sl-cool').value = c.sl_cooldown_minutes || 15;
  document.getElementById('cfg-owner-dir').value = c.owner_directive_ja || '';
  document.getElementById('cfg-notif-hourly').checked = c.notify_hourly !== false;
  document.getElementById('cfg-notif-weekend').checked = c.notify_weekend !== false;
  document.getElementById('cfg-daily-hour').value = String(c.daily_report_hour_jst || 6);

  document.getElementById('brk-login').value = brk.login || '';
  document.getElementById('brk-server').value = brk.server || '';
  document.getElementById('brk-symbol').value = brk.symbol || 'XAUUSD';
}

function updateSimLabels() {
  document.getElementById('lbl-sim-z').textContent = Number(document.getElementById('sim-z').value).toFixed(2);
  document.getElementById('lbl-sim-mrr').textContent = Number(document.getElementById('sim-mrr').value).toFixed(2);
  document.getElementById('lbl-sim-srr').textContent = Number(document.getElementById('sim-srr').value).toFixed(2);
  document.getElementById('lbl-sim-atr').textContent = Number(document.getElementById('sim-atr').value).toFixed(2);
  document.getElementById('lbl-sim-pos').textContent = document.getElementById('sim-pos').value;
}

async function runBacktest() {
  try {
    const payload = {
      z_thresh: Number(document.getElementById('sim-z').value),
      macro_rr: Number(document.getElementById('sim-mrr').value),
      smc_rr: Number(document.getElementById('sim-srr').value),
      atr_sl_mult: Number(document.getElementById('sim-atr').value),
      max_pos: Number(document.getElementById('sim-pos').value),
      days: 14
    };
    const res = await apiCall('/api/lab/backtest', 'POST', payload);
    const b = res.baseline || {}, s = res.simulated || {};
    const diff = s.diff_jpy || 0;
    document.getElementById('sim-summary').innerHTML = `
      <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;background:var(--card-alt);padding:8px;border-radius:8px;">
        <span>現行: <strong>¥${(b.net_pnl_jpy||0).toLocaleString()}</strong> (勝率${b.win_rate_pct}% / PF ${b.profit_factor})</span>
        <span>変更後: <strong class="${diff>=0?'text-bull':'text-bear'}">¥${(s.net_pnl_jpy||0).toLocaleString()} (${diff>=0?'+':''}¥${diff.toLocaleString()})</strong> (勝率${s.win_rate_pct}% / PF ${s.profit_factor})</span>
      </div>`;
    drawLineChart('chart-backtest', res.labels || [], [
      {label: '現行設定 (JPY)', color: '#94a3b8', data: b.curve || []},
      {label: '変更後シミュレート (JPY)', color: '#10b981', data: s.curve || []}
    ]);
  } catch (e) { console.error(e); }
}

async function applySimParamsToLive() {
  const payload = {
    momentum_z_threshold: Number(document.getElementById('sim-z').value),
    macro_min_rr: Number(document.getElementById('sim-mrr').value),
    min_risk_reward_ratio: Number(document.getElementById('sim-srr').value),
    atr_sl_multiplier: Number(document.getElementById('sim-atr').value),
    max_concurrent_positions: Number(document.getElementById('sim-pos').value),
  };
  const r = await apiCall('/api/control/params', 'POST', payload);
  showToast(r.message || 'シミュレーション設定を本番BOTへ適用しました！');
  refreshAll();
}

async function setStance(stance) {
  const r = await apiCall('/api/control/stance', 'POST', {stance});
  controlsInitialized = false;
  showToast(r.message || `スタンスを ${stance} に切り替えました`);
  refreshAll();
}

async function saveControlConfig() {
  const payload = {
    enable_type_a: document.getElementById('cfg-en-a').checked,
    enable_type_b: document.getElementById('cfg-en-b').checked,
    enable_smc: document.getElementById('cfg-en-smc').checked,
    session_asia: document.getElementById('cfg-sess-asia').checked,
    session_london: document.getElementById('cfg-sess-lon').checked,
    session_ny: document.getElementById('cfg-sess-ny').checked,
    max_concurrent_positions: Number(document.getElementById('cfg-max-pos').value),
    risk_per_trade_percent: Number(document.getElementById('cfg-risk-pct').value),
    max_daily_drawdown_percent: Number(document.getElementById('cfg-dd-pct').value),
    max_lot_size: Number(document.getElementById('cfg-max-lot').value),
    max_allowed_spread_pips: Number(document.getElementById('cfg-max-sp').value),
    sl_cooldown_minutes: Number(document.getElementById('cfg-sl-cool').value),
    owner_directive_ja: document.getElementById('cfg-owner-dir').value,
    notify_hourly: document.getElementById('cfg-notif-hourly').checked,
    notify_weekend: document.getElementById('cfg-notif-weekend').checked,
    daily_report_hour_jst: Number(document.getElementById('cfg-daily-hour').value),
  };
  const r = await apiCall('/api/control/params', 'POST', payload);
  showToast(r.message || '設定と改修方針を保存しました（15秒以内に即反映）');
  refreshAll();
}

async function posAction(action, ticket=null) {
  if (action === 'close_all' && !confirm('保有中の全ポジションを今すぐ成行決済しますか？')) return;
  const r = await apiCall('/api/control/position', 'POST', {action, ticket});
  showToast(r.message || 'ポジション操作を実行しました', !r.success);
  refreshAll();
}

async function switchBrokerAccount() {
  const login = Number(document.getElementById('brk-login').value);
  const server = document.getElementById('brk-server').value.trim();
  const password = document.getElementById('brk-pass').value;
  const symbol = document.getElementById('brk-symbol').value.trim();
  if (!login || !server || !password) {
    showToast('MT5口座を切り替えるにはログイン番号・サーバー名・パスワードを入力してください', true);
    return;
  }
  showToast('MT5口座へ接続テスト＆シンボル自動検出中...');
  const r = await apiCall('/api/control/broker', 'POST', {login, server, password, symbol});
  if (r.success) {
    showToast(`口座 #${r.login} (${r.server}) へ切替完了！ 銘柄: ${r.active_symbol}`);
    document.getElementById('brk-pass').value = '';
    if (r.detected_symbols) {
      document.getElementById('brk-detected-info').textContent = '自動検出シンボル: ' + JSON.stringify(r.detected_symbols);
    }
    refreshAll();
  } else {
    showToast(r.error || '口座切替に失敗しました', true);
  }
}

async function triggerLabTask(task) {
  showToast('リクエストを実行中...');
  const r = await apiCall('/api/lab/trigger', 'POST', {task});
  showToast(r.message || '実行完了しました！');
  refreshAll();
}

refreshAll();
setInterval(refreshAll, 10000);
</script>
</body>
</html>"""
