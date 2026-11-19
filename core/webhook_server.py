import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional


class MacroWebhookStore:
    """
    TradingView Webhook 受信シグナルをスレッドセーフ＆永続キャッシュ管理するストア。
    - オンメモリ高速読み出し（レイテンシ < 1ms）
    - ログディレクトリへのアトミック保存（コンテナ再起動時も最新シグナルを復元）
    """

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "last_any_ts": 0.0,
            "heartbeat": None,
            "momentum": None,
            "smt": None,
            "received_count": 0,
        }
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            if self.cache_path.exists():
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._state.update(data)
        except Exception as e:
            print(f"[TV WEBHOOK WARN] キャッシュ読込スキップ: {e}")

    def _save_cache_unlocked(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.cache_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.cache_path)
        except Exception as e:
            print(f"[TV WEBHOOK WARN] キャッシュ保存失敗: {e}")

    def record_signal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now_ts = time.time()
        sig_type = str(payload.get("signal_type", "MACRO_BIAS_HEARTBEAT")).upper().strip()
        direction = str(payload.get("direction", "NEUTRAL")).upper().strip()

        def _to_float(val: Any, default: float = 0.0) -> float:
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        entry = {
            "signal_type": sig_type,
            "direction": direction,
            "dxy_z": _to_float(payload.get("dxy_z"), 0.0),
            "us10y_z": _to_float(payload.get("us10y_z"), 0.0),
            "us02y_z": _to_float(payload.get("us02y_z"), 0.0),
            "bias_score": max(-1.0, min(1.0, _to_float(payload.get("bias_score"), 0.0))),
            "strength": _to_float(payload.get("strength"), 1.0),
            "dxy_above_m5_ema20": bool(payload.get("dxy_above_m5_ema20", False)),
            "us10y_above_m5_ema20": bool(payload.get("us10y_above_m5_ema20", False)),
            "detail": str(payload.get("detail", "")),
            "symbol": str(payload.get("symbol", "XAUUSD")),
            "received_at": now_ts,
            "consumed": False,
        }

        with self._lock:
            self._state["last_any_ts"] = now_ts
            self._state["received_count"] = int(self._state.get("received_count", 0)) + 1

            # ハートビート情報はいずれのシグナル受信時にも最新マクロ環境として更新
            self._state["heartbeat"] = {
                "dxy_z": entry["dxy_z"],
                "us10y_z": entry["us10y_z"],
                "us02y_z": entry["us02y_z"],
                "bias_score": entry["bias_score"],
                "dxy_above_m5_ema20": entry["dxy_above_m5_ema20"],
                "us10y_above_m5_ema20": entry["us10y_above_m5_ema20"],
                "received_at": now_ts,
            }

            if sig_type == "MACRO_MOMENTUM" and direction in ("BUY", "SELL"):
                prev = self._state.get("momentum")
                # 同一方向の連続急変時は初検知時刻を引き継ぎ、クールダウン判定を正確化
                if prev and prev.get("direction") == direction and (now_ts - float(prev.get("received_at", 0.0))) < 240:
                    entry["first_seen_at"] = float(prev.get("first_seen_at", now_ts))
                else:
                    entry["first_seen_at"] = now_ts
                self._state["momentum"] = entry
            elif sig_type == "SMT_DIVERGENCE" and direction in ("BUY", "SELL"):
                self._state["smt"] = entry

            self._save_cache_unlocked()

        return entry

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def mark_consumed(self, kind: str) -> None:
        """約定完了したTVトリガーを消費済みにして多重発注を防止"""
        with self._lock:
            if kind in ("momentum", "smt") and isinstance(self._state.get(kind), dict):
                self._state[kind]["consumed"] = True
                self._save_cache_unlocked()


class TVWebhookServer:
    """
    Python標準ライブラリのみで稼働する超軽量・高信頼 TradingView Webhook サーバー。
    - 外部依存ゼロ（追加pip不要）
    - 応答速度 < 5ms（TradingViewの3秒タイムアウト制約を余裕でクリア）
    - text/plain および application/json 両対応（TradingView仕様対策）
    """

    def __init__(self, store: MacroWebhookStore, secret_token: str, host: str = "0.0.0.0", port: int = 8000):
        self.store = store
        self.secret_token = secret_token
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def _build_handler(self):
        store = self.store
        secret_token = self.secret_token

        class Handler(BaseHTTPRequestHandler):
            # 標準ログ出力の過剰スパムを抑制し、重要イベントのみ出力
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send_json(self, status_code: int, body: Dict[str, Any]) -> None:
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path in ("/health", "/"):
                    snap = store.get_snapshot()
                    last_ts = float(snap.get("last_any_ts", 0.0))
                    age_sec = round(time.time() - last_ts, 1) if last_ts > 0 else None
                    self._send_json(200, {
                        "status": "ok",
                        "service": "xauusd-macro-webhook",
                        "received_count": snap.get("received_count", 0),
                        "last_signal_age_sec": age_sec,
                    })
                else:
                    self._send_json(404, {"error": "not_found"})

            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                if path not in ("/tv-webhook", "/webhook"):
                    self._send_json(404, {"error": "not_found"})
                    return

                try:
                    content_len = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    content_len = 0

                if content_len <= 0 or content_len > 16384:
                    self._send_json(400, {"error": "invalid_payload_size"})
                    return

                raw_bytes = self.rfile.read(content_len)
                try:
                    payload = json.loads(raw_bytes.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("JSON root must be object")
                except Exception:
                    self._send_json(400, {"error": "invalid_json"})
                    return

                # 認証トークン検証（ボディ内 token または X-Webhook-Token ヘッダー）
                provided_token = str(
                    payload.get("token") or self.headers.get("X-Webhook-Token") or ""
                ).strip()

                if not secret_token or not hmac.compare_digest(provided_token, secret_token):
                    print(f"[TV WEBHOOK REJECTED] 不正トークンからのアクセス (IP: {self.client_address[0]})")
                    self._send_json(401, {"error": "unauthorized"})
                    return

                entry = store.record_signal(payload)
                print(
                    f"📡 [TV WEBHOOK RECEIVED] type={entry['signal_type']} dir={entry['direction']} "
                    f"dxy_z={entry['dxy_z']:+.2f} us10y_z={entry['us10y_z']:+.2f} bias={entry['bias_score']:+.2f}"
                )
                self._send_json(200, {
                    "status": "accepted",
                    "signal_type": entry["signal_type"],
                    "direction": entry["direction"],
                })

        return Handler

    def start(self) -> bool:
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), self._build_handler())
            self._server.daemon_threads = True
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="tv-webhook-server",
                daemon=True,
            )
            self._thread.start()
            print(f"📡 [TV WEBHOOK READY] 受信サーバー起動完了 (listen={self.host}:{self.port}, path=/tv-webhook)")
            return True
        except Exception as e:
            print(f"[TV WEBHOOK ERROR] サーバー起動失敗: {e}")
            return False

    def stop(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
