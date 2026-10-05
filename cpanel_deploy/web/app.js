/**
 * VELOCITY SCALPER: Frontend Real-Time Client Application
 * Polling /api/status every 2 seconds for ultra-responsive live dashboard updates.
 */

let isEngineRunning = true;

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    renderDashboard(data);
  } catch (err) {
    console.error("Error fetching engine status:", err);
  }
}

function renderDashboard(data) {
  // 1. Engine Running Status
  isEngineRunning = data.is_running;
  const statusPill = document.getElementById("engineStatusText");
  const pulseDot = document.getElementById("pulseDot");
  const btnToggle = document.getElementById("btnToggleEngine");
  const btnText = document.getElementById("btnToggleText");
  const btnIcon = document.getElementById("btnToggleIcon");

  if (data.is_running) {
    statusPill.textContent = "SYSTEM ACTIVE";
    pulseDot.style.background = "var(--profit-green)";
    pulseDot.style.boxShadow = "0 0 10px var(--profit-green)";
    btnToggle.className = "control-btn btn-pause";
    btnText.textContent = "Pause Bot";
    btnIcon.textContent = "⏸️";
  } else {
    statusPill.textContent = "ENGINE PAUSED";
    pulseDot.style.background = "var(--warning-amber)";
    pulseDot.style.boxShadow = "0 0 10px var(--warning-amber)";
    btnToggle.className = "control-btn btn-resume";
    btnText.textContent = "Resume Bot";
    btnIcon.textContent = "▶️";
  }

  // Trading Mode Pill
  document.getElementById("tradingModeText").textContent = data.trading_mode + " MODE";

  // 2. KPI Cards
  document.getElementById("valCurrentBalance").textContent = `$${data.current_balance.toFixed(2)}`;
  document.getElementById("valStartingBase").textContent = `$${data.starting_balance.toFixed(2)}`;

  const todayPnL = data.today_realized_pnl;
  const target = data.daily_target || 3.0;
  const pnlEl = document.getElementById("valTodayPnL");
  pnlEl.textContent = `${todayPnL >= 0 ? "+" : ""}$${todayPnL.toFixed(2)}`;
  pnlEl.className = `kpi-value ${todayPnL >= 0 ? "pnl-positive" : "pnl-negative"}`;

  // Target Progress Bar
  const pct = Math.min(100, Math.max(0, (todayPnL / target) * 100));
  document.getElementById("targetProgressBar").style.width = `${pct}%`;
  document.getElementById("targetProgressLabel").textContent = `Progress to $${target.toFixed(2)} Target: ${pct.toFixed(0)}%`;

  // Circuit Breaker Status
  const cbEl = document.getElementById("valCircuitStatus");
  if (data.circuit_breaker === "PROFIT_LOCKED") {
    cbEl.textContent = "🎯 PROFIT LOCKED";
    cbEl.style.color = "var(--accent-purple)";
  } else if (data.circuit_breaker === "LOSS_LOCKED") {
    cbEl.textContent = "🛡️ DEFENSE HALTED";
    cbEl.style.color = "var(--loss-red)";
  } else {
    cbEl.textContent = "NORMAL ACTIVE";
    cbEl.style.color = "var(--profit-green)";
  }

  // Win Rate
  document.getElementById("valWinRate").textContent = `${data.win_rate.toFixed(1)}%`;
  document.getElementById("valTradesCount").textContent = `${data.today_wins} Wins / ${data.today_losses} Losses`;

  // 3. Active Trade Box (Supports Multiple Concurrent Positions)
  const positions = data.active_positions || (data.active_position ? [data.active_position] : []);
  const maxSlots = data.max_open_positions || 3;
  renderActiveTrades(positions, maxSlots);

  // 4. Market Radar Matrix
  renderRadar(data.market_radar);

  // 5. Closed Trades History
  renderTradeHistory(data.recent_trades);

  // 6. Terminal Logs
  renderLogs(data.logs);
}

function renderActiveTrades(positions, maxSlots = 3) {
  const container = document.getElementById("activeTradeContainer");
  const badge = document.getElementById("activePositionBadge");
  if (badge) {
    badge.textContent = `${positions.length}/${maxSlots} ACTIVE POSITIONS (10X ISOLATED)`;
    badge.style.background = positions.length > 0 ? "rgba(16, 185, 129, 0.2)" : "rgba(255, 255, 255, 0.05)";
    badge.style.color = positions.length > 0 ? "var(--profit-green)" : "var(--text-dim)";
  }

  if (!positions || positions.length === 0) {
    container.innerHTML = `
      <div class="empty-trade-state">
        <div class="radar-spinner"></div>
        <h3 style="font-size: 16px; font-weight: 700;">Scanning 1h Candles Across 6 Cryptos...</h3>
        <p style="font-size: 12px; color: var(--text-dim); max-width: 420px;">
          Velocity Engine is actively monitoring BTC, ETH, SOL, BNB, DOGE, and LINK for high-probability 9/21 EMA pullback setups with 200 EMA regime confirmation (Max ${maxSlots} Concurrent Slots).
        </p>
      </div>
    `;
    return;
  }

  let html = `<div class="active-positions-grid" style="display: flex; flex-direction: column; gap: 14px;">`;
  for (const pos of positions) {
    const isLong = pos.direction === "LONG";
    const pnl = pos.unrealized_pnl || 0.0;
    const pnlClass = pnl >= 0 ? "pnl-positive" : "pnl-negative";
    const beStatus = pos.be_locked 
      ? `<span class="badge-pill" style="background: rgba(16, 185, 129, 0.2); color: var(--profit-green); border-color: var(--profit-green);">🛡️ BREAK-EVEN ACTIVE (+0.18% LOCKED)</span>`
      : `<span class="badge-pill" style="background: rgba(255, 255, 255, 0.05); color: var(--text-dim);">Arming BE at $${pos.be_trigger}</span>`;

    html += `
      <div class="active-trade-card" style="background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 16px;">
        <div class="trade-header-row" style="margin-bottom: 12px;">
          <div class="trade-pair-badge">
            <span class="pair-symbol" style="font-size: 16px; font-weight: 800;">${pos.symbol}</span>
            <span class="dir-badge ${isLong ? 'dir-long' : 'dir-short'}">${pos.direction} 10X</span>
            ${beStatus}
          </div>
          <div class="live-pnl-display">
            <div class="live-pnl-val ${pnlClass}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</div>
            <span style="font-size: 11px; color: var(--text-dim);">Unrealized PnL</span>
          </div>
        </div>

        <div class="trade-details-grid">
          <div class="trade-detail-item">
            <span class="lbl">Entry Price</span>
            <span class="val">$${pos.entry_price}</span>
          </div>
          <div class="trade-detail-item">
            <span class="lbl">Allocated Margin</span>
            <span class="val">$${pos.margin} (10x)</span>
          </div>
          <div class="trade-detail-item">
            <span class="lbl">Stop Loss</span>
            <span class="val" style="color: var(--loss-red);">$${pos.sl_price}</span>
          </div>
          <div class="trade-detail-item">
            <span class="lbl">Take Profit (2.2R)</span>
            <span class="val" style="color: var(--profit-green);">$${pos.tp_price}</span>
          </div>
        </div>

        <div class="trade-actions" style="margin-top: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 11px; color: var(--text-dim);">Opened: ${pos.entry_time || 'Just now'}</span>
          <button class="btn-emergency" style="padding: 6px 14px; font-size: 12px;" onclick="emergencyClose('${pos.symbol}')">🚨 Close ${pos.symbol}</button>
        </div>
      </div>
    `;
  }
  html += `</div>`;
  container.innerHTML = html;
}

function renderRadar(radar) {
  const list = document.getElementById("radarList");
  if (!radar || Object.keys(radar).length === 0) return;

  let html = "";
  for (const [sym, item] of Object.entries(radar)) {
    const isBull = item.regime === "BULLISH";
    const sigClass = item.signal_label === "BUY" ? "sig-buy" : (item.signal_label === "SELL" ? "sig-sell" : "sig-hold");

    html += `
      <div class="radar-item">
        <div class="radar-pair-col">
          <span class="radar-pair-name">${sym}</span>
          <span class="radar-pair-price">$${item.price}</span>
        </div>

        <div class="radar-regime-col">
          <span class="regime-pill ${isBull ? 'regime-bull' : 'regime-bear'}">${item.regime}</span>
          <span style="font-size: 10px; color: var(--text-dim);">200 EMA: $${item.ema_trend}</span>
        </div>

        <div class="radar-signal-col">
          <span class="signal-status-pill ${sigClass}">${item.signal_label}</span>
          <span style="font-size: 10px; color: var(--text-dim);">ATR: $${item.atr}</span>
        </div>
      </div>
    `;
  }
  list.innerHTML = html;
}

function renderTradeHistory(trades) {
  const tbody = document.getElementById("tradesTableBody");
  if (!trades || trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-dim); padding: 25px;">No closed trades yet today.</td></tr>`;
    return;
  }

  tbody.innerHTML = trades.slice().reverse().map(t => {
    const isWin = t.net_pnl > 0;
    const pnlColor = isWin ? "var(--profit-green)" : "var(--loss-red)";
    return `
      <tr>
        <td style="color: var(--text-dim);">${t.time ? t.time.split(" ")[1] : "-"}</td>
        <td><strong>${t.symbol}</strong></td>
        <td><span class="dir-badge ${t.direction === 'LONG' ? 'dir-long' : 'dir-short'}">${t.direction}</span></td>
        <td>$${t.entry_price}</td>
        <td>$${t.exit_price}</td>
        <td>${t.duration_m}m</td>
        <td style="color: ${pnlColor}; font-weight: bold;">${t.net_pnl >= 0 ? '+' : ''}$${t.net_pnl.toFixed(2)}</td>
        <td><span class="badge-pill" style="font-size: 10px;">${t.reason}</span></td>
      </tr>
    `;
  }).join("");
}

function renderLogs(logs) {
  const win = document.getElementById("terminalLogs");
  if (!win || !logs) return;

  win.innerHTML = logs.map((l, idx) => `
    <div class="log-entry ${idx === 0 ? 'log-entry-latest' : ''}">
      <span class="log-time">[${l.time}]</span>
      <span class="log-level-${l.level}">[${l.level}]</span>
      <span>${l.msg}</span>
      ${idx === 0 ? '<span class="latest-tag">LATEST</span>' : ''}
    </div>
  `).join("");
}

async function toggleEngine() {
  const action = isEngineRunning ? "pause" : "resume";
  try {
    await fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    fetchStatus();
  } catch (err) {
    console.error("Error toggling engine:", err);
  }
}

async function emergencyClose(sym) {
  const confirmMsg = sym ? `Are you sure you want to close ${sym} at market price?` : "Are you sure you want to close active positions at market price?";
  if (!confirm(confirmMsg)) return;
  try {
    const res = await fetch("/api/close_position", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym || null })
    });
    const data = await res.json();
    alert(data.msg || "Position closed.");
    fetchStatus();
  } catch (err) {
    console.error("Error closing position:", err);
  }
}

// Initial fetch and 2-second polling loop
fetchStatus();
setInterval(fetchStatus, 2000);
