# ⚡ VELOCITY SCALPER: Complete cPanel Shared Hosting Deployment Guide

This guide walks you step-by-step through deploying **Velocity Scalper** to a cPanel shared hosting account using cPanel's native **"Setup Python App"** (CloudLinux Phusion Passenger).

---

## 📁 What is in this Folder?

This `cpanel_deploy` folder is fully self-contained and pre-configured for cPanel. It contains **only** the production files:

| File / Folder | Purpose in cPanel |
| :--- | :--- |
| `passenger_wsgi.py` | **Entry point** for cPanel Phusion Passenger. Bridges FastAPI to WSGI and auto-starts the trading engine. |
| `app.py` | FastAPI application & real-time REST API endpoints. |
| `engine.py` | Core execution engine & multi-pair scanner. |
| `strategy.py` | Strategy indicators, entry/exit logic, break-even trigger. |
| `config.py` | Bot parameters and environment variable loader. |
| `binance_client.py` | High-speed Binance Futures / Spot REST API client. |
| `indicators.py` | Vectorized EMA, ATR, Bollinger Bands, RSI math. |
| `data_recorder.py` | Tick and trade journey trajectory logger. |
| `run_daemon.py` | Standalone CLI runner for cPanel Cron Jobs / Terminal. |
| `requirements.txt` | Production dependencies (including `a2wsgi` for Passenger). |
| `bot_state.json` | Starting account state ($100 benchmark, 0 positions). |
| `.env` & `.env.example` | Trading mode (`PAPER` or `LIVE_FUTURES`) and API keys. |
| `web/` | Web dashboard UI (`index.html`, `style.css`, `app.js`). |
| `logs/` & `data/` | Runtime directories for logs and tick recordings. |

---

## 🚀 Step-by-Step Deployment Instructions

### Step 1: Create a Subdomain (Recommended)
1. In your cPanel dashboard, go to **Domains** &rarr; **Domains** (or **Subdomains**).
2. Create a subdomain, e.g. `scalper.yourdomain.com` (or `bot.yourdomain.com`).
3. Set the Document Root to a folder, e.g., `/home/YOUR_USER/scalper`.

---

### Step 2: Upload Files to cPanel
1. In cPanel, open **File Manager**.
2. Navigate to your app directory (e.g. `/home/YOUR_USER/scalper/`).
3. Upload `cpanel_deploy.zip` (found inside your project folder) or upload all files from this folder.
4. If you uploaded the zip, right-click `cpanel_deploy.zip` and click **Extract**.
5. Ensure `passenger_wsgi.py`, `app.py`, and the `web` folder are directly in the root of your application folder.

---

### Step 3: Create the Python App in cPanel
1. In cPanel, search for **"Setup Python App"** (under the *Software* category) and click it.
2. Click **Create Application**:
   * **Python version:** Select **3.10** or **3.11** (recommended).
   * **Application root:** Enter your folder path (e.g., `scalper` or `public_html/scalper`).
   * **Application URL:** Select your subdomain (e.g., `scalper.yourdomain.com`).
   * **Application startup file:** Type `passenger_wsgi.py`
   * **Application Entry point:** Type `application`
3. Click **Create** at the top right.

---

### Step 4: Install Dependencies via cPanel GUI
1. Once the application is created, scroll down to the **Configuration files** section.
2. In the text box, type `requirements.txt` and click **Add**.
3. Click the **"Run Pip Install"** button next to `requirements.txt`.
4. Wait 30–60 seconds while cPanel installs FastAPI, pandas, numpy, uvicorn, and a2wsgi.
5. Once installation finishes, click the **"Restart"** button at the top of the page.

> **Alternative (via cPanel Terminal):**  
> If you have Terminal access in cPanel, copy the virtualenv activate command shown at the top of the Python App page:
> ```bash
> source /home/YOUR_USER/virtualenv/scalper/3.11/bin/activate
> cd /home/YOUR_USER/scalper
> pip install -r requirements.txt
> ```

---

### Step 5: Configure Your Trading Mode (`.env`)
1. In cPanel **File Manager**, ensure **"Show Hidden Files (dotfiles)"** is checked in Settings.
2. Edit `.env`:
   - For simulated live trading: Keep `TRADING_MODE=PAPER`
   - For real Binance Futures: Change to `TRADING_MODE=LIVE_FUTURES` and enter your Binance API keys.
3. Save changes, then click **Restart** in the cPanel Python App manager.

---

### Step 6: ⚠️ CRITICAL — Keep the Engine Scanning 24/7

> [!IMPORTANT]
> **Why this step is essential on Shared Hosting:**  
> On shared cPanel servers, Phusion Passenger automatically puts idle Python apps to sleep if no visitor loads the website for 10–15 minutes.  
> A trading bot must scan prices continuously every few seconds!

To prevent your shared hosting from sleeping, use one (or both) of these cPanel Cron Jobs:

#### Method A: HTTP Keep-Alive Ping (Easiest)
1. In cPanel, open **Cron Jobs**.
2. Under *Common Settings*, select **Once Per 5 Minutes (`*/5 * * * *`)** or **Once Per Minute (`* * * * *`)**.
3. In the Command field, enter:
   ```bash
   curl -s https://scalper.yourdomain.com/api/status > /dev/null 2>&1
   ```
4. Click **Add New Cron Job**.  
   *Every time this cron runs, it pings your API, keeping the Passenger Python process alive and active.*

#### Method B: Standalone Daemon Cron (100% Fail-Safe)
If your host aggressive kills background threads in Passenger, run the independent `run_daemon.py` via Cron:
1. In cPanel **Cron Jobs**, set schedule to **Once Per 5 Minutes (`*/5 * * * *`)**:
2. In the Command field, enter (replace `YOUR_USER` with your cPanel username):
   ```bash
   pgrep -f run_daemon.py > /dev/null || /home/YOUR_USER/virtualenv/scalper/3.11/bin/python /home/YOUR_USER/scalper/run_daemon.py >> /home/YOUR_USER/scalper/logs/daemon.log 2>&1 &
   ```
3. This ensures that if the engine ever stops, cPanel's cron will immediately relaunch it in the background!

---

## 🔍 How to Verify Everything is Running

1. Open your browser and go to your app URL:  
   `https://scalper.yourdomain.com`
2. You will see the **Velocity Scalper** dashboard.
3. Check the **Engine Live Feed** terminal at the bottom — you should see scans executing every few seconds across all 6 crypto pairs (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `DOGEUSDT`, `LINKUSDT`).

---

## 🛡️ Shared Hosting vs VPS: Important Notes
* **Outbound Binance API Access:** Some shared web hosts block outgoing requests to external crypto APIs or have strict firewall rules. To test if your cPanel host allows connections to Binance, run this in cPanel Terminal:
  ```bash
  curl -I https://fapi.binance.com/fapi/v1/ping
  ```
  If it returns `HTTP/2 200`, your host has full access.
* **Process CPU Limits:** If your shared hosting plan has strict CloudLinux LVE CPU limits (e.g. 25% CPU quota), the engine's 3-second sleep cycle is designed to consume <1% CPU.
