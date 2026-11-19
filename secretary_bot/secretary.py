import asyncio
import json
import os
import sys
import subprocess
import gc
from datetime import datetime, time as dtime
from pathlib import Path

# WindowsコンソールでのUnicodeEncodeError防止
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import discord
from discord.ext import tasks

from project_scanner import get_active_projects
from conversation_scanner import get_sidebar_conversations
from antigravity_bridge import AntigravityBridge
from sync_logger import record_activity_for_desktop

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
BOT_TOKEN = config.get("discord_bot_token", "")
TARGET_ID = int(config.get("channel_id", 0))
ACTIVE_DAYS = int(config.get("active_days_threshold", 7))
BASE_DIRS = config.get("project_directories", [r"C:\Obsidian\LLM Folder\02_Projects"])
PERSONA_NAME = config.get("persona_name", "有栖川 乃愛")
MORNING_TIME_STR = config.get("morning_time", "09:00")
EVENING_TIME_STR = config.get("evening_time", "18:00")

# 超軽量Intents（省メモリ化）
intents = discord.Intents.default()
intents.message_content = True
intents.members = False
intents.presences = False

bot = discord.Client(intents=intents, max_messages=50)
bridge = AntigravityBridge()

resolved_channel = None
last_proposal_pending = False
last_proposed_plan = ""
last_target_conversation_id = ""
last_target_conversation_title = ""
last_target_project_path = ""
last_user_raw_instruction = ""

def resolve_target_channel():
    global resolved_channel
    if resolved_channel:
        return resolved_channel

    ch = bot.get_channel(TARGET_ID)
    if isinstance(ch, discord.TextChannel):
        resolved_channel = ch
        return resolved_channel

    guild = bot.get_guild(TARGET_ID)
    if not guild and bot.guilds:
        guild = bot.guilds[0]

    if guild:
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            resolved_channel = guild.system_channel
            return resolved_channel

        for text_ch in guild.text_channels:
            if text_ch.permissions_for(guild.me).send_messages:
                resolved_channel = text_ch
                return resolved_channel

    return None

class PlanApprovalView(discord.ui.View):
    def __init__(self, plan_text: str, conversation_id: str = "", conversation_title: str = "", project_path: str = "", raw_instruction: str = ""):
        super().__init__(timeout=86400)
        self.plan_text = plan_text
        self.conversation_id = conversation_id
        self.conversation_title = conversation_title
        self.project_path = project_path
        self.raw_instruction = raw_instruction or plan_text.split('\n')[0]

    @discord.ui.button(label="許可して実行", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        global last_proposal_pending
        last_proposal_pending = False

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        status_msg = await interaction.followup.send(
            f"🚀 **【実行開始】** 許可をいただきました！\n"
            f"📌 **追記先スレッド**: `{self.conversation_title}`\n"
            f"既存の会話にメッセージと実行結果を追記しています...\n*(完了まで少々お待ちください)*"
        )

        # ★ 既存の会話スレッド (conversation_id) に直接追記実行！
        result = await bridge.execute_plan(
            approved_plan=self.plan_text,
            conversation_id=self.conversation_id,
            project_path=self.project_path
        )

        # Obsidian活動ログにも同期保存
        try:
            record_activity_for_desktop(
                instruction=self.raw_instruction,
                plan=self.plan_text,
                result=result,
                project_path=self.project_path
            )
        except Exception as e:
            print(f"デスクトップ同期エラー: {e}")

        gc.collect()

        await send_long_message(
            interaction.channel,
            f"✨ **【作業完了報告】**\n"
            f"既存の会話スレッド **「{self.conversation_title}」** への追記が完了しました！\n"
            f"デスクトップアプリの画面上でも同じスレッドに履歴が反映されています。\n\n"
            f"```text\n{result[:1800]}\n```"
        )
        try:
            await status_msg.delete()
        except Exception:
            pass

    @discord.ui.button(label="要望・修正を伝える", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def modify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "承知しました！変更したい点や追加のご要望を、このチャンネルでそのまま返信してください。",
            ephemeral=True
        )

    @discord.ui.button(label="スキップ / 中止", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        global last_proposal_pending
        last_proposal_pending = False

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="~~（この提案はスキップされました）~~", view=self)
        await interaction.followup.send("提案をスキップしました。また何かあればお申し付けください！", ephemeral=True)


async def send_long_message(channel, text: str, view: discord.ui.View = None):
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
    for idx, chunk in enumerate(chunks):
        if idx == len(chunks) - 1 and view:
            await channel.send(chunk, view=view)
        else:
            await channel.send(chunk)


@tasks.loop(minutes=1)
async def scheduled_routine():
    global last_proposal_pending, last_proposed_plan, last_target_conversation_id, last_target_conversation_title, last_target_project_path, last_user_raw_instruction

    channel = resolve_target_channel()
    if not channel:
        return

    now_str = datetime.now().strftime("%H:%M")

    # 朝の定時提案 (09:00)
    if now_str == MORNING_TIME_STR:
        if last_proposal_pending and config.get("auto_silent_if_no_reaction", True):
            return

        actives, _ = get_sidebar_conversations(days_threshold=ACTIVE_DAYS)
        active_projects = get_active_projects(BASE_DIRS, days_threshold=ACTIVE_DAYS)

        if not actives and not active_projects:
            return

        summary_lines = ["【直近アクティブなConversations】"]
        for c in actives[:3]:
            summary_lines.append(f"- 会話: {c['title']} (更新: {c['last_modified_display']})")

        proposal_text = await bridge.create_morning_proposal("\n".join(summary_lines), persona_name=PERSONA_NAME)
        
        target_conv = actives[0] if actives else {"id": "", "title": "最新会話"}
        last_proposal_pending = True
        last_proposed_plan = proposal_text
        last_target_conversation_id = target_conv.get("id", "")
        last_target_conversation_title = target_conv.get("title", "最新会話")
        last_target_project_path = active_projects[0]["path"] if active_projects else ""
        last_user_raw_instruction = "朝の定時提案タスク"

        view = PlanApprovalView(
            plan_text=proposal_text,
            conversation_id=last_target_conversation_id,
            conversation_title=last_target_conversation_title,
            project_path=last_target_project_path,
            raw_instruction=last_user_raw_instruction
        )
        await send_long_message(
            channel,
            f"🌅 **【朝のブリーフィング】{PERSONA_NAME}**\n"
            f"📌 追記先スレッド: **{last_target_conversation_title}**\n\n{proposal_text}",
            view=view
        )
        gc.collect()

    # 夕方の進捗まとめ (18:00)
    elif now_str == EVENING_TIME_STR:
        actives, _ = get_sidebar_conversations(days_threshold=1)
        if not actives:
            return

        report = f"🌆 **【本日のまとめ】{PERSONA_NAME}**\n本日更新されたConversations:\n"
        for c in actives:
            report += f"・**{c['title']}** ({c['last_modified_display']} | {c['step_count']}ステップ)\n"
        report += "\n本日もお疲れ様でした！"

        await channel.send(report)
        gc.collect()


@bot.event
async def on_message(message: discord.Message):
    global last_proposal_pending, last_proposed_plan, last_target_conversation_id, last_target_conversation_title, last_target_project_path, last_user_raw_instruction

    if message.author == bot.user:
        return

    channel = resolve_target_channel()
    is_target_channel = (channel and message.channel.id == channel.id)
    is_mentioned = bot.user in message.mentions

    if not is_target_channel and not is_mentioned:
        return

    content = message.clean_content.replace(f"@{bot.user.display_name}", "").strip()
    if not content:
        return

    # ★ /restart コマンド
    if content.lower() in ("/restart", "/ reload", "/reload", "再起動"):
        await message.channel.send("🔄 秘書ボットを再起動しています... 数秒お待ちください。")
        restart_script = Path(__file__).parent / "restart_secretary.py"
        real_py = r"C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe"
        py_exe = real_py if os.path.exists(real_py) else sys.executable
        creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen([py_exe, str(restart_script)], creationflags=creation_flags)
        await bot.close()
        return

    # ★ /status コマンド
    if content.lower().startswith("/status") or content.lower().startswith("/ status"):
        actives, inactives = get_sidebar_conversations(days_threshold=ACTIVE_DAYS)

        embed = discord.Embed(
            title="📋 Antigravity Conversations 最新稼働状況",
            description=(
                f"サイドバーの会話スレッドのうち、**直近{ACTIVE_DAYS}日以内に更新があったもの**です。\n"
                f"アクティブ: **{len(actives)}件** ／ 休眠中: **{inactives}件**"
            ),
            color=0x2ECC71 if actives else 0x95A5A6,
            timestamp=datetime.now()
        )

        if not actives:
            embed.add_field(
                name="更新状況",
                value=f"直近{ACTIVE_DAYS}日以内に更新されたConversationsはありません。",
                inline=False
            )
        else:
            for i, c in enumerate(actives, start=1):
                name = f"🟢 {i}. {c['title']}"
                value = f"├ 最終更新: **{c['last_modified_display']}**\n└ ステップ数: `{c['step_count']:,}`"
                embed.add_field(name=name, value=value, inline=False)

        embed.set_footer(text=f"※1週間以上動いていない会話({inactives}件)は除外しています | 秘書: {PERSONA_NAME}")
        await message.channel.send(embed=embed)
        gc.collect()
        return

    # 通常指示・相談
    async with message.channel.typing():
        actives, _ = get_sidebar_conversations(days_threshold=ACTIVE_DAYS)
        active_projects = get_active_projects(BASE_DIRS, days_threshold=ACTIVE_DAYS)

        # 関連する既存の会話スレッドをマッチング（キーワード判定）
        target_conv = None
        content_lower = content.lower()

        for c in actives:
            # 会話タイトル内の単語が含まれているかチェック
            t_clean = c["title"].lower()
            keywords = [k for k in ["typescript", "ts", "xau", "trading", "ea", "漫画", "manga", "秘書", "secretary", "ソリューション", "要件"] if k in t_clean]
            if any(k in content_lower for k in keywords):
                target_conv = c
                break

        # マッチしなかった場合は、直近で一番新しいアクティブな既存会話を選択
        if not target_conv and actives:
            target_conv = actives[0]

        target_conv_id = target_conv["id"] if target_conv else ""
        target_conv_title = target_conv["title"] if target_conv else "最新の会話"

        context_str = f"【追記対象の既存会話スレッド】: {target_conv_title}\n"
        if target_conv and target_conv.get("preview"):
            context_str += f"最近のやり取り: {target_conv['preview']}\n"

        matched_path = active_projects[0]["path"] if active_projects else ""

        plan_text = await bridge.create_plan(content, context_str, persona_name=PERSONA_NAME)

        last_proposed_plan = plan_text
        last_target_conversation_id = target_conv_id
        last_target_conversation_title = target_conv_title
        last_target_project_path = matched_path
        last_user_raw_instruction = content
        last_proposal_pending = True

        view = PlanApprovalView(
            plan_text=plan_text,
            conversation_id=target_conv_id,
            conversation_title=target_conv_title,
            project_path=matched_path,
            raw_instruction=content
        )
        await send_long_message(
            message.channel,
            f"💡 **【行動計画のすり合わせ】{PERSONA_NAME}**\n"
            f"📌 **追記先スレッド**: **`{target_conv_title}`**\n"
            f"*(※新しいスレッドは作らず、既存のこのスレッドに直接追記されます)*\n\n{plan_text}",
            view=view
        )

    gc.collect()


@bot.event
async def on_ready():
    print(f"==================================================")
    print(f"  Antigravity Secretary Bot 起動完了")
    print(f"  ログイン名: {bot.user} (ID: {bot.user.id})")
    print(f"  ペルソナ: {PERSONA_NAME}")
    print(f"  既存スレッド直接追記モード: 有効")
    print(f"  省メモリ待機中（目標メモリ: ~30MB）")
    print(f"==================================================")
    
    channel = resolve_target_channel()
    if channel:
        print(f"  接続先チャンネル: #{channel.name} (ID: {channel.id})")

    if not scheduled_routine.is_running():
        scheduled_routine.start()


if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("エラー: config.json に Discord Bot Token が設定されていません。")
    else:
        bot.run(BOT_TOKEN)
