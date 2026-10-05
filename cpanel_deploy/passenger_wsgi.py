"""
VELOCITY SCALPER: Robust Phusion Passenger WSGI Bridge for cPanel
Bridges FastAPI (ASGI) to cPanel Phusion Passenger (WSGI) using a2wsgi.
"""
import sys
import os

# 1. Force working directory to the application folder so relative paths work
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# 2. Try importing dependencies
try:
    from a2wsgi import ASGIMiddleware
    from app import app, ensure_engine_thread

    # Create the WSGI wrapper around FastAPI
    asgi_handler = ASGIMiddleware(app)
    _daemon_initialized = False

    def application(environ, start_response):
        global _daemon_initialized
        # Lazily start background execution daemon after worker fork
        if not _daemon_initialized:
            _daemon_initialized = True
            try:
                ensure_engine_thread()
            except Exception as e:
                try:
                    with open(os.path.join(APP_DIR, "logs", "startup_error.log"), "a") as f:
                        f.write(f"Daemon startup error: {e}\n")
                except Exception:
                    pass

        return asgi_handler(environ, start_response)

except Exception as err:
    import traceback
    tb = traceback.format_exc()

    # Write error to stderr.log so it appears in cPanel logs
    try:
        with open(os.path.join(APP_DIR, "stderr.log"), "a") as f:
            f.write(f"\n--- STARTUP ERROR ---\n{tb}\n")
    except Exception:
        pass

    # Provide clear visual diagnosis in the browser instead of generic 500 error
    def application(environ, start_response):
        status = '200 OK'
        body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Velocity Scalper - Setup Diagnosis</title>
</head>
<body style="font-family:system-ui, -apple-system, sans-serif; padding:40px; background:#0b0e14; color:#f0f2f5;">
  <div style="max-width:760px; margin:0 auto; background:#161b22; padding:30px; border-radius:12px; border:1px solid #30363d;">
    <h1 style="color:#38bdf8; margin-top:0;">⚡ Velocity Scalper: Setup Diagnosis</h1>
    <p>Application loaded, but encountered an error initializing dependencies:</p>
    
    <div style="background:#0d1117; padding:15px; border-radius:8px; border-left:4px solid #ef4444; font-family:monospace; color:#fca5a5; font-size:13px; margin:20px 0; white-space:pre-wrap; word-break:break-all;">
{tb}
    </div>

    <h2 style="color:#e6edf3; font-size:18px;">How to Fix in cPanel:</h2>
    <ol style="line-height:2; color:#c9d1d9;">
      <li>Go to cPanel &rarr; <b>"Setup Python App"</b>.</li>
      <li>Click the <b>Edit</b> (pencil) icon next to your application.</li>
      <li>In the <b>Configuration files</b> box, type <code>requirements.txt</code> and click <b>Add</b>.</li>
      <li>Click <b>"Run Pip Install"</b> and wait for it to complete.</li>
      <li>Click <b>"Restart"</b> at the top of the Python App page.</li>
    </ol>
  </div>
</body>
</html>""".encode("utf-8")
        headers = [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(body)))
        ]
        start_response(status, headers)
        return [body]
