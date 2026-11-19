# Antigravity 専属AI秘書 (Discord常駐・省メモリ版)

Antigravityで進行中のプロジェクトを自律監視し、先回り提案やすり合わせを行うDiscord常駐型の専属AI秘書です。

---

## 🌟 特徴

1. **超省メモリ常駐（アイドル時 約20MB〜30MB）**
   - 普段は軽量なDiscord接続のみで待機。
   - Antigravity本体は指示やボタン操作のあった瞬間だけオンデマンドで起動し、タスク完了後に即座にメモリをOSへ返却します。
2. **直近1週間（7日以内）のアクティブプロジェクト限定**
   - 昔の放置プロジェクトに関する通知は完全除外。今まさに動いているプロジェクトのみに集中します。
3. **安全な2段階実行（Two-Phase Execution）**
   - 指示を出してもいきなりコードを変更せず、まずは「行動計画（変更ファイル・方針・疑問点）」を提示してすり合わせ。
   - Discord上で **`[ ✅ 許可して実行 ]`** を押して初めてAntigravityがファイルを編集・実行します。
4. **通知爆発の完全防止**
   - 朝（09:00）の提案と夕方（18:00）のまとめの1日2回を基本とし、前回の提案に未反応の場合は追加通知を行いません。

---

## 🚀 セットアップ手順（約3分）

### ステップ1: Discord Bot の作成とトークン取得
1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセスしてログインします。
2. 右上の **「New Application」** を押し、適当な名前（例: `乃愛 (秘書)`）を入力して作成します。
3. 左メニューの **「Bot」** を選び、**「Reset Token」** を押して表示された **トークン** をコピーします。
4. 同じ「Bot」画面を少し下にスクロールし、**「Privileged Gateway Intents」** の **`MESSAGE CONTENT INTENT`** を **ON** にして「Save Changes」を押します。
5. 左メニューの **「OAuth2」** → **「URL Generator」** を開き：
   - SCOPES: **`bot`** にチェック
   - BOT PERMISSIONS: **`Send Messages`**, **`Send Messages in Threads`**, **`Read Message History`** にチェック
6. 下部に生成されたURLをブラウザで開き、自分のDiscordサーバーにBotを招待します。

---

### ステップ2: チャンネルIDの取得
1. Discordの「ユーザー設定」→「詳細設定」で **「開発者モード」** をONにします。
2. 秘書とやり取りしたいチャンネルを右クリックし、**「チャンネルIDをコピー」** をクリックします。

---

### ステップ3: 設定ファイル (`config.json`) の編集
`config.json` をメモ帳等で開き、コピーしたトークンとチャンネルIDを貼り付けます：

```json
{
  "discord_bot_token": "ここにコピーしたBotトークンを貼り付け",
  "channel_id": 123456789012345678,
  "active_days_threshold": 7,
  "morning_time": "09:00",
  "evening_time": "18:00",
  "project_directories": [
    "C:\\Obsidian\\LLM Folder\\02_Projects",
    "C:\\Obsidian\\LLM Folder\\01_Inbox"
  ],
  "persona_name": "有栖川 乃愛",
  "auto_silent_if_no_reaction": true
}
```

---

### ステップ4: 起動
`start_secretary.bat` をダブルクリックするだけで起動します！

> **PC起動時に自動で常駐させたい場合**:
> 1. キーボードで `Win + R` を押し、`shell:startup` と入力してEnterを押します。
> 2. 開いた「スタートアップ」フォルダに、`start_secretary.bat` のショートカットを配置してください。

---

## 💬 使い方

* **指示を出す場合**:
  - チャンネルで `@乃愛 〇〇画面のスタイルをTailwindで修正して` と発言するだけ。
  - 秘書が **変更予定ファイル** と **計画案** を返信し、ボタンが表示されます。
  - 内容を確認して **`[ ✅ 許可して実行 ]`** を押すと、Antigravityがバックグラウンドで作業を完了させます。
* **状態確認コマンド**:
  - `/status` と送信すると、直近7日以内に動いているプロジェクトと未完了ToDoが一覧表示されます。
