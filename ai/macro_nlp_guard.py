import datetime
import json
from google import genai
from typing import Tuple, Dict, Any, Optional
from config import settings

class MacroNLPGuard:
    """
    【プロ仕様AI安全門番 - 超低トークン消費アーキテクチャ】
    
    1. シグナル成立時のみ稼働（毎秒/毎分の無駄撃ちゼロ）
    2. TTLキャッシュ機構（同一判定を20分間キャッシュし、APIコールを劇的に削減）
    3. thinking_budget=0 設定（Gemini 2.5 Flashの思考トークンを0にし、消費を最小化）
    4. プロンプト超圧縮（入力約60トークン、出力約30〜50トークンに極限まで圧縮）
    """
    def __init__(self, cache_ttl_minutes: int = 20):
        self.cache_ttl_minutes = cache_ttl_minutes
        self.last_check_time: Optional[datetime.datetime] = None
        self.cached_result: Optional[Tuple[bool, str]] = None

        try:
            self.client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_VERTEX_LOCATION
            )
            self.model_name = settings.VERTEX_MODEL_NAME
            self.available = True
        except Exception as e:
            print(f"[AI GUARD WARNING] Vertex AI Client init error: {e}")
            self.available = False

    def check_macro_safety(self, symbol: str = "XAUUSD") -> Tuple[bool, str]:
        """
        現在の市場環境においてトレードを許可（PASS）するか、一時停止（HALT）するかを判定。
        キャッシュが有効な場合はAPIを呼ばず即座にキャッシュを返してトークンを完全節約。
        """
        now = datetime.datetime.now()

        # --- トークン節約: キャッシュ判定 ---
        if self.cached_result is not None and self.last_check_time is not None:
            elapsed_minutes = (now - self.last_check_time).total_seconds() / 60.0
            if elapsed_minutes < self.cache_ttl_minutes:
                # キャッシュ有効期間内はAPI呼び出しゼロ（トークン消費ゼロ）
                allowed, reason = self.cached_result
                remaining = int(self.cache_ttl_minutes - elapsed_minutes)
                return allowed, f"{reason} [キャッシュ有効: 残り{remaining}分]"

        if not self.available:
            return True, "AI Guard Offline (Passed by fallback)"

        # --- プロンプト超圧縮（入力トークン数を約60トークンに極小化） ---
        now_jst = now.strftime("%Y-%m-%d %H:%M")
        prompt = (
            f"JST:{now_jst} Asset:{symbol} (Gold)\n"
            "Evaluate if imminent extreme shocks (active war crisis, surprise rate hike, FOMC/NFP/CPI within 20m) "
            "make trading reckless right now. Normal daily volatility and minor news must return allow:true.\n"
            'Output JSON only: {"allow": true, "reason": "簡潔な日本語理由"}'
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                    "max_output_tokens": 120,
                    "thinking_config": {
                        "thinking_budget": 0  # 思考トークン消費を0にして超省トークン化
                    }
                }
            )
            res = json.loads(response.text)
            allowed = bool(res.get("allow", True))
            reason = str(res.get("reason", "マクロ環境正常"))

            # キャッシュ更新
            self.cached_result = (allowed, reason)
            self.last_check_time = now
            return allowed, reason

        except Exception as e:
            # 万が一のAPIエラー時は安全にPASS（クオンツ側のハードSLで守る）
            return True, f"AI Guard check bypass ({e})"
