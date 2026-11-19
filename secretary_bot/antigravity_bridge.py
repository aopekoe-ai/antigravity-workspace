import asyncio
import os
import subprocess
from typing import Dict, Any, Optional

class AntigravityBridge:
    def __init__(self, agy_path: str = "agy"):
        self.agy_path = agy_path

    async def create_plan(self, user_instruction: str, project_context: str, persona_name: str = "秘書") -> str:
        """
        Phase 1: 計画立案（ファイル書き換えなし）
        """
        system_prompt = (
            f"あなたは有能な専属AI秘書（{persona_name}）です。"
            "ユーザーからプロジェクトに関する作業指示を受けました。"
            "【最重要ルール】現段階ではファイルの変更やコマンド実行は絶対に行わず、"
            "「これから何を行うか」の行動計画とすり合わせのみを行ってください。\n\n"
            "以下のフォーマットで簡潔・明瞭に出力してください：\n"
            "1. 【方針・概要】（何を実現するかを1〜2行で）\n"
            "2. 【変更・作成予定のファイル】（対象パスの箇条書き）\n"
            "3. 【確認・すり合わせ事項】（ユーザーに事前に判断してほしい点や質問があれば1〜2点。特になければ『特になし』）\n"
            "4. 秘書からの一言（「この内容でよろしければ、下の【許可して実行】ボタンを押してください」）"
        )

        full_prompt = (
            f"{system_prompt}\n\n"
            f"【関連する既存の会話・プロジェクト文脈】\n{project_context}\n\n"
            f"【ユーザーからの指示】\n{user_instruction}"
        )

        return await self._run_agy(full_prompt, mode="plan")

    async def create_morning_proposal(self, active_projects_summary: str, persona_name: str = "秘書") -> str:
        """
        朝の定時提案
        """
        prompt = (
            f"あなたは有能な専属AI秘書（{persona_name}）です。"
            "直近1週間以内に作業された会話・プロジェクトの状況を確認し、今日着手すべき「最も効果的な次の1アクション」を1件だけ厳選して提案してください。\n"
            "※長文は避け、要点のみをスッキリと伝えてください。\n\n"
            f"【直近アクティブな会話・プロジェクト情報】\n{active_projects_summary}\n\n"
            "出力形式：\n"
            "・朝の挨拶\n"
            "・今日おすすめのアクション（対象会話スレッド名、理由、具体的な作業内容）\n"
            "・『この作業を進めておきましょうか？』と問いかける結び"
        )
        return await self._run_agy(prompt, mode="plan")

    async def execute_plan(self, approved_plan: str, conversation_id: Optional[str] = None, project_path: Optional[str] = None) -> str:
        """
        Phase 2: 承認後の実行（既存の会話スレッドに直接追加）
        conversation_id が指定されている場合、新しいスレッドは作らず、既存スレッドに直接メッセージとタスクを追加します。
        """
        exec_prompt = (
            "【Discord秘書からの承認済みタスク実行】\n"
            "以下の計画がDiscord上で承認されました。既存の会話の文脈を踏まえ、"
            "計画に従って必要なファイル作成・コード編集・調査を実行し、完了させてください。\n\n"
            f"【承認された計画】\n{approved_plan}\n\n"
            "作業完了後、何を変更・作成したかの完了報告を簡潔に出力してください。"
        )

        extra_args = ["--dangerously-skip-permissions"]

        # ★ 既存の会話スレッドに直接追加する
        if conversation_id:
            extra_args.extend(["--conversation", conversation_id])

        if project_path and os.path.isdir(project_path):
            extra_args.extend(["--add-dir", project_path])

        return await self._run_agy(exec_prompt, mode="auto", extra_flags=extra_args)

    async def _run_agy(self, prompt: str, mode: str = "plan", extra_flags: Optional[list] = None) -> str:
        cmd = [
            self.agy_path,
            "-p", prompt,
            "--mode", mode
        ]
        if extra_flags:
            cmd.extend(extra_flags)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            output = stdout.decode('utf-8', errors='replace').strip()
            
            if not output and stderr:
                err_text = stderr.decode('utf-8', errors='replace').strip()
                return f"エラーが発生しました: {err_text}"
            return output
        except Exception as e:
            return f"Antigravityの呼び出しに失敗しました: {e}"
