# 🔒 XAU/USD クオンツ自律取引システム 確定仕様 ＆ デグレ防止スナップショット
最終更新: 2026-11-07 (v8.3 Institutional Pro Edition)

本ドキュメントは、Contabo VPS上でのXAU/USD完全自律稼働、トレードロジック設計、リスク管理、AI連携、Discord通知仕様、および過去の失敗から得た教訓を網羅した**マスター復元リファレンス**です。
`/compact` 実行後やコンテキスト復元時、以下の確定ルールおよび設計方針を最優先で遵守し、先祖返り（デグレ）を固く防止すること。

---

## 1. 運用環境・インフラ確定仕様
* **VPSホスト**: Contabo VPS (Ubuntu 22.04 LTS, 4コア / 8GB RAM, IP: `155.133.7.59`, user: `root`, SSH鍵認証済)
* **VPS上プロジェクトパス**: `/root/xauusd_ai_hedge_fund`
* **ローカルプロジェクトパス**: `C:\Users\user\.gemini\antigravity\scratch\xauusd_ai_hedge_fund`
* **完全隔離アーキテクチャ (Docker Compose)**:
  * `mt5-server` (lprett/mt5linuxベース, Wine ＋ MT5 build 6230, CPU 1.5コア/メモリ 1.5GB制限)
  * `xauusd-quant-bot` (Python 3.11-slim, CPU 1.0コア/メモリ 1.0GB制限)
  * 隔離ネットワーク `quant-net` (bridge) により、ホストの主要ポート（80, 443, 3000等）への干渉ゼロ。外部公開はnoVNC用 18080 のみ。
* **ブローカー・認証情報**:
  * Broker: Exness Demo
  * Account Login: `277984494`
  * Server: `Exness-MT5Trial5`
  * Password: `aA!24861793`
* **Google Cloud (Vertex AI / Gemini API)**:
  * Project ID: `xauusd-ai-fund` (ADC: `config/application_default_credentials.json`)
  * Model: `gemini-2.5-flash` (Location: `us-central1`, `thinking_budget: 0`)
* **Discord Webhook**:
  * URL: `https://discord.com/api/webhooks/1556945137257680907/CzP5QETlItJvdLr1zyLFSfPeFJJO_M9x2RnD0zcPDKRgqtNY0e_bCSafNkRvW7pY_GW4`

---

## 2. トレード戦略確定仕様 (`SMC_Institutional_Pro_v8.3`)
大口機関投資家（スマートマネー）の流動性スイープとFVGリテストを狙い、**平常日であれば1日 5〜10回**の優位性あるエントリーを安定執行する。

1. **3大プロトリガー（マルチセットアップ並行監視）**:
   * **トリガー①: フラクタル・ピボット流動性スイープ (Fractal Pivot Sweep)**
     * M5足の直近フラクタル高安（左右2本より高い/低いピボット）および日次高安（PDH/PDL/AsiaH/L）を一瞬ヒゲで抜けた後、実体で押し戻されたストップ狩りを狙い撃つ。
     * SL: スイープ先 + 0.35 ATR (12〜55 pips) / TP: RR 1:1.8〜2.0 / 確信度: 0.88
   * **トリガー②: ICT Fair Value Gap (FVG / 不均衡ゾーン) リテスト**
     * 大口のインパルス急伸・急落で作られた未埋めギャップ（0.4ドル以上の価格空白）への戻りを検知し、順張り押し目・戻り目エントリー。
     * SL: FVG外側 + 0.3 ATR / TP: RR 1:1.8以上 / 確信度: 0.84
   * **トリガー③: トレンドモメンタム EMA20 プルバック反発**
     * M5足でパーフェクトオーダー（EMA20 > EMA50 または EMA20 < EMA50）時、EMA20へのタッチ＆反発ヒゲから順張り加速に乗る。
     * 確信度: 0.80

2. **「トレードしなさすぎる」を防止するための感度基準**:
   * 0.7倍縛りの過剰フィルターを廃止し、「ヒゲ比率 0.4倍以上、またはピンバー／次足での陰陽反転」という実戦基準を採用。
   * M5足（5分足）ベースで機敏にスキャンし、チャンスの見落としを完全排除。

---

## 3. リスク管理 ＆ プロップファーム仕様の確定原則
1. **単一ポジション限定インターロック (One Position Only)**:
   * 1つのポジションが決済（TPまたはSL）されるまで、追加発注（ナンピン・両建て）は絶対に禁止。
2. **ブローカー側ハードSL/TPの即時付与**:
   * 成行約定と同時に、必ずExnessブローカーサーバーへ直接ハードSLおよびTPをミリ秒でセット（VPS切断時も完全安全）。
3. **【プロップ流】建値自動移動 (Break-Even Auto-Sliding)**:
   * 含み益が `+20 pips`（初期リスクと同等）に達した瞬間、SLを即座に「建値 ＋ 1 pip（微益確保）」へ自動スライド。
   * 「負けゼロ」状態で利を伸ばし、急激な全戻しヒゲ相場による損失を完全回避。
4. **スプレッド上限インターロック**:
   * 現在スプレッドが 3.0 pips を超える急変・拡大時は発注を自動ブロック。
5. **日次最大損失サーキットブレーカー**:
   * 日次資産の 3.0% 以上の損失を検知した場合は当日の取引を完全停止。

---

## 4. Discord通知・自律PDCA確定仕様
1. **毎時00分 AI合議体 定時分析レポート (`🤖 XAU/USD AI合議体 定時分析レポート`)**:
   * 📝 **合議体エグゼクティブ解説**（テクニカル・高安・相場レジーム）
   * 😈 **デビルズアドボケート (リスク反論)**（フェイクアウトや罠の指摘）
   * 🎬 **AIプロデューサー助言**（次セッションの立ち回り方針）
   * 入力・出力圧縮 ＆ `thinking_budget: 0` により、1回約300トークンの超省トークンを厳守。
2. **実エントリー即時通知 (`⚡ 【実約定完了】 XAUUSD BUY/SELL`)**:
   * エントリーの瞬間に、売買種別、価格、SL/TP、動的ATR根拠、セットアップ解説、Geminiマクロ安全判定を即時通知。
3. **安全門番通知の廃止方針**:
   * 「AIマクロ安全門番発動（シグナル一時静観）」のDiscord通知およびメッセージ作成処理は、通知過多とノイズ排除のため**完全に停止（ログのみ記録）**とする。
4. **毎朝06:00 自律振り返りレポート (`📋 【XAU/USD 日次トレード振り返り ＆ 自律改善レポート】`)**:
   * 取引回数（平常時目標5回以上に対しどうだったか？）、勝敗、相場とロジックの相性をGeminiが自己診断。
   * 改善教訓を `logs/learning_journal.md` に永続蓄積。

---

## 5. 過去の失敗と教訓（Lessons Learned - デグレ厳禁）
* **【教訓1: RPyCバージョン不一致】**: Wine側MT5サーバー（RPyC 6系）とBot側クライアントでバージョンが異なると通信不能になる。Bot側は `rpyc==6.0.1` 固定。
* **【教訓2: 日次高安のみの監視による取引過少】**: 前日高安・アジア高安だけだと数日に1回しかエントリーされない。直近フラクタル高安・FVG・M5足の併用が必須。
* **【教訓3: 思考トークンの無制限消費】**: Gemini 2.5 Flashでthinking_budgetを指定しないとトークンを浪費する。`thinking_budget: 0` を常に指定すること。
* **【教訓4: 戻り相場での利益消失】**: ゴールドは急伸後の全戻しが多いため、+20pips乗った時点での建値移動（Break-Even）が不可欠。

---

## 6. Step 2 確定仕様 (2026-11-19 / v9.0 SMC_Macro_Hybrid)
* **デュアル先行指標パイプライン（M1ベース）**:
  * **主系 (TradingView Premium / 2026年2月まで)**: `http://155.133.7.59/tv-webhook` (Port 80 -> コンテナ 8000, `.env` の `TV_WEBHOOK_TOKEN` 認証)。Pine Script `tradingview/xauusd_macro_sentinel.pine` で `TVC:DXY` + `TVC:US10Y` + `TVC:US02Y` + `XAUUSD` を非リペイント監視。
  * **副系 (Exness MT5 M1 完全自動フェイルオーバー)**: TV無受信時（15分超）または解約後は `DXY` + `USDJPY`（米金利プロキシ）+ `USOIL` + `USTEC` + `XAUUSD` のM1生データへ自動切替。
* **上位足トレンドフォロー 3系統ハイブリッド**:
  * H1トレンド（`BULLISH`/`BEARISH`）への順張りを全系統で徹底し、`NEUTRAL`時は双方向を解放して機会損失を防止。
  * **型A (マクロモメンタム / FVG不要)**: 2市場同時一致＋極端ショック45秒クールダウン＋XAUUSD追随確認＋飛び乗り防止（M5 ATR×1.5）＋M5 ATR×1.7動的SL（RR 1.8〜2.2）。
  * **型B (SMTダイバージェンス / FVG不要)**: DXY vs XAUUSD M1同期35分スイング比較で機関吸収を検知（RR 2.0）。
  * **系統3 (既存SMC＋ソフト/ハードオーバーレイ)**: 極端逆行(`<= -0.70`)のみブロック、微逆行(`<= -0.35`)はロット0.75x、順行(`>= +0.35`)はロット1.25x＆TP+15%拡張。
* **利益防衛マクロ反転トレーリング**: 含み益がM5 ATR×1.1（かつ25pips）以上乗った状態でDXY＆金利がM5 EMA20を逆抜けした場合、SLを段階引き上げ。

---

## 7. Step 3 確定仕様 (2026-11-19 / 先行指標レジーム適応 ＆ ログ保全)
* **リアルタイム4レジーム適応 (`DynamicParamOptimizer.classify_and_adapt_regime`)**:
  * `REGIME_MACRO_TREND` / `REGIME_GEO_VOLATILITY` / `REGIME_MACRO_CHOP` / `REGIME_NORMAL_FLOW` を15秒ごとに判定し、RR比・型A感度・ATR SL倍率をガードレール内でオンメモリ動的調整。
* **MT5決済損益の完全突合 (`ReviewEngine.reconcile_with_mt5_history`)**:
  * 起動時・決済検知時・日次レビュー前にMT5の `position_id` / `order` と `trade_journal.json` を自動突合し、未同期のOPENレコードをゼロに保つ。
* **ログ＆ディスク永久保全 (`LogMaintainer` + Docker log limit)**:
  * `trade_journal.json`（上限300件＋OPEN）および `learning_journal.md`（上限256KB）の超過分を `logs/archive/*.gz` へ自動圧縮退避。
  * `docker-compose.yml` でコンテナログを `10MB × 3世代` に制限。
