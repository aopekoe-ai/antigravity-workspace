<!-- PORTABLE-BRAIN:START -->
# Portable Brain Adapter (Google Antigravity (AGY 2.0))
本プロジェクトは共通思考エンジン `.brain/` で駆動しています。作業時は以下を厳守してください：

1. **【??????OS補完 & `/compact` 耐性】** 着手前およびコンテキスト要約（`/compact`）直後は、要約文を過信せず必ず `.brain/DECISIONS_SNAPSHOT.md`（特にボツ案・先祖返り禁止リスト）と `.brain/current_task.md` を再読して前提補完・タスク更新を行う。
2. **【カナリー流5段階思考】** `.brain/pipeline.md` に従い、要求整理 → OOUI情報設計 → 3案発散（`.brain/workspace/latest_rationale.md` 記録）→ 本実装 → 監査の順に進める（軽微な1行修正を除く）。
3. **【極限省トークン】** `.brain/questions/` は `INDEX.md` の目次から、現在のステップに必要なファイルのみをピンポイントで開くこと（全量読込禁止）。
4. **【即時セーブ & 圧縮学習】** 仕様決定や却下案（ボツ理由）が出たターンは即座に `DECISIONS_SNAPSHOT.md` へ反映し、コード変更後は `python .brain/scripts/verify_gate.py` を実行する。修正指摘は該当 `q*.md` へ既存行と統合して圧縮上書きする。
<!-- PORTABLE-BRAIN:END -->
