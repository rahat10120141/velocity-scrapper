"""
VELOCITY SCALPER: FastAPI Application & Dashboard Server
Serves real-time REST APIs and responsive UI on port 8088.
"""
import os
import time
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from engine import VelocityEngine
from config import SERVER_HOST, SERVER_PORT

# Global Engine Instance & Execution Thread Watchdog
engine = VelocityEngine()
bg_thread = None
watchdog_stop_event = threading.Event()

def ensure_engine_thread():
    global bg_thread
    if bg_thread is None or not bg_thread.is_alive():
        engine._log("Starting Velocity execution daemon thread...", "ACTION")
        bg_thread = threading.Thread(target=engine.run_forever, daemon=True, name="VelocityExecutionDaemon")
        bg_thread.start()

def engine_watchdog():
    """Periodic watchdog ensuring engine thread stays running 24/7."""
    while not watchdog_stop_event.is_set():
        try:
            ensure_engine_thread()
        except Exception as e:
            try:
                engine._log(f"Watchdog error: {e}", "ERROR")
            except Exception:
                pass
        time.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start execution daemon and watchdog
    ensure_engine_thread()
    wd_thread = threading.Thread(target=engine_watchdog, daemon=True, name="VelocityWatchdog")
    wd_thread.start()
    yield
    watchdog_stop_event.set()

app = FastAPI(title="Velocity Scalper API", lifespan=lifespan)

# Mount Static Files
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.get("/")
def serve_index():
    index_file = os.path.join(WEB_DIR, "index.html")
    return FileResponse(index_file)

@app.get("/api/status")
def get_status():
    import json
    status_data = engine.get_status()
    status_data["thread_alive"] = bool(bg_thread and bg_thread.is_alive())
    clean_data = json.loads(json.dumps(status_data, default=str))
    return JSONResponse(clean_data)

@app.post("/api/restart")
def restart_engine():
    ensure_engine_thread()
    return {"success": True, "msg": "Engine thread verified and running", "thread_alive": bool(bg_thread and bg_thread.is_alive())}

class ControlPayload(BaseModel):
    action: str

@app.post("/api/control")
def handle_control(payload: ControlPayload):
    action = payload.action.lower()
    if action == "pause":
        engine.pause_bot()
        return {"success": True, "msg": "Bot paused"}
    elif action in ["resume", "start"]:
        engine.start_bot()
        return {"success": True, "msg": "Bot resumed"}
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

class ClosePayload(BaseModel):
    symbol: str = None

@app.post("/api/close_position")
def close_position(payload: ClosePayload = None):
    sym = payload.symbol if payload else None
    res = engine.emergency_close_active(sym)
    return JSONResponse(res)

class SettingsPayload(BaseModel):
    mode: str = None
    target: float = None

@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    if payload.mode:
        engine.set_trading_mode(payload.mode)
    if payload.target is not None and payload.target > 0:
        engine.state["daily_target"] = payload.target
        engine._save_state()
    return {"success": True, "msg": "Settings updated"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=SERVER_HOST, port=SERVER_PORT, log_level="info")
