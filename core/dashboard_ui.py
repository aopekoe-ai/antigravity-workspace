def get_dashboard_html() -> str:
    """
    スマホ＆PC完全対応・ダークモード5タブクオンツ運用ダッシュボード (v9.3)
    - 注文操作・口座残高・含み損益を排除し、「どのロジックがどのポジション（売買・Lot・価格・SL/TP）を持っているか」に特化
    - 先行指標メーターを「何が・どのくらい・どのロジックにどう影響しているか」が直感的にわかる因果関係パネルへ刷新
    - 日々の自己最適化と動的ATRがリアルタイム反映される「📘 ロジック仕様書（生きた設計書＆変更履歴）」タブを新設
    """
    return r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>XAU/USD AI Quant Hedge Fund v9.3 Cockpit</title>
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
    line-height: 1.5;
    padding-bottom: 80px;
    font-variant-numeric: tabular-nums;
  }
  .topbar {
    position: sticky; top: 0; z-index: 40;
    background: rgba(11, 15, 23, 0.94);
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
  .badge.bull { background: rgba(16,185,129,0.15); border-color: rgba(16,185,129,0.45); color: #34d399; }
  .badge.bear { background: rgba(244,63,94,0.15); border-color: rgba(244,63,94,0.45); color: #fb7185; }
  .badge.gold { background: rgba(245,158,11,0.15); border-color: rgba(245,158,11,0.45); color: #fbbf24; }
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
    padding: 14px;
    margin-bottom: 12px;
  }
  .card-title {
    font-size: 13px; font-weight: 700; color: var(--muted);
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px;
    margin-bottom: 10px;
  }
  .kpi-val { font-size: 19px; font-weight: 800; margin-top: 2px; }
  .kpi-sub { font-size: 11px; color: var(--muted); margin-top: 3px; }
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
  .btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 6px; }
  .btn-block { width: 100%; }

  .pos-slot {
    background: var(--card-alt); border: 1px solid var(--border); border-radius: 10px; padding: 12px;
  }
  .pos-slot.active-buy { border-color: rgba(16,185,129,0.6); background: rgba(16,185,129,0.07); }
  .pos-slot.active-sell { border-color: rgba(244,63,94,0.6); background: rgba(244,63,94,0.07); }

  /* 双方向（センターゼロ）インパクトゲージ */
  .impact-card {
    background: var(--card-alt); border: 1px solid var(--border); border-radius: 10px;
    padding: 11px; margin-bottom: 10px;
  }
  .bipolar-track {
    position: relative; height: 10px; background: #0b0f17; border-radius: 99px;
    border: 1px solid var(--border); overflow: hidden; margin: 6px 0;
  }
  .bipolar-center {
    position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; background: #475569; z-index: 2;
  }
  .bipolar-fill {
    position: absolute; top: 0; bottom: 0; transition: all 0.3s ease;
  }
  .impact-explain {
    font-size: 12px; padding: 8px 10px; border-radius: 8px;
    background: rgba(15, 23, 42, 0.75); border-left: 3px solid var(--gold); margin-top: 6px;
  }

  /* ロジック仕様書カード */
  .spec-box {
    background: var(--card-alt); border: 1px solid var(--border); border-radius: 10px;
    padding: 13px; margin-bottom: 12px;
  }
  .spec-header {
    font-size: 15px; font-weight: 800; margin-bottom: 8px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px;
  }
  .spec-list { list-style: none; font-size: 13px; }
  .spec-list li {
    padding: 6px 0; border-bottom: 1px dashed rgba(51,65,85,0.6);
  }
  .spec-list li:last-child { border-bottom: none; }
  .live-val {
    display: inline-block; padding: 1px 7px; border-radius: 5px;
    background: rgba(245,158,11,0.18); border: 1px solid rgba(245,158,11,0.45);
    color: #fbbf24; font-weight: 800; font-size: 12px;
  }

  .tab-pane { display: none; }
  .tab-pane.active { display: block; }

  .bottom-nav {
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 50;
    background: rgba(15, 21, 33, 0.97); backdrop-filter: blur(10px);
    border-top: 1px solid var(--border);
    display: grid; grid-template-columns: repeat(5, 1fr);
    padding: 6px 2px;
  }
  .nav-btn {
    background: none; border: none; color: var(--muted);
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    font-size: 10px; font-weight: 700; padding: 6px 2px; cursor: pointer; border-radius: 8px;
  }
  .nav-btn.active { color: var(--gold); background: rgba(245,158,11,0.12); }
  .nav-icon { font-size: 16px; }

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

  /* 誤操作防止ロック ＆ はい/いいえ確認モーダル */
  .lock-banner {
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;
    padding: 11px 14px; border-radius: 12px; margin-bottom: 12px;
    background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.45);
  }
  .lock-banner.unlocked {
    background: rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.5);
  }
  .locked-zone {
    opacity: 0.55; pointer-events: none; user-select: none; filter: grayscale(0.25);
    transition: opacity 0.2s ease;
  }
  .locked-zone.unlocked {
    opacity: 1.0; pointer-events: auto; user-select: auto; filter: none;
  }
  .modal-backdrop {
    position: fixed; inset: 0; z-index: 200;
    background: rgba(5, 8, 15, 0.82); backdrop-filter: blur(6px);
    display: none; align-items: center; justify-content: center; padding: 16px;
  }
  .modal-backdrop.open { display: flex; }
  .modal-box {
    width: 100%; max-width: 420px; background: var(--card);
    border: 1px solid var(--gold); border-radius: 14px; padding: 18px;
    box-shadow: 0 20px 50px rgba(0,0,0,0.75);
  }
  .modal-title { font-size: 16px; font-weight: 800; color: var(--gold); margin-bottom: 8px; }
  .modal-desc {
    font-size: 13px; color: var(--text); background: var(--card-alt);
    border: 1px solid var(--border); border-radius: 8px; padding: 11px;
    margin-bottom: 16px; white-space: pre-line; line-height: 1.55;
  }
  .modal-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

  /* 編集モード時のスマホ画面追従フローティング保存バー */
  .sticky-save-bar {
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 150;
    background: rgba(11, 15, 23, 0.95); backdrop-filter: blur(10px);
    border-top: 2px solid var(--gold); padding: 12px 16px;
    display: none; align-items: center; justify-content: space-between;
    box-shadow: 0 -8px 25px rgba(0,0,0,0.6);
  }
  .sticky-save-bar.show { display: flex; }
</style>
</head>
<body>

<div id="toast"></div>

<!-- はい / いいえ 確認ポップアップモーダル -->
<div id="confirm-modal" class="modal-backdrop" onclick="if(event.target===this)closeConfirmModal()">
  <div class="modal-box">
    <div id="confirm-title" class="modal-title">⚠️ 設定変更の確認</div>
    <div id="confirm-desc" class="modal-desc">この変更を適用してもよろしいですか？</div>
    <div class="modal-actions">
      <button class="btn" onclick="closeConfirmModal()">✖ いいえ (キャンセル)</button>
      <button id="confirm-yes-btn" class="btn btn-gold">✔ はい (実行する)</button>
    </div>
  </div>
</div>

<header class="topbar">
  <div class="brand">⚡ XAU/USD Quant Cockpit <span style="font-size:11px;color:var(--muted);">v9.3</span></div>
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
    <span id="badge-source" class="badge">📡 読込中...</span>
    <span id="badge-regime" class="badge violet">🎛️ REGIME</span>
    <span id="badge-spread" class="badge">Sp: --</span>
    <button class="btn btn-sm" onclick="refreshAll()">🔄 更新</button>
  </div>
</header>

<main class="container">
  <!-- 共通ステータス・リボン（残高・含み損益を排除し、価格・トレンド・保有ロジック・マクロ結論に特化） -->
  <div class="grid-4">
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">💵 現在価格 (<span id="kpi-symbol">XAUUSD</span>)</div>
      <div id="kpi-price" class="kpi-val text-gold">$----.--</div>
      <div id="kpi-mtf" class="kpi-sub">H1: -- / M15: --</div>
    </div>
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">🎯 保有中ロジック ＆ ポジション数</div>
      <div id="kpi-open-count" class="kpi-val">0 / 3 ポジ</div>
      <div id="kpi-open-engines" class="kpi-sub">保有ロジック: なし</div>
    </div>
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">📡 先行指標の総合判定</div>
      <div id="kpi-macro-verdict" class="kpi-val">中立 (0.00)</div>
      <div id="kpi-macro-effect" class="kpi-sub">SMC倍率: 1.00x</div>
    </div>
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">🎛️ 動的相場レジーム ＆ 方針</div>
      <div id="kpi-regime-name" class="kpi-val" style="font-size:16px;">NORMAL_FLOW</div>
      <div id="kpi-stance-name" class="kpi-sub">スタンス: BALANCED</div>
    </div>
  </div>

  <!-- ==================== TAB 1: LIVE COCKPIT ==================== -->
  <section id="tab-live" class="tab-pane active">
    <!-- 1. どのロジックが今どのポジションをいくらで持っているか（読み取り専用・MT5操作方針準拠） -->
    <div class="card">
      <div class="card-title">
        <span>🎯 3系統ロジック別・現在保有ポジション状況（注文・決済操作はMT5アプリ専用）</span>
        <span id="htf-direction-badge" class="badge gold">上位足方向確認中</span>
      </div>
      <div id="live-slots" class="grid-3"></div>
    </div>

    <!-- 2. 何が・どのくらい・何のロジックに影響しているか一目でわかる先行指標パネル -->
    <div class="card">
      <div class="card-title">
        <span>📡 先行指標インパクト解剖（何が・どのくらい・どのロジックにどう影響しているか）</span>
        <span id="macro-source-detail" class="badge">データソース確認中</span>
      </div>

      <!-- 総合結論＆3ロジックへの具体的影響バナー -->
      <div id="macro-logic-effects" class="impact-explain" style="margin-bottom:12px;"></div>

      <div class="grid-3" id="macro-indicators-cards"></div>
    </div>

    <div class="card" style="margin-bottom:0;">
      <div class="card-title">📉 直近1分足ゴールド価格推移 (SQLite 時系列DB)</div>
      <canvas id="chart-live-m1" width="800" height="185"></canvas>
    </div>
  </section>

  <!-- ==================== TAB 2: LOGIC SPEC (生きたロジック仕様書) ==================== -->
  <section id="tab-spec" class="tab-pane">
    <div class="card">
      <div class="card-title">
        <span>📘 現行ロジック完全仕様書（日々のAI自己最適化 ＆ 動的ATRがリアルタイム反映された実効値）</span>
        <span id="spec-version-badge" class="badge gold">Dynamic v--</span>
      </div>
      <div id="spec-overview-banner" class="impact-explain" style="margin-bottom:12px;"></div>
      <div id="spec-engines-container"></div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>📅 日々のロジック変更・AI自己最適化履歴タイムライン</span>
        <span class="badge violet">自動記録ログ</span>
      </div>
      <div id="spec-history-list"></div>
    </div>
  </section>

  <!-- ==================== TAB 3: LAB (本格検証 & 日曜AI投資委員会) ==================== -->
  <section id="tab-lab" class="tab-pane">
    <div class="card" style="border:1px solid rgba(245,158,11,0.45);">
      <div class="card-title" style="flex-wrap:wrap;gap:8px;">
        <span>🏛️ 日曜AI投資委員会（6役エージェント激論・ファンダメンタルズ統合・次週検証＆中長期方針）</span>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <span id="ic-quota-badge" class="badge gold">AI Quota: 確認中</span>
          <button class="btn btn-sm btn-gold" onclick="confirmTriggerLabTask('sunday_ic_meeting')">🏛️ 今すぐ投資委員会を開催＆Discord決裁送信</button>
        </div>
      </div>
      <div id="ic-committee-box" style="font-size:12px;">
        <div style="color:var(--muted);padding:10px;">投資委員会データを読み込み中...（日曜 10:00 JST 自動開催、または上のボタンで今すぐ開催できます）</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>🎛️ 「もしも（What-If）」スライダー高速バックテスト（現行 vs 変更後シミュレーション）</span>
        <button class="btn btn-sm btn-gold" onclick="confirmApplySimParamsToLive()">✨ この検証設定を本番ロジックへ適用 (確認へ)</button>
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
        <button class="btn btn-sm btn-primary" onclick="confirmTriggerLabTask('weekend_study')">🔄 今すぐ再検証＆Discord送信</button>
      </div>
      <div id="weekend-study-box" style="font-size:12px;"></div>
    </div>
  </section>

  <!-- ==================== TAB 4: ANALYTICS (戦績) ==================== -->
  <section id="tab-analytics" class="tab-pane">
    <div class="card">
      <div class="card-title">📈 確定トレード損益推移（エクイティカーブ）</div>
      <canvas id="chart-equity" width="800" height="190"></canvas>
    </div>

    <div class="card">
      <div class="card-title">⚙️ 3系統エンジン別 ＆ 時間帯別（東京・ロンドン・NY）戦績比較</div>
      <div id="engine-perf-grid" class="grid-3"></div>
      <div id="session-perf-bar" style="margin-top:8px;font-size:12px;"></div>
    </div>

    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
        <div class="card-title" style="margin:0;">📜 トレード履歴（ロジック別 約定・決済）</div>
        <div id="trades-filter-info" style="font-size:12px;color:var(--muted);"></div>
      </div>
      <div style="overflow-x:auto;">
        <table>
          <thead><tr><th>日時</th><th>ロジック</th><th>売買/Lot</th><th>セットアップ名</th><th>約定価格 → 決済価格</th><th>SL / TP</th><th>状態/結果</th></tr></thead>
          <tbody id="trades-tbody"></tbody>
        </table>
      </div>
      <div style="text-align:center;margin-top:14px;">
        <button id="btn-load-more-trades" onclick="toggleTradeHistoryView()" class="btn" style="padding:8px 22px;font-size:12px;background:rgba(255,255,255,0.06);border:1px solid var(--border);color:var(--text);border-radius:6px;cursor:pointer;display:none;">
          ▼ さらに過去の履歴を読み込む
        </button>
      </div>
    </div>
  </section>

  <!-- ==================== TAB 5: CONTROL & BROKER ==================== -->
  <section id="tab-control" class="tab-pane">
    <!-- スマホ誤タップ防止ロックバー -->
    <div id="edit-lock-banner" class="lock-banner">
      <div>
        <div id="edit-lock-title" style="font-weight:800;font-size:13px;color:var(--gold);">🔒 誤操作防止ロック中（スクロール時に手が当たっても変更されません）</div>
        <div style="font-size:11px;color:var(--muted);">設定を変更する時だけ右のボタンでロックを解除してください（変更完了後は自動で再ロックされます）</div>
      </div>
      <button id="edit-lock-btn" class="btn btn-sm btn-gold" onclick="toggleEditLock()">🔓 ロックを解除して編集</button>
    </div>

    <div id="control-locked-zone" class="locked-zone">
    <div class="card">
      <div class="card-title">⚡ 運用スタンス（タップ後に「はい／いいえ」確認ポップアップが表示されます）</div>
      <div class="stance-grid">
        <button class="stance-btn" id="st-AGGRESSIVE" onclick="confirmSetStance('AGGRESSIVE')">🔥 積極トレンド追撃<br><span style="font-size:10px;color:var(--muted);">Z閾値1.35 / 最大3ポジ</span></button>
        <button class="stance-btn" id="st-BALANCED" onclick="confirmSetStance('BALANCED')">⚖️ 標準バランス<br><span style="font-size:10px;color:var(--muted);">Z閾値1.50 / 最大3ポジ</span></button>
        <button class="stance-btn" id="st-DEFENSIVE" onclick="confirmSetStance('DEFENSIVE')">🛡️ 厳選・資金防衛<br><span style="font-size:10px;color:var(--muted);">Z閾値1.70 / 最大1ポジ</span></button>
        <button class="stance-btn" id="st-PAUSED" onclick="confirmSetStance('PAUSED')">⏸️ 新規エントリー停止<br><span style="font-size:10px;color:var(--muted);">保有中ポジのみ保護</span></button>
      </div>
    </div>

    <div class="grid-2">
      <div class="card" style="margin-bottom:0;">
        <div class="card-title">🎛️ 3系統ロジックON/OFF ＆ リスク・フィルター詳細設定</div>
        <div class="toggle-row"><span>🚀 系統1：型A マクロモメンタム (FVG不要)</span><input type="checkbox" id="cfg-en-a" checked></div>
        <div class="toggle-row"><span>🎯 系統2：型B SMTダイバージェンス (FVG不要)</span><input type="checkbox" id="cfg-en-b" checked></div>
        <div class="toggle-row"><span>🏛️ 系統3：既存SMC 3トリガー (Fractal/FVG/EMA)</span><input type="checkbox" id="cfg-en-smc" checked></div>
        <div class="toggle-row"><span>🌏 東京セッション (08:00-15:00 JST) 取引許可</span><input type="checkbox" id="cfg-sess-asia" checked></div>
        <div class="toggle-row"><span>🇬🇧 ロンドンセッション (15:00-24:00 JST) 取引許可</span><input type="checkbox" id="cfg-sess-lon" checked></div>
        <div class="toggle-row"><span>🗽 NYセッション (21:00-06:00 JST) 取引許可</span><input type="checkbox" id="cfg-sess-ny" checked></div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;">
          <div class="form-group">
            <div class="form-label"><span>最大同時保有ポジ数</span></div>
            <select id="cfg-max-pos" class="form-select">
              <option value="1">1ポジ (単ポジ)</option>
              <option value="2">2ポジ</option>
              <option value="3" selected>3ポジ (3系統)</option>
              <option value="5">5ポジ</option>
              <option value="10">10ポジ</option>
              <option value="0">0: 設定しない (無制限)</option>
            </select>
          </div>
          <div class="form-group">
            <div class="form-label"><span>1トレードリスク (%)</span></div>
            <input type="number" id="cfg-risk-pct" class="form-input" step="0.1" min="0" value="1.5" placeholder="0で最小固定Lot">
          </div>
          <div class="form-group">
            <div class="form-label"><span>日次最大DD停止 (%) <span style="font-size:10px;color:var(--gold);">(0で無効)</span></span></div>
            <input type="number" id="cfg-dd-pct" class="form-input" step="0.5" min="0" value="3.0" placeholder="0で停止無効（上限なし）">
          </div>
          <div class="form-group">
            <div class="form-label"><span>最大ロット上限 (Lot) <span style="font-size:10px;color:var(--gold);">(0で無制限)</span></span></div>
            <input type="number" id="cfg-max-lot" class="form-input" step="0.05" min="0" value="0.50" placeholder="0で口座上限まで無制限">
          </div>
          <div class="form-group">
            <div class="form-label"><span>許容スプレッド (pips) <span style="font-size:10px;color:var(--gold);">(0で無制限)</span></span></div>
            <input type="number" id="cfg-max-sp" class="form-input" step="0.5" min="0" value="3.0" placeholder="0で制限なし（上限なし）">
          </div>
          <div class="form-group">
            <div class="form-label"><span>連敗防止待機 (分) <span style="font-size:10px;color:var(--gold);">(0で待機なし)</span></span></div>
            <input type="number" id="cfg-sl-cool" class="form-input" step="1" min="0" value="15" placeholder="0で待機なし">
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
          <div style="margin-top:10px;text-align:right;">
            <button class="btn btn-primary" style="white-space:nowrap;" onclick="confirmTriggerLabTask('daily_report')">📨 日次レポートを手動テスト送信</button>
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
          <button class="btn btn-primary btn-block" onclick="confirmSwitchBrokerAccount()">🔄 MT5口座を即時切替 ＆ シンボル自動検出</button>
        </div>
      </div>
    </div>

    <!-- 唯一の保存ボタン（最下部に配置） -->
    <div class="card" style="margin-top:16px;background:rgba(245,158,11,0.08);border:1px solid var(--gold);text-align:center;">
      <div style="font-size:13px;color:var(--text);margin-bottom:10px;">
        💡 変更した稼働ロジック・リスク・日次最大DD・スプレッド・AI方針をすべて本番BOTへ反映します
      </div>
      <button class="btn btn-gold btn-block" style="padding:15px;font-size:15px;font-weight:800;" onclick="confirmSaveControlConfig()">
        💾 設定を保存して本番へ反映する (確認へ)
      </button>
    </div>
    </div>
  </section>
</main>

<nav class="bottom-nav">
  <button class="nav-btn active" onclick="switchTab('live', this)"><span class="nav-icon">⚡</span><span>LIVE監視</span></button>
  <button class="nav-btn" onclick="switchTab('spec', this)"><span class="nav-icon">📘</span><span>ロジック仕様</span></button>
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
  const padL = 52, padR = 14, padT = 18, padB = 22;
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
    ctx.fillText(s.label, padL + idx * 145, 13);
  });
}

function bipolarBarHtml(val, maxAbs) {
  const clamped = Math.max(-maxAbs, Math.min(maxAbs, val));
  const pct = Math.abs(clamped) / maxAbs * 50;
  const left = clamped >= 0 ? 50 : (50 - pct);
  const color = clamped >= 0 ? 'var(--bull)' : 'var(--bear)';
  return `<div class="bipolar-track">
    <div class="bipolar-center"></div>
    <div class="bipolar-fill" style="left:${left}%;width:${pct}%;background:${color};"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);">
    <span>◀ ゴールド下落要因 (SELL)</span><span>中立 (0)</span><span>ゴールド上昇要因 (BUY) ▶</span>
  </div>`;
}

async function refreshAll() {
  try {
    const st = await apiCall('/api/state');
    window._lastFetchedState = st;
    renderCockpit(st);
    renderLogicSpec(st);
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
  const positions = st.open_positions || [];
  const spec = st.live_spec || {};
  const ctrl = st.control_config || {};

  const h1 = m.h1_trend || 'NEUTRAL';
  const m15 = m.m15_trend || 'NEUTRAL';
  document.getElementById('kpi-symbol').textContent = brk.symbol || 'XAUUSD';
  document.getElementById('kpi-price').textContent = '$' + Number(m.current_ask || 0).toFixed(2);
  document.getElementById('kpi-mtf').textContent = `H1: ${h1} / M15: ${m15} (M5 ATR: $${Number(m.atr_m5_dollars||0).toFixed(2)})`;

  // 保有中ロジックKPI
  document.getElementById('kpi-open-count').textContent = `${positions.length} / ${st.max_positions || 3} ポジ保有中`;
  const engShort = {'MACRO_MOMENTUM': '型A(急変)', 'SMT_DIVERGENCE': '型B(SMT)', 'SMC': '系統3(SMC)'};
  if (positions.length === 0) {
    document.getElementById('kpi-open-engines').textContent = '現在保有中のロジックはありません';
  } else {
    document.getElementById('kpi-open-engines').textContent = positions.map(p => `${engShort[p.engine]||p.engine}: ${p.action} ${p.volume}L @$${p.price_open}`).join(' / ');
  }

  // 先行指標総合KPI
  const bias = Number(mac.macro_bias_score || 0);
  const elMv = document.getElementById('kpi-macro-verdict');
  if (bias >= 0.35) {
    elMv.textContent = `BUY優勢 (${bias >= 0 ? '+' : ''}${bias.toFixed(2)})`;
    elMv.className = 'kpi-val text-bull';
  } else if (bias <= -0.35) {
    elMv.textContent = `SELL優勢 (${bias.toFixed(2)})`;
    elMv.className = 'kpi-val text-bear';
  } else {
    elMv.textContent = `中立 (${bias >= 0 ? '+' : ''}${bias.toFixed(2)})`;
    elMv.className = 'kpi-val';
  }
  let smcEffectTxt = 'SMCロット補正: 1.00x (通常)';
  if (bias >= 0.70) smcEffectTxt = 'BUY 1.25x増額 / SELL 完全ブロック';
  else if (bias >= 0.35) smcEffectTxt = 'BUY 1.25x増額 / SELL 0.75x減額';
  else if (bias <= -0.70) smcEffectTxt = 'SELL 1.25x増額 / BUY 完全ブロック';
  else if (bias <= -0.35) smcEffectTxt = 'SELL 1.25x増額 / BUY 0.75x減額';
  document.getElementById('kpi-macro-effect').textContent = smcEffectTxt;

  const regShort = (st.active_regime || 'REGIME_NORMAL_FLOW').replace('REGIME_', '');
  document.getElementById('kpi-regime-name').textContent = regShort;
  document.getElementById('kpi-stance-name').textContent = `スタンス: ${ctrl.stance || 'BALANCED'} (${brk.server || 'MT5'} #${brk.login || ''})`;

  const src = mac.source || 'MT5_M1';
  const bSrc = document.getElementById('badge-source');
  bSrc.textContent = src === 'TV_WEBHOOK' ? '🟢 TV_WEBHOOK 主系直結' : '🟡 MT5_M1 副系稼働';
  bSrc.className = 'badge ' + (src === 'TV_WEBHOOK' ? 'bull' : 'gold');
  document.getElementById('badge-regime').textContent = '🎛️ ' + regShort;
  document.getElementById('badge-spread').textContent = `Sp: ${m.spread_pips || '--'}p`;

  // 上位足トレンド方向バッジ
  const htfBadge = document.getElementById('htf-direction-badge');
  if (h1 === 'BULLISH') {
    htfBadge.textContent = '📈 H1上昇トレンド：全ロジック BUY（買い）のみ許可';
    htfBadge.className = 'badge bull';
  } else if (h1 === 'BEARISH') {
    htfBadge.textContent = '📉 H1下降トレンド：全ロジック SELL（売り）のみ許可';
    htfBadge.className = 'badge bear';
  } else {
    htfBadge.textContent = '⚖️ H1中立レンジ：全ロジック BUY / SELL 双方向許可';
    htfBadge.className = 'badge gold';
  }

  // 3系統エンジンの保有ポジションカード（残高・含み損益・決済ボタン無し、どのロジックがいくら持っているか明示）
  const slotDefs = [
    {key: 'MACRO_MOMENTUM', title: '🚀 系統1：型A マクロモメンタム', desc: 'DXY＋米金利の2市場同時急変で発火（FVG不要）', en: ctrl.enable_type_a !== false},
    {key: 'SMT_DIVERGENCE', title: '🎯 系統2：型B SMTダイバージェンス', desc: 'DXY高安更新×ゴールド不追随の機関吸収で発火（FVG不要）', en: ctrl.enable_type_b !== false},
    {key: 'SMC', title: '🏛️ 系統3：SMC テクニカル', desc: 'M5フラクタルスイープ / ICT FVGリテスト / EMA20反発', en: ctrl.enable_smc !== false}
  ];
  document.getElementById('live-slots').innerHTML = slotDefs.map(sd => {
    const pos = positions.find(p => p.engine === sd.key);
    if (!pos) {
      return `<div class="pos-slot">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="font-weight:800;font-size:13px;">${sd.title}</span>
          <span class="badge">${sd.en ? '⚪ ポジションなし (監視中)' : '⛔ OFF'}</span>
        </div>
        <div style="font-size:11px;color:var(--muted);">${sd.desc}</div>
      </div>`;
    }
    const isBuy = pos.action === 'BUY';
    const slPips = Math.abs(pos.price_open - pos.sl) / 0.10;
    const tpPips = Math.abs(pos.tp - pos.price_open) / 0.10;
    return `<div class="pos-slot ${isBuy ? 'active-buy' : 'active-sell'}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-weight:800;font-size:13px;">${sd.title}</span>
        <span class="badge ${isBuy ? 'bull' : 'bear'}">${isBuy ? '🟢 BUY 保有中' : '🔴 SELL 保有中'}</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;background:rgba(11,15,23,0.65);padding:8px;border-radius:8px;font-size:12px;">
        <div><span style="color:var(--muted);font-size:11px;">保有ロット数</span><br><strong style="font-size:16px;">${pos.volume} Lot</strong></div>
        <div><span style="color:var(--muted);font-size:11px;">エントリー約定価格</span><br><strong style="font-size:16px;color:var(--gold);">$${pos.price_open.toFixed(2)}</strong></div>
        <div><span style="color:var(--muted);font-size:11px;">ハードSL (損切値)</span><br><strong>$${pos.sl.toFixed(2)}</strong> <span style="font-size:10px;color:var(--muted);">(${slPips.toFixed(0)}p)</span></div>
        <div><span style="color:var(--muted);font-size:11px;">ターゲットTP (利確値)</span><br><strong>$${pos.tp.toFixed(2)}</strong> <span style="font-size:10px;color:var(--muted);">(${tpPips.toFixed(0)}p)</span></div>
      </div>
      <div style="margin-top:7px;display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--muted);">
        <span>注文番号: #${pos.ticket} (${pos.symbol})</span>
        <span>${pos.is_be_locked ? '<strong class="text-bull">🛡️ 建値ロック完了済 (負けなし)</strong>' : '⏳ 建値移動待機中 (RR 1:1で発動)'}</span>
      </div>
    </div>`;
  }).join('');

  // 先行指標の「何が・どのくらい・何に影響しているか」パネル
  const dxyZ = Number(mac.dxy_z || 0);
  const yldZ = Number(mac.yield_z || 0);
  const oilZ = Number(mac.oil_z || 0);
  const eqZ = Number(mac.equity_z || 0);
  const geoOff = Boolean(mac.is_geopolitical_risk_off);
  const zTh = Number(spec.effective_momentum_z_threshold || 1.50);
  const wDxy = Number(spec.dxy_weight || 0.70);
  const wYld = Number(spec.yield_weight || 0.30);

  document.getElementById('macro-source-detail').textContent =
    src === 'TV_WEBHOOK' ? `主系 TradingView (TVC:DXY + TVC:US10Y) ｜ 重み DXY:${Math.round(wDxy*100)}% / 金利:${Math.round(wYld*100)}%`
                         : `副系 Exness MT5 M1 (DXY + USDJPY金利代替) ｜ 重み DXY:${Math.round(wDxy*100)}% / 金利:${Math.round(wYld*100)}%`;

  // 各ロジックへの現在の具体的影響説明
  const sameDirBear = (dxyZ < 0 && yldZ < 0);
  const sameDirBull = (dxyZ > 0 && yldZ > 0);
  let typeAStatus = '';
  if (mac.momentum_signal) {
    typeAStatus = `<strong class="text-gold">🔥 現在【${mac.momentum_signal}】発火条件クリア！</strong> (${mac.momentum_detail || ''})`;
  } else if (sameDirBear) {
    const needD = Math.max(0, zTh - Math.abs(dxyZ)).toFixed(2);
    const needY = Math.max(0, zTh*0.72 - Math.abs(yldZ)).toFixed(2);
    typeAStatus = `ドル・金利とも下落方向（ゴールドBUY向き）。発火閾値(|Z|≥${zTh.toFixed(2)}σ)まで <strong>DXYあと ${needD}σ / 金利あと ${needY}σ</strong>`;
  } else if (sameDirBull) {
    const needD = Math.max(0, zTh - Math.abs(dxyZ)).toFixed(2);
    const needY = Math.max(0, zTh*0.72 - Math.abs(yldZ)).toFixed(2);
    typeAStatus = `ドル・金利とも上昇方向（ゴールドSELL向き）。発火閾値(|Z|≥${zTh.toFixed(2)}σ)まで <strong>DXYあと ${needD}σ / 金利あと ${needY}σ</strong>`;
  } else {
    typeAStatus = `現在 DXY(${dxyZ>=0?'+':''}${dxyZ.toFixed(2)}σ) と 金利(${yldZ>=0?'+':''}${yldZ.toFixed(2)}σ) の方向が不一致（ねじれ）のため、<strong>型Aの飛び乗り発火を自動ロック中</strong>`;
  }

  let typeBStatus = mac.smt_signal
    ? `<strong class="text-gold">🎯 現在【${mac.smt_signal}】SMTダイバージェンス検知！</strong> (${mac.smt_detail})`
    : `直近35分間のDXY高安更新に対するゴールドの不追随（機関吸収）を監視中（現在異常ズレなし）`;

  document.getElementById('macro-logic-effects').innerHTML = `
    <div style="font-weight:800;margin-bottom:4px;color:var(--gold);">💡 現在の先行指標が各ロジックに与えている影響まとめ</div>
    <div>・<strong>🚀 型A (マクロ急変) への影響:</strong> ${typeAStatus}</div>
    <div>・<strong>🎯 型B (SMT吸収) への影響:</strong> ${typeBStatus}</div>
    <div>・<strong>🏛️ 系統3 (SMC) への影響:</strong> 統合バイアス <strong>${bias>=0?'+':''}${bias.toFixed(2)}</strong> に基づき、<strong>${smcEffectTxt}</strong>（閾値: ±0.35でロット増減、±0.70で逆行ブロック）</div>
  `;

  // 3枚の個別指標因果カード（逆相関のため -Z がゴールド上昇要因）
  const dxyGoldEffect = -dxyZ;
  const yldGoldEffect = -yldZ;
  const dxyContrib = (-wDxy * dxyZ / 2.0);
  const yldContrib = (-wYld * yldZ / 2.0);

  document.getElementById('macro-indicators-cards').innerHTML = `
    <div class="impact-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong>💵 ① ドル指数 (DXY)</strong>
        <span class="badge gold">影響ウェイト: ${Math.round(wDxy*100)}%</span>
      </div>
      <div style="font-size:12px;color:var(--muted);margin-top:3px;">
        現在値: <strong>Z = ${dxyZ>=0?'+':''}${dxyZ.toFixed(2)}σ</strong> (${dxyZ > 0.3 ? 'ドル買い進行' : (dxyZ < -0.3 ? 'ドル売り進行' : '横ばい')})
      </div>
      ${bipolarBarHtml(dxyGoldEffect, 3.0)}
      <div style="font-size:11px;margin-top:6px;">
        ・<strong>ゴールドへの作用:</strong> <strong class="${dxyGoldEffect>=0?'text-bull':'text-bear'}">${dxyGoldEffect>=0?'▲ 上昇追い風 (BUY要因)':'▼ 下落圧力 (SELL要因)'}</strong> (バイアス寄与: ${dxyContrib>=0?'+':''}${dxyContrib.toFixed(2)})<br>
        ・<strong>型A発火基準 (|Z|≥${zTh.toFixed(2)}σ):</strong> ${Math.abs(dxyZ)>=zTh ? '<strong class="text-bull">✅ 基準クリア</strong>' : `未達 (現在 ${Math.abs(dxyZ).toFixed(2)}σ / 基準の ${Math.min(100, Math.round(Math.abs(dxyZ)/zTh*100))}%)`}
      </div>
    </div>

    <div class="impact-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong>🏛️ ② 米金利 (${src==='TV_WEBHOOK'?'US10Y/02Y':'USDJPY代替'})</strong>
        <span class="badge gold">影響ウェイト: ${Math.round(wYld*100)}%</span>
      </div>
      <div style="font-size:12px;color:var(--muted);margin-top:3px;">
        現在値: <strong>Z = ${yldZ>=0?'+':''}${yldZ.toFixed(2)}σ</strong> (${yldZ > 0.3 ? '金利上昇' : (yldZ < -0.3 ? '金利低下' : '横ばい')})
      </div>
      ${bipolarBarHtml(yldGoldEffect, 3.0)}
      <div style="font-size:11px;margin-top:6px;">
        ・<strong>ゴールドへの作用:</strong> <strong class="${yldGoldEffect>=0?'text-bull':'text-bear'}">${yldGoldEffect>=0?'▲ 金利低下でBUY追い風':'▼ 金利上昇でSELL圧力'}</strong> (バイアス寄与: ${yldContrib>=0?'+':''}${yldContrib.toFixed(2)})<br>
        ・<strong>型Aコンフルエンス基準:</strong> DXYと同方向に <strong>|Z|≥${(zTh*0.72).toFixed(2)}σ</strong> で2市場一致成立 (${Math.abs(yldZ)>=zTh*0.72 ? '<strong class="text-bull">✅ 到達</strong>' : '待機中'})
      </div>
    </div>

    <div class="impact-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong>🛢️ ③ 原油 (USOIL) × 📈 米株 (USTEC)</strong>
        <span class="badge violet">地政学リスクオフ判定器</span>
      </div>
      <div style="font-size:12px;color:var(--muted);margin-top:3px;">
        原油 Z = <strong>${oilZ>=0?'+':''}${oilZ.toFixed(2)}σ</strong> ／ 米株 Z = <strong>${eqZ>=0?'+':''}${eqZ.toFixed(2)}σ</strong>
      </div>
      ${bipolarBarHtml(geoOff ? 2.0 : (oilZ > 0.8 && yldZ > 0.5 ? -1.5 : 0.0), 3.0)}
      <div style="font-size:11px;margin-top:6px;">
        ・<strong>発火条件:</strong> <code>原油Z≥+1.2σ</code> かつ <code>米株Z≤-0.8σ</code> かつ <code>金利Z≤-0.8σ</code><br>
        ・<strong>現在の判定:</strong> ${geoOff
          ? '<strong class="text-bull">🚨 地政学リスクオフ発動中！ゴールドBUYバイアスを +0.30 ブースト</strong>'
          : (oilZ > 0.8 && yldZ > 0.5
              ? '<strong class="text-bear">⚠️ 原油高＋金利高＝「インフレ型原油高」のためゴールド買いブーストを自動ブロック中</strong>'
              : '⚪ 通常状態（地政学ショックなし・補正 0.00）')}
      </div>
    </div>
  `;

  // M1ライブチャート
  const m1Series = st.m1_series || [];
  if (m1Series.length > 1) {
    drawLineChart('chart-live-m1', m1Series.map(r => r.time_str.slice(11,16)), [
      {label: 'XAUUSD 1分足価格 ($)', color: '#f59e0b', data: m1Series.map(r => Number(r.xau_close))}
    ]);
  }
}

function renderLogicSpec(st) {
  const m = st.market || {};
  const spec = st.live_spec || {};
  const dp = st.dynamic_params || {};
  const ctrl = st.control_config || {};
  const atr = Number(m.atr_m5_dollars || 2.0);
  const h1 = m.h1_trend || 'NEUTRAL';

  document.getElementById('spec-version-badge').textContent = `最適化 Version ${dp.version || 7} (最終更新: ${dp.last_updated || '--'})`;

  document.getElementById('spec-overview-banner').innerHTML = `
    <div style="font-weight:800;color:var(--gold);margin-bottom:4px;">🧭 現在適用中のグローバル原則（リアルタイム動的計算値）</div>
    <div>・<strong>上位足トレンドフォロー原則:</strong> 現在 H1 = <span class="live-val">${h1}</span> のため、<strong>${h1==='BULLISH'?'全ロジック BUY（買い）のみエントリー許可':(h1==='BEARISH'?'全ロジック SELL（売り）のみエントリー許可':'H1中立につき BUY / SELL 双方向許可')}</strong></div>
    <div>・<strong>現在稼働レジーム:</strong> <span class="live-val">${st.active_regime || 'REGIME_NORMAL_FLOW'}</span> ｜ <strong>M5 ATR(14):</strong> <span class="live-val">$${atr.toFixed(2)} (${(atr/0.10).toFixed(1)} pips)</span> ｜ <strong>動的許容SL範囲:</strong> <span class="live-val">${spec.effective_min_sl_pips || 18} 〜 ${spec.effective_max_sl_pips || 55} pips</span></div>
    <div>・<strong>ポジション＆リスク管理:</strong> 3系統それぞれ最大1ポジ（全体最大 <span class="live-val">${ctrl.max_concurrent_positions || 3}ポジ</span> 順張りピラミッディング）、1トレード基本リスク <span class="live-val">${ctrl.risk_per_trade_percent || 1.5}%</span>（先行建玉が建値移動前なら追加ポジは <span class="live-val">0.80倍</span>、建値移動済なら <span class="live-val">1.00倍</span>）</div>
  `;

  const zTh = Number(spec.effective_momentum_z_threshold || 1.50);
  const mSlMult = Number(spec.effective_macro_sl_atr_mult || 1.70);
  const mSlPips = (atr * mSlMult / 0.10).toFixed(1);
  const mRr = Number(spec.effective_macro_min_rr || 1.80);
  const smtRr = Number(spec.effective_smt_min_rr || 2.00);
  const smtDivDollars = Math.max(0.25, atr * 0.12).toFixed(2);
  const chaseLimitDollars = Math.max(1.5, atr * 1.5).toFixed(2);

  const smcRr = Number(spec.effective_smc_min_rr || 1.50);
  const wickTh = Number(spec.effective_wick_ratio || 0.25);
  const fvgGap = Number(spec.effective_min_fvg_gap || 0.40).toFixed(2);
  const atrSlMult = Number(spec.effective_atr_sl_mult || 1.40);
  const beRr = Number(spec.effective_be_trigger_rr || 1.15);
  const trailMult = Number(spec.effective_trail_atr_mult || 1.15);
  const trailCushionPips = Math.max(18.0, (atr * trailMult / 0.10)).toFixed(1);

  document.getElementById('spec-engines-container').innerHTML = `
    <div class="spec-box">
      <div class="spec-header">
        <span>🚀 系統1：型A コンフルエンス・マクロモメンタム（指標発信・FVG不要）</span>
        <span class="badge ${ctrl.enable_type_a!==false?'bull':'bear'}">${ctrl.enable_type_a!==false?'稼働中 (ON)':'停止中 (OFF)'}</span>
      </div>
      <ul class="spec-list">
        <li><strong>🎯 ロジックの狙い:</strong> 経済指標やNY市場オープンでドルと米金利が同時に急変し、FVG（押し目）を作らず一気に走るトレンド相場の第2波（ショック後5〜15分の本流）を捕捉します。</li>
        <li><strong>① 2市場同時コンフルエンス条件:</strong> <code>DXY</code> と <code>米金利(US10Y / USDJPY)</code> の3〜5分Zスコアが<strong>同方向</strong>であり、片方が <span class="live-val">|Z| ≥ ${zTh.toFixed(2)}σ</span>（ベース値 ${Number(dp.momentum_z_threshold||1.5).toFixed(2)}σ）かつ他方も <span class="live-val">|Z| ≥ ${(zTh*0.72).toFixed(2)}σ</span> を同時に満たすこと（ユーロ単体ノイズを完全排除）。</li>
        <li><strong>② 初動往復ビンタ回避クールダウン:</strong> <code>|Z| ≥ 2.40σ</code> の極端な指標スパイク時は、初検知から <span class="live-val">45秒 〜 240秒</span> 待機して上下ヒゲとスプレッド拡大の収束を待ちます。</li>
        <li><strong>③ ゴールド追随 ＆ 飛び乗り防止 (Max Chase Guard):</strong> XAUUSD自身がM1 EMA9の順方向で推移しており、かつ直近3分間で既に <span class="live-val">M5 ATR × 1.5倍 ($${chaseLimitDollars})</span> 以上飛んでいる場合は天井掴みを防ぐため見送ります。</li>
        <li><strong>④ 動的SL / TP / ロット設定:</strong> SL幅 ＝ <span class="live-val">M5 ATR × ${mSlMult.toFixed(2)}倍 (現在約 ${mSlPips} pips)</span> ｜ TP目標 ＝ <span class="live-val">RR 1 : ${mRr.toFixed(2)}</span>（H1+M15完全一致時は <span class="live-val">RR 1 : 2.20</span>）｜ H1順張り一致時はロット <span class="live-val">1.15倍</span>。</li>
      </ul>
    </div>

    <div class="spec-box">
      <div class="spec-header">
        <span>🎯 系統2：型B SMTダイバージェンス（機関投資家の吸収検知・FVG不要）</span>
        <span class="badge ${ctrl.enable_type_b!==false?'bull':'bear'}">${ctrl.enable_type_b!==false?'稼働中 (ON)':'停止中 (OFF)'}</span>
      </div>
      <ul class="spec-list">
        <li><strong>🎯 ロジックの狙い:</strong> 「ドル指数(DXY)が高値を更新したのに、ゴールドが安値を割らない（＝裏で大口・中央銀行が巨大な買い板で吸収している）」という機関投資家の痕跡を検知し、DXY失速初動でFVGを待たずに押し目・戻り目を狙い撃ちます。</li>
        <li><strong>① 35分間M1同期スイング比較:</strong> 確定M1足 <span class="live-val">35本</span> を「基準スイング（9〜35分前）」と「直近スイープ帯（直近8分間）」に分割してタイムスタンプ完全同期で比較。</li>
        <li><strong>② ダイバージェンス＆反転確定条件:</strong> BUYの場合、DXYが基準高値を上抜いたにもかかわらず、XAUUSDの直近8分安値が基準安値より <span class="live-val">$${smtDivDollars} (M5 ATR×0.12)</span> 以上高く維持され、直前M1確定足でDXYが失速（陰線または上ヒゲ30%以上）＋XAUUSDが陽線かつM1 EMA9上抜けで即発火。</li>
        <li><strong>③ 動的SL / TP設定:</strong> SL ＝ 直近8分スイープ安値/高値 ± <code>M5 ATR × 0.40</code>（最低 <span class="live-val">${spec.effective_min_sl_pips || 18} pips</span> 保証）｜ TP目標 ＝ <span class="live-val">RR 1 : ${smtRr.toFixed(2)}</span>。</li>
      </ul>
    </div>

    <div class="spec-box">
      <div class="spec-header">
        <span>🏛️ 系統3：SMC テクニカル 3大トリガー ＋ 先行指標オーバーレイ</span>
        <span class="badge ${ctrl.enable_smc!==false?'bull':'bear'}">${ctrl.enable_smc!==false?'稼働中 (ON)':'停止中 (OFF)'}</span>
      </div>
      <ul class="spec-list">
        <li><strong>① フラクタル流動性スイープ:</strong> M5足の左右2本ピボット高安・アジア高安・前日高安(PDH/PDL)をヒゲで抜いて実体で押し戻されたストップ狩り（現在のヒゲ比率閾値: <span class="live-val">${wickTh.toFixed(2)}</span>、2本合成ピンバー対応）。</li>
        <li><strong>② ICT Fair Value Gap (FVG) リテスト:</strong> 3本ローソク足で作られた未埋め価格空白（現在の最小ギャップ閾値: <span class="live-val">$${fvgGap}</span>）へのプルバック反発。</li>
        <li><strong>③ トレンドモメンタム EMA20 反発:</strong> M5足で <code>EMA20 > EMA50</code>（または <code>EMA20 < EMA50</code>）推進中のEMA20タッチ＆反発確定足。</li>
        <li><strong>④ 先行指標オーバーレイ（機会温存＆ブースト）:</strong> SL倍率 <span class="live-val">ATR × ${atrSlMult.toFixed(2)}</span>、基本目標RR <span class="live-val">1 : ${smcRr.toFixed(2)}</span> に対し、先行指標バイアスが順行（<code>≥ +0.35</code>）なら<strong>ロット <span class="live-val">1.25倍</span> ＆ TP <span class="live-val">+15%拡張</span></strong>、微逆行（<code>-0.35〜-0.70</code>）なら見送らず<strong>ロット <span class="live-val">0.75倍</span> で機会温存</strong>、極端逆行（<code>≤ -0.70</code>）のみ<strong>ハードガードでブロック</strong>。</li>
      </ul>
    </div>

    <div class="spec-box" style="margin-bottom:0;">
      <div class="spec-header">
        <span>🛡️ 共通イグジット・利益防衛 ＆ 自滅防止ルール</span>
        <span class="badge bull">常時有効</span>
      </div>
      <ul class="spec-list">
        <li><strong>① 建値自動移動 (Break-Even / 早すぎる建値刈り防止連動):</strong> 各ポジションの含み益が<strong>初期SL幅 × <span class="live-val">${beRr.toFixed(2)}倍 (かつ最低30pips)</span></strong>に到達した時点で、ブローカー側ハードSLを <span class="live-val">建値 + 2.5 pips</span> へ自動引き上げ。微益撤退が多発した場合は発動基準が自動拡大します。</li>
        <li><strong>② マクロ反転トレーリング利確（反発ノイズ耐性連動）:</strong> 含み益が <span class="live-val">最低35pips (または M5 ATR × 1.35 = ${(Math.max(3.5, atr*1.35)/0.10).toFixed(1)} pips)</span> 以上乗った状態で先行指標が反転した場合、現在価格から <span class="live-val">M5 ATR × ${trailMult.toFixed(2)} (現在約 ${trailCushionPips} pips / 最低18pips)</span> の呼吸幅を残してSLを引き上げ（押し目・戻りの反発による早すぎる微益決済を防止＆自動最適化）。</li>
        <li><strong>③ 狭すぎるSLの自動拡張 ＆ 同方向SL連敗防止:</strong> 短時間でのノイズ損切りが発生した際は最小SL幅（現在 <span class="live-val">${spec.effective_min_sl_pips || 22} pips</span>）とATR倍率が自動拡大（ロットは反比例縮小して損失額を固定）。損切り後は同方向を <span class="live-val">${ctrl.sl_cooldown_minutes || 15}分間</span> クールダウン。</li>
      </ul>
    </div>
  `;

  // 日々のロジック変更履歴タイムライン
  const hist = st.optimization_history || [];
  document.getElementById('spec-history-list').innerHTML = hist.map(h => `
    <div class="pos-slot" style="margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <strong style="color:var(--gold);">${h.title || h.date}</strong>
        <span class="badge">${h.badge || '自動適用済'}</span>
      </div>
      <div style="font-size:12px;color:var(--text);white-space:pre-line;">${h.detail || ''}</div>
    </div>
  `).join('') || `<div style="font-size:12px;color:var(--muted);">履歴データ読込中...</div>`;
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

  const ws = st.weekend_study || {};
  const corrs = ws.correlations_15m || {};
  const wts = ws.recommended_weights || {};
  const ll = (ws.lead_lag_profile || {}).horizon_breakdown || {};
  document.getElementById('weekend-study-box').innerHTML = `
    <div style="margin-bottom:6px;"><strong>最新15分相関 (対XAUUSD):</strong> ${Object.entries(corrs).map(([k,v]) => `<span class="badge">${k}: ${v >= 0 ? '+' : ''}${v}</span>`).join(' ')}</div>
    <div style="margin-bottom:6px;"><strong>自動適用バイアス重み:</strong> ドル指数(DXY) = <strong class="text-gold">${wts.dxy_weight || 0.7}</strong> ／ 米金利(US10Y/USDJPY) = <strong class="text-gold">${wts.yield_weight || 0.3}</strong></div>
    <div><strong>M1リードラグ（ショック後の順行勝率）:</strong> ${Object.entries(ll).map(([k,v]) => `<span class="badge violet">${k.replace('t_plus_','+')}: 勝率${v.directional_hit_rate_pct}% (${v.avg_favorable_pips>=0?'+':''}${v.avg_favorable_pips}p)</span>`).join(' ')}</div>
  `;

  // 日曜AI投資委員会＆AIモデルクォータ状態の描画
  const qSt = st.ai_quota_status || {};
  const qBadge = document.getElementById('ic-quota-badge');
  if (qBadge) {
    const qPct = qSt.pro_quota_health_pct !== undefined ? qSt.pro_quota_health_pct : 100;
    qBadge.textContent = `🧠 ${qSt.recommended_tier_label || 'Tier 1: Pro Deep'} (余裕度 ${qPct}%)`;
    qBadge.className = 'badge ' + (qPct >= 60 ? 'bull' : (qPct >= 25 ? 'gold' : 'bear'));
  }

  const ic = st.investment_committee || {};
  const icBox = document.getElementById('ic-committee-box');
  if (icBox) {
    if (!ic.meeting_id) {
      icBox.innerHTML = `<div style="padding:12px;background:var(--card-alt);border-radius:10px;color:var(--muted);">
        まだ投資委員会議事録がありません。毎週土曜 08:00 JST に徹底検証、日曜 10:00 JST に6役エージェント会議が自動開催されDiscordへ決裁通知が届きます。<br>
        右上の「<strong>🏛️ 今すぐ投資委員会を開催＆Discord決裁送信</strong>」ボタンを押すと、今すぐ最新データと最新ニュースで会議を実行できます。
      </div>`;
    } else {
      const f = ic.fundamental_report || {};
      const deb = ic.agent_debate || {};
      const alpha = deb.alpha_researcher || {};
      const macEx = deb.macro_and_execution || {};
      const aud = deb.red_team_auditor || {};
      const cio = deb.cio_chairman || {};
      const opts = ic.options || {};
      const nExp = ic.next_week_experiment || {};
      const rMap = ic.mid_long_term_roadmap || [];
      const stBadge = ic.status === 'APPROVED'
        ? `<span class="badge bull">✅ 決裁完了: 選択肢 ${ic.approved_choice} (${ic.approved_at || ''})</span>`
        : (ic.status === 'REJECTED_KEEP_CURRENT'
            ? `<span class="badge">🔴 却下・現状維持 (${ic.approved_at || ''})</span>`
            : `<span class="badge gold">⏳ オーナー決裁待ち (推奨: 選択肢 ${ic.recommended_choice || 'C'})</span>`);

      icBox.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:10px;padding:8px 10px;background:var(--card-alt);border-radius:8px;">
          <div><strong>議事録ID:</strong> <code>${ic.meeting_id}</code> <span style="color:var(--muted);font-size:11px;">(${ic.held_at || ''})</span></div>
          <div>${stBadge}</div>
        </div>

        <div class="impact-explain" style="margin-bottom:10px;">
          <div style="font-weight:800;color:var(--gold);margin-bottom:4px;">📰 1. ファンダメンタルズ＆地政学インテリジェンス分析</div>
          <div>・<strong>今週の値動き×ニュース因果:</strong> ${f.this_week_causal_analysis_ja || ''}</div>
          <div>・<strong>週末新着ニュース＆来週イベント:</strong> ${f.weekend_news_and_next_week_events_ja || ''}</div>
          <div>・<strong>🎯 来週のファンダ狙い目:</strong> <strong class="text-bull">${f.recommended_focus_ja || ''}</strong></div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
          <div class="pos-slot" style="border-left:3px solid var(--gold);">
            <div style="font-weight:800;color:var(--gold);margin-bottom:3px;">🎯 アルファ開拓官 (攻め・平均化禁止)</div>
            <div style="font-size:11px;line-height:1.5;">${alpha.bold_proposal_ja || ''}</div>
          </div>
          <div class="pos-slot" style="border-left:3px solid var(--bear);">
            <div style="font-weight:800;color:var(--bear);margin-bottom:3px;">🛡️ RedTeam リスク監査官 (反証・過剰適合ブロック)</div>
            <div style="font-size:11px;line-height:1.5;">${aud.red_team_critique_ja || ''}<br><strong style="color:var(--text);">監査結論:</strong> ${aud.risk_audit_verdict_ja || ''}</div>
          </div>
          <div class="pos-slot" style="border-left:3px solid var(--primary);">
            <div style="font-weight:800;color:#60a5fa;margin-bottom:3px;">🌍 マクロ戦略官 ＆ ⚡ 執行分析官</div>
            <div style="font-size:11px;line-height:1.5;">${macEx.macro_and_execution_view_ja || ''}</div>
          </div>
          <div class="pos-slot" style="border-left:3px solid var(--bull);">
            <div style="font-weight:800;color:var(--bull);margin-bottom:3px;">⚖️ CIO 最高投資責任者 (最終裁定)</div>
            <div style="font-size:11px;line-height:1.5;"><strong>核心争点:</strong> ${ic.core_agenda_ja || ''}<br>${cio.cio_verdict_ja || ''}</div>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
          <div class="impact-card">
            <div style="font-weight:800;color:#a78bfa;margin-bottom:4px;">🔬 次週（来週1週間）のシャドー検証テーマ</div>
            <div style="font-weight:700;margin-bottom:3px;">『${nExp.title || ''}』</div>
            <div style="font-size:11px;color:var(--muted);">${nExp.hypothesis || ''}</div>
          </div>
          <div class="impact-card">
            <div style="font-weight:800;color:#38bdf8;margin-bottom:4px;">🗺️ 中長期（1〜3ヶ月）のロジック構造修正方針</div>
            ${rMap.map(r => `<div style="font-size:11px;margin-bottom:3px;">・<strong>[優先度:${r.priority}] ${r.title}</strong> <span class="badge">${r.status || ''}</span></div>`).join('')}
          </div>
        </div>

        <div style="background:rgba(15,23,42,0.85);padding:10px;border-radius:10px;border:1px solid var(--border);">
          <div style="font-weight:800;margin-bottom:8px;color:var(--gold);">👑 オーナー決裁アクション（平均化なしの3択パッケージ ＋ 却下）</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;">
            <button class="btn" style="background:rgba(245,158,11,0.16);border:1px solid var(--gold);color:var(--text);text-align:left;padding:10px;" onclick="confirmIcDecision('A', '${ic.meeting_id}')">
              <div style="font-weight:800;color:var(--gold);">🔥 選択肢A（攻め）を採択</div>
              <div style="font-size:10px;color:var(--muted);margin-top:3px;">${(opts.A||{}).summary_ja || ''}</div>
            </button>
            <button class="btn" style="background:rgba(59,130,246,0.16);border:1px solid #3b82f6;color:var(--text);text-align:left;padding:10px;" onclick="confirmIcDecision('B', '${ic.meeting_id}')">
              <div style="font-weight:800;color:#60a5fa;">🛡️ 選択肢B（守り）を採択</div>
              <div style="font-size:10px;color:var(--muted);margin-top:3px;">${(opts.B||{}).summary_ja || ''}</div>
            </button>
            <button class="btn" style="background:rgba(16,185,129,0.18);border:2px solid var(--bull);color:var(--text);text-align:left;padding:10px;" onclick="confirmIcDecision('C', '${ic.meeting_id}')">
              <div style="font-weight:800;color:var(--bull);">🧪 選択肢C（本番B＋裏シャドーでA検証）★推奨</div>
              <div style="font-size:10px;color:var(--muted);margin-top:3px;">${(opts.C||{}).summary_ja || ''}</div>
            </button>
            <button class="btn" style="background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--muted);text-align:left;padding:10px;" onclick="confirmIcDecision('REJECT', '${ic.meeting_id}')">
              <div style="font-weight:800;color:#cbd5e1;">🔴 すべて却下（現状維持）</div>
              <div style="font-size:10px;color:var(--muted);margin-top:3px;">現行パラメータのまま変更せず継続</div>
            </button>
          </div>
        </div>
      `;
    }
  }
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

  let cum = 0;
  const eqCurve = [0];
  const closedAsc = [...trades].reverse().filter(t => t.profit !== null);
  closedAsc.forEach(t => { cum += Number(t.profit || 0); eqCurve.push(cum); });
  drawLineChart('chart-equity', eqCurve.map((_,i)=>String(i)), [
    {label: '確定損益推移 (JPY)', color: '#10b981', data: eqCurve}
  ]);

  cachedTrades = trades;
  renderTradesTable();
}

let tradesShowAll = false;
let cachedTrades = [];

function toggleTradeHistoryView() {
  tradesShowAll = !tradesShowAll;
  renderTradesTable();
}

function renderTradesTable() {
  const tbody = document.getElementById('trades-tbody');
  const infoEl = document.getElementById('trades-filter-info');
  const btn = document.getElementById('btn-load-more-trades');
  if (!tbody) return;

  const trades = cachedTrades || [];
  if (trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px;">トレード履歴はありません</td></tr>';
    if (infoEl) infoEl.innerHTML = '';
    if (btn) btn.style.display = 'none';
    return;
  }

  // 直近3日（72時間）の基準
  const cutoff = Date.now() - (3 * 24 * 60 * 60 * 1000);
  const recent3d = [];
  const older = [];

  trades.forEach(t => {
    // 保有中 (OPEN) は常に直近枠に含める
    if (t.profit === null) {
      recent3d.push(t);
      return;
    }
    const tTime = t.time ? new Date(t.time.replace(' ', 'T')).getTime() : 0;
    if (tTime && tTime >= cutoff) {
      recent3d.push(t);
    } else {
      older.push(t);
    }
  });

  // 直近3日以内が0件の場合は最新5件を初期表示
  const baseList = recent3d.length > 0 ? recent3d : trades.slice(0, 5);
  const displayList = tradesShowAll ? trades : baseList;

  if (tradesShowAll) {
    if (infoEl) infoEl.innerHTML = `<span class="badge gold">全 ${trades.length} 件を表示中</span>`;
    if (btn) {
      btn.style.display = 'inline-block';
      btn.innerHTML = '▲ 過去3日分のみに折りたたむ';
    }
  } else {
    const is3d = recent3d.length > 0;
    if (infoEl) infoEl.innerHTML = `<span class="badge">${is3d ? '過去3日分' : '直近'} ${displayList.length}件 / 全${trades.length}件</span>`;
    if (btn) {
      if (trades.length > displayList.length) {
        btn.style.display = 'inline-block';
        btn.innerHTML = `▼ さらに過去の履歴を読み込む (+${trades.length - displayList.length}件)`;
      } else {
        btn.style.display = 'none';
      }
    }
  }

  tbody.innerHTML = displayList.map(t => {
    const p = t.profit !== null ? Math.round(Number(t.profit)) : null;
    const pTxt = p === null ? '<span class="badge gold">保有中 (OPEN)</span>' : `<strong class="${p >= 0 ? 'text-bull' : 'text-bear'}">${p >= 0 ? '¥+' : '¥'}${p.toLocaleString()}</strong>`;
    return `<tr>
      <td>${(t.time||'').slice(5,16)}</td>
      <td><span class="badge">${t.entry_engine || 'SMC'}</span></td>
      <td><strong>${t.action}</strong> (${t.volume}L)</td>
      <td>${t.setup_name || ''}</td>
      <td>$${Number(t.price||0).toFixed(2)} → ${t.close_price ? '$'+Number(t.close_price).toFixed(2) : '--'}</td>
      <td>SL:$${Number(t.sl||0).toFixed(1)} / TP:$${Number(t.tp||0).toFixed(1)}</td>
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

let isEditUnlocked = false;
let pendingConfirmFn = null;

function toggleEditLock(forceState=null) {
  isEditUnlocked = (forceState !== null) ? forceState : !isEditUnlocked;
  const zone = document.getElementById('control-locked-zone');
  const banner = document.getElementById('edit-lock-banner');
  const title = document.getElementById('edit-lock-title');
  const btn = document.getElementById('edit-lock-btn');
  if (isEditUnlocked) {
    zone.classList.add('unlocked');
    banner.classList.add('unlocked');
    title.textContent = '🔓 編集モード解除中（変更後に最下部の保存ボタンを押してください）';
    title.style.color = 'var(--bull)';
    btn.textContent = '🔒 編集ロックに戻す';
    btn.className = 'btn btn-sm';
  } else {
    zone.classList.remove('unlocked');
    banner.classList.remove('unlocked');
    title.textContent = '🔒 誤操作防止ロック中（スクロール時に手が当たっても変更されません）';
    title.style.color = 'var(--gold)';
    btn.textContent = '🔓 ロックを解除して編集';
    btn.className = 'btn btn-sm btn-gold';
    controlsInitialized = false;
    if (window._lastFetchedState) populateControls(window._lastFetchedState);
  }
}

function openConfirmModal(titleTxt, descTxt, onYesFn) {
  document.getElementById('confirm-title').textContent = titleTxt;
  document.getElementById('confirm-desc').textContent = descTxt;
  pendingConfirmFn = onYesFn;
  document.getElementById('confirm-yes-btn').onclick = async () => {
    const fn = pendingConfirmFn;
    closeConfirmModal();
    if (fn) {
      await fn();
      toggleEditLock(false);
    }
  };
  document.getElementById('confirm-modal').classList.add('open');
}

function closeConfirmModal() {
  document.getElementById('confirm-modal').classList.remove('open');
  pendingConfirmFn = null;
}

function confirmApplySimParamsToLive() {
  const z = Number(document.getElementById('sim-z').value).toFixed(2);
  const mrr = Number(document.getElementById('sim-mrr').value).toFixed(2);
  const srr = Number(document.getElementById('sim-srr').value).toFixed(2);
  const atr = Number(document.getElementById('sim-atr').value).toFixed(2);
  const pos = document.getElementById('sim-pos').value;
  openConfirmModal(
    '✨ シミュレーション設定の本番適用確認',
    `以下の検証パラメータを本番BOTへ適用しますか？\n\n・型A Zスコア閾値: ${z}σ\n・型A 最小RR比: 1 : ${mrr}\n・系統3 SMC 最小RR比: 1 : ${srr}\n・ATR SL倍率: ${atr}倍\n・最大同時保有ポジ数: ${pos}ポジ`,
    applySimParamsToLive
  );
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
  showToast(r.message || 'シミュレーション設定を本番ロジックへ適用しました！');
  refreshAll();
}

function confirmSetStance(stance) {
  const names = {
    'AGGRESSIVE': '🔥 積極トレンド追撃モード (Z閾値1.35 / 最大3ポジ)',
    'BALANCED': '⚖️ 標準バランスモード (Z閾値1.50 / 最大3ポジ)',
    'DEFENSIVE': '🛡️ 厳選・資金防衛モード (Z閾値1.70 / 最大1ポジ)',
    'PAUSED': '⏸️ 新規エントリー一時停止モード (保有ポジのみ保護)'
  };
  openConfirmModal(
    '⚡ 運用スタンス変更の確認',
    `BOTの運用スタンスを以下に変更してよろしいですか？\n\n👉 【 ${names[stance] || stance} 】`,
    () => setStance(stance)
  );
}

async function setStance(stance) {
  const r = await apiCall('/api/control/stance', 'POST', {stance});
  controlsInitialized = false;
  showToast(r.message || `スタンスを ${stance} に切り替えました`);
  refreshAll();
}

function confirmSaveControlConfig() {
  const enA = document.getElementById('cfg-en-a').checked ? 'ON' : 'OFF';
  const enB = document.getElementById('cfg-en-b').checked ? 'ON' : 'OFF';
  const enS = document.getElementById('cfg-en-smc').checked ? 'ON' : 'OFF';
  const maxP = document.getElementById('cfg-max-pos').value;
  const risk = document.getElementById('cfg-risk-pct').value;
  const dd = document.getElementById('cfg-dd-pct').value;
  const maxLot = document.getElementById('cfg-max-lot').value;
  const sp = document.getElementById('cfg-max-sp').value;
  const dir = document.getElementById('cfg-owner-dir').value.trim();

  const posTxt = Number(maxP) === 0 ? '無制限' : `${maxP}ポジ`;
  const ddTxt = Number(dd) <= 0 ? '設定なし(無制限)' : `${dd}%`;
  const spTxt = Number(sp) <= 0 ? '設定なし(無制限)' : `${sp} pips`;
  const lotTxt = Number(maxLot) <= 0 ? '設定なし(口座上限)' : `${maxLot} Lot`;

  openConfirmModal(
    '💾 設定・改修方針の保存確認',
    `以下の設定を保存し、本番BOTへ反映してよろしいですか？\n\n・稼働ロジック: 型A[${enA}] / 型B[${enB}] / SMC[${enS}]\n・最大同時ポジ数: ${posTxt}\n・1回リスク: ${risk}%\n・日次最大DD停止: ${ddTxt}\n・ロット上限: ${lotTxt}\n・許容スプレッド: ${spTxt}\n・AI方針メモ: ${dir ? dir : '(指定なし)'}`,
    saveControlConfig
  );
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

function confirmSwitchBrokerAccount() {
  const login = Number(document.getElementById('brk-login').value);
  const server = document.getElementById('brk-server').value.trim();
  const password = document.getElementById('brk-pass').value;
  const symbol = document.getElementById('brk-symbol').value.trim();
  if (!login || !server || !password) {
    showToast('MT5口座を切り替えるにはログイン番号・サーバー名・パスワードを入力してください', true);
    return;
  }
  openConfirmModal(
    '🏦 MT5アカウント（証券会社）切替の確認',
    `接続先MT5アカウントを以下へ切り替えてよろしいですか？\n\n・ログイン番号: #${login}\n・サーバー名: ${server}\n・指定ゴールド銘柄: ${symbol || '(自動検出)'}`,
    switchBrokerAccount
  );
}

async function switchBrokerAccount() {
  const login = Number(document.getElementById('brk-login').value);
  const server = document.getElementById('brk-server').value.trim();
  const password = document.getElementById('brk-pass').value;
  const symbol = document.getElementById('brk-symbol').value.trim();
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

function confirmTriggerLabTask(task) {
  let desc = '';
  if (task === 'daily_report') {
    desc = '今すぐ6ブロック日次運用ブリーフィングを生成してDiscordへ送信しますか？\n（※Gemini APIを1回呼び出します）';
  } else if (task === 'sunday_ic_meeting') {
    desc = '今すぐ【6役マルチエージェントAI投資委員会】を開催しますか？\n\n・土曜ディープ検証＆21日What-Ifバックテスト\n・最新ファンダメンタルズ＆ニュース取得\n・6役独立セッション議論（クォータ連動・最上位モデル優先）\n・Discordへワンタップ決裁通知を送信します（所要約15〜30秒）';
  } else {
    desc = '今すぐ最新M5/M1データで土曜ディープ検証（相関・リードラグ・What-Ifバックテスト）を再計算し、結果をDiscordへ送信しますか？\n（※AIトークン消費はゼロです）';
  }
  openConfirmModal('📨 手動実行の確認', desc, () => triggerLabTask(task));
}

function confirmIcDecision(choice, meetingId) {
  const names = {
    'A': '🔥 選択肢A：【攻め】アルファ開拓＆ファンダ順張り特化パッケージを本番適用',
    'B': '🛡️ 選択肢B：【守り】ノイズSL完全防御＆高勝率イグジット改善パッケージを本番適用',
    'C': '🧪 選択肢C：【ハイブリッド（推奨）】本番は🛡️選択肢Bを適用し、裏シャドー枠で🔥選択肢A＆次週テーマを1週間検証',
    'REJECT': '🔴 却下：今週の提案はすべて見送り（完全現状維持）'
  };
  openConfirmModal(
    '👑 投資委員会 オーナー決裁の確認',
    `以下の決裁を確定し、システムへ反映（およびDiscordへ決裁完了通知）してよろしいですか？\n\n👉 ${names[choice] || choice}`,
    async () => {
      const r = await apiCall('/api/ic/decide_dashboard', 'POST', {choice, meeting_id: meetingId});
      showToast(r.message || `選択肢 ${choice} を採択しました！`, !r.success);
      refreshAll();
    }
  );
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
