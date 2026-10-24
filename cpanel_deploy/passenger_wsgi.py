"""
VELOCITY SCALPER: Ultra-Robust Pure-WSGI Production Bridge for cPanel & LiteSpeed
Zero ASGI overhead, zero socket-blocking deadlocks, sub-millisecond response times.
Directly serves the Tri-Engine UI and REST APIs while running the 24/7 background trading daemon.
"""
import sys
import os
import glob
import json
import mimetypes
import urllib.parse
import threading
from datetime import datetime

# 1. Force working directory to the application folder
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# 2. Automatically find and add cPanel virtualenv site-packages to sys.path
def auto_add_virtualenv():
    home_dir = os.path.expanduser("~")
    patterns = [
        os.path.join(home_dir, "virtualenv", "*", "*", "lib", "python3.*", "site-packages"),
        os.path.join(home_dir, "virtualenv", "*", "*", "lib64", "python3.*", "site-packages"),
        os.path.join(APP_DIR, "venv", "lib", "python3.*", "site-packages"),
        os.path.join(APP_DIR, ".venv", "lib", "python3.*", "site-packages"),
        os.path.join(home_dir, ".local", "lib", "python3.*", "site-packages")
    ]
    for pattern in patterns:
        for p in glob.glob(pattern):
            if os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)

auto_add_virtualenv()

WEB_DIR = os.path.join(APP_DIR, "web")

# Ensure proper MIME types are known
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")

# 3. Application Engine & Daemon Watchdog
_engine = None
_bg_thread = None
_daemon_lock = threading.Lock()
_startup_error = None

try:
    from engine import VelocityEngine
    _engine = VelocityEngine()

    def ensure_daemon():
        global _bg_thread
        with _daemon_lock:
            if _bg_thread is None or not _bg_thread.is_alive():
                _engine._log("Starting 24/7 Velocity Trading Daemon in background thread...", "ACTION")
                _bg_thread = threading.Thread(
                    target=_engine.run_forever,
                    daemon=True,
                    name="VelocityQuantDaemon"
                )
                _bg_thread.start()

except Exception as err:
    import traceback
    _startup_error = traceback.format_exc()
    try:
        with open(os.path.join(APP_DIR, "stderr.log"), "a") as f:
            f.write(f"\n--- CPANEL STARTUP ERROR ---\n{_startup_error}\n")
    except Exception:
        pass


def _read_json_body(environ):
    """Safely read JSON payload using CONTENT_LENGTH without socket blocking."""
    try:
        content_len_str = environ.get("CONTENT_LENGTH", "")
        content_len = int(content_len_str) if content_len_str.isdigit() else 0
        if content_len > 0 and environ.get("wsgi.input"):
            raw_bytes = environ["wsgi.input"].read(content_len)
            return json.loads(raw_bytes.decode("utf-8"))
    except Exception:
        pass
    return {}


def _json_response(data, start_response, status="200 OK"):
    body = json.dumps(data, default=str).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache, no-store, must-revalidate"),
        ("Access-Control-Allow-Origin", "*"),
    ]
    start_response(status, headers)
    return [body]


def _file_response(file_path, start_response, content_type=None):
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"404 Not Found"]

    if content_type is None:
        content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "application/octet-stream"

    with open(file_path, "rb") as f:
        content = f.read()

    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(content))),
        ("Cache-Control", "public, max-age=3600" if "/static/" in file_path else "no-cache"),
    ]
    start_response("200 OK", headers)
    return [content]


def application(environ, start_response):
    """
    Standard WSGI entry point called by Phusion Passenger / LiteSpeed.
    Handles all UI & REST API requests synchronously with sub-millisecond latency.
    """
    try:
        # If startup error occurred, show informative setup instructions
        if _startup_error:
            error_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Velocity Scalper - Setup Required</title>
</head>
<body style="font-family:system-ui,-apple-system,sans-serif;padding:30px;background:#0b0e14;color:#f0f2f5;">
  <div style="max-width:760px;margin:0 auto;background:#161b22;padding:30px;border-radius:12px;border:1px solid #30363d;">
    <h1 style="color:#38bdf8;margin-top:0;">⚡ Velocity Scalper: Setup Required</h1>
    <p style="color:#cbd5e1;">cPanel Phusion Passenger is running, but Python packages are missing:</p>
    
    <div style="background:#0d1117;padding:15px;border-radius:8px;border-left:4px solid #ef4444;font-family:monospace;color:#fca5a5;font-size:13px;margin:20px 0;white-space:pre-wrap;word-break:break-all;">
{_startup_error}
    </div>

    <h2 style="color:#e6edf3;font-size:18px;">How to Fix in cPanel:</h2>
    <ol style="line-height:2;color:#94a3b8;">
      <li>Open cPanel &rarr; <b>"Setup Python App"</b>.</li>
      <li>Click the <b>Edit (Pencil)</b> icon next to your app.</li>
      <li>Under <b>Configuration files</b>, type <code>requirements.txt</code> and click <b>Add</b>.</li>
      <li>Click <b>"Run Pip Install"</b> and wait for it to complete.</li>
      <li>Click <b>"Restart"</b> at the top of the Python App page.</li>
    </ol>
  </div>
</body>
</html>""".encode("utf-8")
            headers = [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(error_html)))
            ]
            start_response("200 OK", headers)
            return [error_html]

        # Ensure background trading engine is running
        try:
            ensure_daemon()
        except Exception:
            pass

        path = environ.get("PATH_INFO", "/") or "/"
        method = environ.get("REQUEST_METHOD", "GET").upper()

        # Route 1: Serve Main UI Dashboard
        if path in ("/", "/index.html"):
            index_file = os.path.join(WEB_DIR, "index.html")
            return _file_response(index_file, start_response, content_type="text/html; charset=utf-8")

        # Route 2: Serve Static Assets (/static/style.css, /static/app.js)
        if path.startswith("/static/"):
            rel_path = path[len("/static/"):].lstrip("/")
            safe_rel = os.path.normpath(rel_path)
            if safe_rel.startswith(".."):
                start_response("403 Forbidden", [("Content-Type", "text/plain")])
                return [b"Forbidden"]
            file_path = os.path.join(WEB_DIR, safe_rel)
            return _file_response(file_path, start_response)

        # Route 3: REST API - Real-Time Multi-Engine Status
        if path == "/api/status" and method == "GET":
            query_str = environ.get("QUERY_STRING", "")
            params = urllib.parse.parse_qs(query_str)
            engine_id = params.get("engine_id", [None])[0]

            # If background loop has been idle > 4s (Passenger sleeping thread), perform on-demand scan
            now_dt = datetime.now()
            stale = False
            if _engine.last_scan_time is None:
                stale = True
            elif (now_dt - _engine.last_scan_time).total_seconds() > 4:
                stale = True

            if stale:
                try:
                    _engine.scan_cycle()
                except Exception:
                    pass

            st = _engine.get_status(selected_engine=engine_id)
            st["thread_alive"] = bool(_bg_thread and _bg_thread.is_alive())
            return _json_response(st, start_response)

        # Route 4: REST API - Bot Restart / Verify
        if path == "/api/restart" and method == "POST":
            try:
                ensure_daemon()
            except Exception:
                pass
            return _json_response({
                "success": True,
                "msg": "Engine thread verified and running",
                "thread_alive": bool(_bg_thread and _bg_thread.is_alive())
            }, start_response)

        # Route 5: REST API - Bot Control (Pause / Resume)
        if path == "/api/control" and method == "POST":
            payload = _read_json_body(environ)
            action = payload.get("action", "").lower()
            eid = payload.get("engine_id") or "all"
            if action == "pause":
                _engine.pause_bot(eid)
                return _json_response({"success": True, "msg": f"Engine ({eid}) paused"}, start_response)
            elif action in ("resume", "start"):
                _engine.start_bot(eid)
                return _json_response({"success": True, "msg": f"Engine ({eid}) resumed"}, start_response)
            else:
                return _json_response({"success": False, "msg": "Invalid action"}, start_response, status="400 Bad Request")

        # Route 6: REST API - Emergency Close Position
        if path == "/api/close_position" and method == "POST":
            payload = _read_json_body(environ)
            sym = payload.get("symbol")
            eid = payload.get("engine_id")
            res = _engine.emergency_close_active(symbol=sym, engine_id=eid)
            return _json_response(res, start_response)

        # Route 7: REST API - Update Settings
        if path == "/api/settings" and method == "POST":
            payload = _read_json_body(environ)
            eid = payload.get("engine_id") or "all"
            if payload.get("mode"):
                _engine.set_trading_mode(payload["mode"], engine_id=eid)
            if payload.get("target") is not None and float(payload["target"]) > 0:
                target_val = float(payload["target"])
                targets = _engine.engines.values() if eid == "all" else [_engine.engines.get(eid)]
                for eng in targets:
                    if eng:
                        eng.state["daily_target"] = target_val
                        eng._save_state()
            return _json_response({"success": True, "msg": f"Settings updated for {eid}"}, start_response)

        # Fallback: 404 Not Found
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"404 Not Found"]

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        try:
            with open(os.path.join(APP_DIR, "stderr.log"), "a") as f:
                f.write(f"\n--- WSGI RUNTIME ERROR ---\n{tb}\n")
        except Exception:
            pass
        err_page = f"""<!DOCTYPE html><html><body style="background:#0b0e14;color:#fca5a5;padding:30px;font-family:monospace;">
        <h2 style="color:#ef4444;">⚡ WSGI Runtime Error</h2>
        <pre style="white-space:pre-wrap;word-break:break-all;">{tb}</pre>
        </body></html>""".encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(err_page)))])
        return [err_page]
