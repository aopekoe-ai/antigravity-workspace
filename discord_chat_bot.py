import discord
import sys
import os
import datetime
from google import genai
import config
import mt5_bridge
import MetaTrader5 as mt5

# Windowsコンソールの文字化け防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Vertex AIクライアントの初期化 (us-central1: Gemini 2.5 Flash)
ai_client = genai.Client(
    vertexai=True,
    project=config.GCP_PROJECT_ID,
    location=config.GCP_VERTEX_LOCATION
)

intents = discord.Intents.default()
intents.message_content = True  # メッセージ内容を読み取る権限
bot = discord.Client(intents=intents)

SYSTEM_PERSONA = """
あなたは「XAU/USD AI Hedge Fund System」の専属AIアナリスト兼プログラミングアシスタントです。
ユーザーはDiscordからあなたに相場状況の質問、トレードロジックの相談、Pythonコードの作成依頼などを日本語で行います。

あなたの特徴:
1. 金融工学・クオンツ取引・ゴールド（XAU/USD）の相場力学（米金利TIPS、DXY、SMC、流動性スイープ、動的MAなど）に精通したプロフェッショナルな視点で回答します。
2. プログラミングの依頼があれば、クリーンで実行可能なPythonコードを丁寧な解説付きで返信します。
3. 常に敬意を払い、親しみやすく、わかりやすい日本語で回答します。
"""

def get_current_market_summary():
    """現在のMT5のXAUUSD価格とスプレッドを取得してコンテキストに追加"""
    try:
        if mt5_bridge.initialize_mt5():
            symbol = config.DEFAULT_SYMBOL
            tick = mt5.symbol_info_tick(symbol)
            positions = mt5.positions_get(symbol=symbol)
            mt5.shutdown()
            if tick:
                spread = round((tick.ask - tick.bid) / 0.10, 1)
                pos_count = len(positions) if positions else 0
                return f"\n[現在のリアルタイム相場情報: {symbol} Ask={tick.ask:.2f}, Bid={tick.bid:.2f}, スプレッド={spread} pips, 現在のオープンポジション数={pos_count}]"
    except Exception:
        pass
    return ""

def log_to_antigravity_notes(user_name: str, question: str, answer: str):
    """Antigravityと連携するために、会話履歴をローカル共有ファイルに追記保存"""
    notes_file = os.path.join(os.path.dirname(__file__), "discord_notes.md")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n\n### 💬 [{timestamp}] {user_name} からの質問\n**Q**: {question}\n\n**A (AI)**:\n{answer}\n\n---"
    try:
        with open(notes_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print(f"[NOTES ERROR] {e}")

@bot.event
async def on_ready():
    print("==================================================")
    print(f"🤖 Discord 対話型 AI Bot がオンラインになりました！")
    print(f"ログインアカウント: {bot.user.name} (ID: {bot.user.id})")
    print("メンション (@Bot) または '?質問' で回答します。")
    print("==================================================")

@bot.event
async def on_message(message: discord.Message):
    # 自身からのメッセージは無視
    if message.author == bot.user:
        return

    # ボットへのメンション、または '?' で始まるメッセージに反応
    is_mentioned = bot.user in message.mentions
    is_question = message.content.startswith("?") or message.content.startswith("？")

    if is_mentioned or is_question:
        prompt_text = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if is_question:
            prompt_text = prompt_text[1:].strip()

        if not prompt_text:
            await message.reply("こんにちは！何かご質問やプログラムの作成依頼などがあれば教えてくださいね。")
            return

        async with message.channel.typing():
            market_context = get_current_market_summary()
            full_prompt = f"{market_context}\n\nユーザーからの質問:\n{prompt_text}"

            try:
                response = ai_client.models.generate_content(
                    model=config.VERTEX_MODEL_NAME,
                    contents=full_prompt,
                    config={"system_instruction": SYSTEM_PERSONA, "temperature": 0.4}
                )
                answer_text = response.text

                # Discordの文字数制限 (2000文字) 対応
                if len(answer_text) <= 1950:
                    await message.reply(answer_text)
                else:
                    # 2000文字を超える場合は分割送信
                    for i in range(0, len(answer_text), 1900):
                        await message.channel.send(answer_text[i:i+1900])

                # Antigravity連携ノートに記録
                log_to_antigravity_notes(message.author.display_name, prompt_text, answer_text)

            except Exception as e:
                print(f"[BOT AI ERROR] {e}")
                await message.reply(f"申し訳ありません、回答の生成中にエラーが発生しました: {e}")

if __name__ == "__main__":
    bot_token = getattr(config, "DISCORD_BOT_TOKEN", None)
    if not bot_token or bot_token == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("[SETUP REQUIRED] config.py に DISCORD_BOT_TOKEN を設定してください。")
    else:
        bot.run(bot_token)
