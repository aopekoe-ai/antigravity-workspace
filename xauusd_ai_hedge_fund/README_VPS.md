# 📦 XAU/USD Institutional SMC System - VPS 運用パッケージガイド

本パッケージは、プロ基準のクオンツ・リスク管理とスマートマネー・コンセプト（SMC）流動性スイープ戦略を搭載した、24時間常時稼働型の自動取引システムです。

---

## 📁 ディレクトリ構成と役割

```text
xauusd_ai_hedge_fund/
├── config/
│   ├── strategy_params.json    # ⚙️ 戦略パラメータ（相場変化時にここを編集するだけ！）
│   └── settings.py             # 🔑 APIキー・環境変数管理
├── core/
│   ├── mt5_client.py           # 🔌 堅牢なMT5通信 ＆ ハードSL執行
│   ├── data_engine.py          # 📊 ATR・流動性プール（高安値）の算出
│   └── risk_manager.py         # 🛡️ 動的ロットサイジング ＆ サーキットブレーカー
├── strategies/
│   ├── base_strategy.py        # 🧩 戦略プラグインの共通基底クラス
│   └── smc_liquidity_strategy.py # 🎯 SMC 流動性スイープ ＆ 動的ATR戦略
├── ai/
│   └── macro_nlp_guard.py      # 🤖 Gemini 2.5 Flash によるマクロ安全門番
├── notifications/
│   └── discord_manager.py      # 📱 Discordリッチ通知
├── logs/                       # 📝 稼働ログ保存フォルダ
├── main.py                     # 🚀 24時間常時スキャン・メインオーケストレーター
├── run_vps.bat                 # 🔄 VPS自動復旧（Watchdog）付き起動バッチ
└── requirements.txt            # 📦 依存Pythonライブラリ一覧
```

---

## ⚙️ 相場変化時の「パラメータ編集・修正」方法

相場のボラティリティが変わった場合、**プログラムコード（Python）を一切触る必要はありません**。
`config/strategy_params.json` をメモ帳等で編集して保存するだけで、稼働中のシステムが**自動で即座に新しいパラメータを読み込みます**。

### 主要パラメータ一覧 (`config/strategy_params.json`):

| パラメータ名 | 初期値 | 意味・調整の目安 |
| :--- | :---: | :--- |
| `risk_per_trade_percent` | `1.5` | 1トレードあたりの許容リスク（口座残高の％）。慎重派は `1.0` に変更。 |
| `max_daily_drawdown_percent` | `3.0` | 日次最大許容損失。この損失に達したら当日の全取引を自動停止。 |
| `atr_sl_multiplier` | `1.8` | 動的SLの幅。ノイズで狩られやすい時期は `2.0`〜`2.5` に広げる。 |
| `min_sl_pips` | `25.0` | 最小SL幅（pips）。極端に狭すぎる損切りを防止。 |
| `max_sl_pips` | `80.0` | 最大SL幅（pips）。リスクリワードが悪化するのを防止。 |
| `min_risk_reward_ratio` | `2.0` | 最低リスクリワード比（1:2.0以上でなければエントリーしない）。 |
| `max_allowed_spread_pips` | `3.0` | 許容最大スプレッド。指標時などのスリッページを防止。 |

---

## 🧩 新しいロジックを追加・差し替えたい場合

相場が完全に変わり、新しい戦略を試したくなった場合は、`strategies/` フォルダ内に新しいファイルを作成するだけで簡単に差し替え可能です：

1. `strategies/base_strategy.py` の `BaseStrategy` クラスを継承したクラスを作成。
2. `evaluate(market_data) -> TradeSignal` メソッド内に新しいルールを記述。
3. `main.py` の `strategy = SMCLiquiditySweepStrategy(params=params)` の部分を新しい戦略クラスに差し替えるだけ。

---

## 🚀 VPS（Windows Server）への導入手順（5ステップ）

### 1. VPSの用意
* 推奨スペック: Windows Server 2022 / 2025（メモリ 2GB〜4GB、CPU 2コア以上）。
* おすすめVPS: お名前.comデスクトップクラウド, ConoHa VPS, さくらのVPS, ForexVPS等。

### 2. MT5のインストール & 設定
1. VPS上でMT5（Exness等）をインストールし、取引口座にログイン。
2. MT5上部ツールバーの **「アルゴリズム取引」** ボタンをON（緑色▶）にする。
3. **「ツール」➔「オプション」➔「エキスパートアドバイザ」** で：
   * ✅ 「アルゴリズム取引を許可」にチェック。
   * ✅ 「DLLの使用を許可」にチェック。

### 3. Pythonのインストール
1. VPSのブラウザで [python.org](https://www.python.org/downloads/) から Python 3.10以上をダウンロード。
2. インストール時、**「Add python.exe to PATH」に必ずチェック**を入れてインストール。

### 4. パッケージの配置とライブラリ導入
1. この `xauusd_ai_hedge_fund` フォルダをそのままVPSのデスクトップ（またはCドライブ直下）にコピー。
2. コマンドプロンプトを開き、以下を実行して依存ライブラリを一括インストール：
   ```cmd
   cd C:\Users\Administrator\Desktop\xauusd_ai_hedge_fund
   pip install -r requirements.txt
   ```

### 5. 自動運転の開始
* フォルダ内の **`run_vps.bat`** をダブルクリックするだけ！
* 画面に「[SYSTEM READY] 常時スキャンループを開始します」と表示されれば完了です。
* ※`run_vps.bat` には自動復旧ループが組み込まれているため、万が一ネットワーク切断などでプロセスが終了しても、5秒後に自動で自己復旧して取引を継続します。

---

## 🛡️ 本システムが解決した「旧バージョンの致命的欠陥」

| 旧バージョンの欠陥 | 本バージョン（v8.0）での解決策 |
| :--- | :--- |
| **LLMに価格予測をさせていた** | 予測を破棄し、数理SMC流動性ルールでシグナル生成。LLMはマクロ安全門番に限定。 |
| **固定20pips損切り（ノイズ刈り）** | M15 ATRに基づく**動的損切り ＆ 適正ロットサイジング**。 |
| **毎時00分成行（スリッページ激甚）** | 15秒ごとの常時スキャンによる**ブレイク＆リジェクションピンポイントエントリー**。 |
| **ハードコードされた変数** | すべて `strategy_params.json` に外出しし、動的リロード対応。 |
| **PC再起動で停止する** | `run_vps.bat` による自動再起動ループ ＆ VPS完全対応パッケージ化。 |
