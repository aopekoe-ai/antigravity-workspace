import hmac
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.dashboard_ui import get_dashboard_html


class MacroWebhookStore:
    """
    TradingView Webhook 受信シグナルをスレッドセーフ＆永続キャッシュ管理するストア。
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
        with self._lock:
            if kind in ("momentum", "smt") and isinstance(self._state.get(kind), dict):
                self._state[kind]["consumed"] = True
                self._save_cache_unlocked()


class TVWebhookServer:
    """
    TradingView Webhook 受信 ＆ クオンツ運用Webダッシュボード統合サーバー (Port 80 -> 8000)
    - /tv-webhook : TradingView アラート受信 (token認証)
    - /dashboard  : スマホ＆PC対応 4タブ管理画面
    - /api/*      : リアルタイム状態取得・What-Ifバックテスト・方針変更・MT5口座切替API
    """

    def __init__(
        self,
        store: MacroWebhookStore,
        secret_token: str,
        dashboard_key: Optional[str] = None,
        api_dispatcher: Optional[Callable[[str, str, Dict[str, Any]], Dict[str, Any]]] = None,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        self.store = store
        self.secret_token = secret_token
        self.dashboard_key = dashboard_key or secret_token
        self.api_dispatcher = api_dispatcher
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._sec_lock = threading.Lock()
        self._failed_ips: Dict[str, list] = {}
        self._banned_ips: Dict[str, float] = {}

    def _is_ip_banned(self, ip: str) -> bool:
        now_ts = time.time()
        with self._sec_lock:
            ban_until = self._banned_ips.get(ip, 0.0)
            if ban_until > now_ts:
                return True
            if ban_until > 0:
                self._banned_ips.pop(ip, None)
            return False

    def _record_auth_failure(self, ip: str) -> None:
        now_ts = time.time()
        with self._sec_lock:
            arr = [ts for ts in self._failed_ips.get(ip, []) if now_ts - ts < 600.0]
            arr.append(now_ts)
            self._failed_ips[ip] = arr
            if len(arr) >= 6:
                self._banned_ips[ip] = now_ts + 86400.0  # 24時間IPバン
                print(f"🛡️ [SECURITY IP BAN] ブルートフォース検知によりIP {ip} を24時間遮断しました。")

    def _clear_auth_failure(self, ip: str) -> None:
        with self._sec_lock:
            self._failed_ips.pop(ip, None)

    def _build_handler(self):
        store = self.store
        secret_token = self.secret_token
        dashboard_key = self.dashboard_key
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _add_security_headers(self) -> None:
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")

            def _send_json(self, status_code: int, body: Dict[str, Any]) -> None:
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self._add_security_headers()
                self.end_headers()
                self.wfile.write(raw)

            def _send_html(self, status_code: int, html: str) -> None:
                raw = html.encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self._add_security_headers()
                self.end_headers()
                self.wfile.write(raw)

            def _check_dashboard_auth(self, query_str: str, payload: Optional[Dict[str, Any]] = None) -> bool:
                client_ip = self.client_address[0]
                if server_ref._is_ip_banned(client_ip):
                    return False
                qs = urllib.parse.parse_qs(query_str)
                q_key = (qs.get("key") or [""])[0]
                h_key = self.headers.get("X-Dashboard-Key") or ""
                p_key = str((payload or {}).get("key") or "")
                provided = (q_key or h_key or p_key).strip()
                if not dashboard_key:
                    return True
                ok = hmac.compare_digest(provided, dashboard_key) or hmac.compare_digest(provided, secret_token)
                if ok:
                    server_ref._clear_auth_failure(client_ip)
                elif provided:
                    server_ref._record_auth_failure(client_ip)
                return ok

            def do_GET(self) -> None:
                client_ip = self.client_address[0]
                if server_ref._is_ip_banned(client_ip):
                    self._send_json(429, {"error": "ip_temporarily_blocked_by_security_guard"})
                    return

                parts = self.path.split("?", 1)
                path = parts[0]
                q_str = parts[1] if len(parts) > 1 else ""

                if path in ("/health", "/"):
                    snap = store.get_snapshot()
                    last_ts = float(snap.get("last_any_ts", 0.0))
                    age_sec = round(time.time() - last_ts, 1) if last_ts > 0 else None
                    self._send_json(200, {
                        "status": "ok",
                        "service": "xauusd-macro-webhook-and-dashboard",
                        "received_count": snap.get("received_count", 0),
                        "last_signal_age_sec": age_sec,
                    })
                    return

                # Discord ワンタップ決裁エンドポイント (HMAC-SHA256 署名検証)
                if path == "/api/ic/decide":
                    qs = urllib.parse.parse_qs(q_str)
                    m_id = (qs.get("meeting_id") or [""])[0]
                    choice = (qs.get("choice") or [""])[0]
                    exp_s = (qs.get("exp") or ["0"])[0]
                    sig = (qs.get("sig") or [""])[0]
                    if server_ref.api_dispatcher:
                        res = server_ref.api_dispatcher("POST", "/api/ic/decide_signed", {
                            "meeting_id": m_id,
                            "choice": choice,
                            "exp": int(exp_s) if exp_s.isdigit() else 0,
                            "sig": sig,
                            "client_ip": client_ip,
                        })
                        if not res.get("success"):
                            server_ref._record_auth_failure(client_ip)
                        dash_url = f"/dashboard?key={dashboard_key}"
                        status_color = "#10b981" if res.get("success") else "#ef4444"
                        title_txt = "✅ 投資委員会・オーナー決裁完了" if res.get("success") else "⚠️ 決裁エラー"
                        html_page = (
                            "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>"
                            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                            f"<title>{title_txt}</title>"
                            "<style>body{background:#0b0f17;color:#e2e8f0;font-family:sans-serif;padding:24px;display:flex;justify-content:center;align-items:center;min-height:85vh;margin:0}"
                            f".card{{background:#151c2c;border:2px solid {status_color};border-radius:16px;padding:24px;max-width:480px;width:100%;box-shadow:0 10px 30px rgba(0,0,0,0.5)}}"
                            f"h2{{color:{status_color};margin-top:0;font-size:20px}}"
                            "p{line-height:1.6;font-size:14px;color:#cbd5e1}"
                            ".btn{display:block;text-align:center;background:#3b82f6;color:#fff;text-decoration:none;padding:14px;border-radius:10px;font-weight:bold;margin-top:20px}"
                            "</style></head><body><div class='card'>"
                            f"<h2>{title_txt}</h2>"
                            f"<p><strong>結果:</strong> {res.get('message', '')}</p>"
                            f"<p>{res.get('summary_ja', '')}</p>"
                            f"<a class='btn' href='{dash_url}'>📱 クオンツ管理ダッシュボードを開く</a>"
                            "</div></body></html>"
                        )
                        self._send_html(200 if res.get("success") else 403, html_page)
                    else:
                        self._send_json(503, {"error": "dispatcher_not_ready"})
                    return

                if path == "/dashboard":
                    if not self._check_dashboard_auth(q_str):
                        self._send_html(
                            403,
                            "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>403 Restricted</title></head>"
                            "<body style='background:#0b0f17;color:#94a3b8;font-family:sans-serif;text-align:center;padding-top:20vh'>"
                            "<h3>🔒 Protected Institutional Quant Terminal</h3><p>有効なアクセスキー付きURLからアクセスしてください。</p></body></html>",
                        )
                        return
                    self._send_html(200, get_dashboard_html())
                    return

                if path.startswith("/api/"):
                    if not self._check_dashboard_auth(q_str):
                        self._send_json(401, {"error": "unauthorized"})
                        return
                    if server_ref.api_dispatcher:
                        try:
                            res = server_ref.api_dispatcher("GET", path, {})
                            self._send_json(200, res)
                        except Exception as e:
                            self._send_json(500, {"error": str(e)})
                    else:
                        self._send_json(503, {"error": "dispatcher_not_ready"})
                    return

                self._send_json(404, {"error": "not_found"})

            def do_POST(self) -> None:
                client_ip = self.client_address[0]
                if server_ref._is_ip_banned(client_ip):
                    self._send_json(429, {"error": "ip_temporarily_blocked_by_security_guard"})
                    return

                parts = self.path.split("?", 1)
                path = parts[0]
                q_str = parts[1] if len(parts) > 1 else ""

                try:
                    content_len = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    content_len = 0

                if content_len < 0 or content_len > 32768:
                    self._send_json(400, {"error": "invalid_payload_size"})
                    return

                raw_bytes = self.rfile.read(content_len) if content_len > 0 else b"{}"
                try:
                    payload = json.loads(raw_bytes.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("JSON root must be object")
                except Exception:
                    self._send_json(400, {"error": "invalid_json"})
                    return

                # 1. TradingView Webhook
                if path in ("/tv-webhook", "/webhook"):
                    provided_token = str(
                        payload.get("token") or self.headers.get("X-Webhook-Token") or ""
                    ).strip()

                    if not secret_token or not hmac.compare_digest(provided_token, secret_token):
                        server_ref._record_auth_failure(client_ip)
                        print(f"[TV WEBHOOK REJECTED] 不正トークンからのアクセス (IP: {client_ip})")
                        self._send_json(401, {"error": "unauthorized"})
                        return
                    server_ref._clear_auth_failure(client_ip)

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
                    return

                # 2. Dashboard Control & Lab API
                if path.startswith("/api/"):
                    if not self._check_dashboard_auth(q_str, payload):
                        self._send_json(401, {"error": "unauthorized"})
                        return
                    if server_ref.api_dispatcher:
                        try:
                            res = server_ref.api_dispatcher("POST", path, payload)
                            self._send_json(200, res)
                        except Exception as e:
                            self._send_json(500, {"error": str(e)})
                    else:
                        self._send_json(503, {"error": "dispatcher_not_ready"})
                    return

                self._send_json(404, {"error": "not_found"})

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
            print(f"📡 [TV WEBHOOK & DASHBOARD READY] 起動完了 (listen={self.host}:{self.port}, paths=/tv-webhook, /dashboard)")
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
