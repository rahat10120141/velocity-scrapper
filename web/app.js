/**
 * VELOCITY QUANT PORTFOLIO: Frontend Real-Time Client Application
 * Institutional Tri-Engine Command Center: Hybrid Ladder, Balanced Trailing, Swing Runner & Common Master.
 */

let currentTab = "master"; // Common Summary is default landing view!
let isEngineRunning = true;
let lastDashboardData = null;

const ENGINE_CONFIG = {
  master: {
    icon: "🌐",
    name: "Common Portfolio Dashboard",
    desc: "<strong style='color: #fff;'>Common Portfolio Dashboard:</strong> Unified real-time view across all 3 quant strategies ($300 Total Capital Base).",
    badge: "TRI-ENGINE COMBINED • $300 BASE",
    themeClass: "theme-ladder"
  },
  ladder: {
    icon: "🛡️",
    name: "Hybrid Ladder-Lock",
    desc: "<strong style='color: #fff;'>1. Hybrid Ladder-Lock:</strong> +0.25% Fee Shield Lock ➔ +1.0R Step Lock (+0.40R) ➔ +1.5R Step Lock (+1.0R) ➔ +2.2R Take-Profit.",
    badge: "HISTORICAL: 90.8% WR | +$51.66/MO",
    themeClass: "theme-ladder"
  },
  trailing: {
    icon: "⚡",
    name: "Balanced Trailing Scalper",
    desc: "<strong style='color: #fff;'>2. Balanced Trailing Scalper:</strong> +0.25% Fee Shield Lock ➔ 0.28% Dynamic Trailing @ +0.50% ➔ +2.2R Take-Profit.",
    badge: "HISTORICAL: 90.8% WR | +$44.33/MO",
    themeClass: "theme-trailing"
  },
  runner: {
    icon: "🎯",
    name: "Swing Runner (Baseline)",
    desc: "<strong style='color: #fff;'>3. Swing Runner (Baseline):</strong> High-Conviction 1h Swing ➔ +1.0R Break-Even Lock ➔ Wide +2.2R Take-Profit Runner.",
    badge: "HISTORICAL: 77.2% WR | +$60.31/MO",
    themeClass: "theme-runner"
  }
};

function switchEngineTab(tabId) {
  currentTab = tabId;
  ["master", "ladder", "trailing", "runner"].forEach(t => {
    const btn = document.getElementById(`tab-${t}`);
    if (btn) {
      if (t === tabId) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    }
  });

  if (lastDashboardData) {
    renderDashboard(lastDashboardData);
  }
  fetchStatus();
}

async function fetchStatus() {
  try {
    const url = `/api/status?engine_id=${currentTab}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    lastDashboardData = data;
    renderDashboard(data);
  } catch (err) {
    console.error("Error fetching engine status:", err);
  }
}

function renderDashboard(data) {
  if (!data) return;

  const engines = data.engines || {};
  const ladderEng = engines.ladder || {};
  const trailingEng = engines.trailing || {};
  const runnerEng = engines.runner || {};
  const mp = data.master_portfolio || {};

  // 1. Update Tab Bar Data (Balances, Counts, Floating PnL directly on buttons)
  updateTabBar(ladderEng, trailingEng, runnerEng, mp);

  // 2. System Status & Pause/Resume Controls
  updateSystemControls(data);

  // 3. Sub-header Context Banner
  updateBanner();

  // 4. Hero KPI Grid & Strategy Breakdown
  if (currentTab === "master") {
    renderMasterHero(mp, engines);
    const breakdownSec = document.getElementById("strategyBreakdownSection");
    if (breakdownSec) breakdownSec.style.display = "block";
    renderStrategyCards(ladderEng, trailingEng, runnerEng);

    // Master Active Positions & Trades
    renderActiveTrades(data.all_active_positions || [], true);
    renderCombinedRecentTrades(engines);
  } else {
    const activeEng = engines[currentTab] || data;
    renderSingleHero(activeEng);
    const breakdownSec = document.getElementById("strategyBreakdownSection");
    if (breakdownSec) breakdownSec.style.display = "none";

    renderActiveTrades(activeEng.active_positions || [], false);
    renderRecentTrades(activeEng.recent_trades || [], false);
  }

  // 5. Market Radar Matrix
  renderRadar(data.market_radar);

  // 6. Terminal Logs
  renderLogs(data.logs);
}

function updateTabBar(ladder, trailing, runner, mp) {
  const lBal = ladder.current_balance ?? 100.0;
  const tBal = trailing.current_balance ?? 100.0;
  const rBal = runner.current_balance ?? 100.0;
  const mBal = mp.total_balance ?? (lBal + tBal + rBal);

  const lPos = (ladder.active_positions || []).length;
  const tPos = (trailing.active_positions || []).length;
  const rPos = (runner.active_positions || []).length;
  const mPos = mp.total_open_positions ?? (lPos + tPos + rPos);

  const lUnreal = ladder.unrealized_pnl ?? 0.0;
  const tUnreal = trailing.unrealized_pnl ?? 0.0;
  const rUnreal = runner.unrealized_pnl ?? 0.0;
  const mUnreal = mp.total_unrealized_pnl ?? (lUnreal + tUnreal + rUnreal);

  // Balances
  setElementText("tab-ladder-balance", `$${lBal.toFixed(2)}`);
  setElementText("tab-trailing-balance", `$${tBal.toFixed(2)}`);
  setElementText("tab-runner-balance", `$${rBal.toFixed(2)}`);
  setElementText("tab-master-balance", `$${mBal.toFixed(2)}`);

  // Open Position counts
  updateSlotBadge("badge-ladder-pos", `${lPos}/3 Open`, lPos > 0);
  updateSlotBadge("badge-trailing-pos", `${tPos}/3 Open`, tPos > 0);
  updateSlotBadge("badge-runner-pos", `${rPos}/3 Open`, rPos > 0);
  updateSlotBadge("badge-master-pos", `${mPos} Total Open`, mPos > 0);

  // Floating PnL on tabs
  updateTabFloating("tab-ladder-floating", lUnreal);
  updateTabFloating("tab-trailing-floating", tUnreal);
  updateTabFloating("tab-runner-floating", rUnreal);
  updateTabFloating("tab-master-floating", mUnreal);
}

function updateSlotBadge(id, text, hasOpen) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  if (hasOpen) {
    el.classList.add("has-open");
  } else {
    el.classList.remove("has-open");
  }
}

function updateTabFloating(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  const sign = val > 0 ? "+" : (val < 0 ? "-" : "");
  el.textContent = `Float: ${sign}$${Math.abs(val).toFixed(2)}`;
  if (val > 0) {
    el.style.color = "var(--profit-green)";
  } else if (val < 0) {
    el.style.color = "var(--loss-red)";
  } else {
    el.style.color = "var(--text-dim)";
  }
}

function updateSystemControls(data) {
  isEngineRunning = data.is_running;
  const statusPill = document.getElementById("engineStatusText");
  const pulseDot = document.getElementById("pulseDot");
  const btnToggle = document.getElementById("btnToggleEngine");
  const btnText = document.getElementById("btnToggleText");
  const btnIcon = document.getElementById("btnToggleIcon");

  if (data.is_running) {
    if (statusPill) statusPill.textContent = "SYSTEM ACTIVE";
    if (pulseDot) {
      pulseDot.style.background = "var(--profit-green)";
      pulseDot.style.boxShadow = "0 0 8px rgba(16, 185, 129, 0.4)";
    }
    if (btnToggle) btnToggle.className = "control-btn btn-pause";
    if (btnText) btnText.textContent = currentTab === "master" ? "Pause Bot" : `Pause ${currentTab.toUpperCase()}`;
    if (btnIcon) btnIcon.textContent = "⏸️";
  } else {
    if (statusPill) statusPill.textContent = "ENGINE PAUSED";
    if (pulseDot) {
      pulseDot.style.background = "var(--warning-amber)";
      pulseDot.style.boxShadow = "0 0 8px rgba(245, 158, 11, 0.4)";
    }
    if (btnToggle) btnToggle.className = "control-btn btn-resume";
    if (btnText) btnText.textContent = currentTab === "master" ? "Resume Bot" : `Resume ${currentTab.toUpperCase()}`;
    if (btnIcon) btnIcon.textContent = "▶️";
  }

  setElementText("tradingModeText", (data.trading_mode || "PAPER") + " TRADING");
}

function updateBanner() {
  const cfg = ENGINE_CONFIG[currentTab] || ENGINE_CONFIG.master;
  setElementText("bannerIcon", cfg.icon);
  const descEl = document.getElementById("bannerDescription");
  if (descEl) descEl.innerHTML = cfg.desc;

  const badgeEl = document.getElementById("bannerBadge");
  if (badgeEl) {
    badgeEl.textContent = cfg.badge;
    badgeEl.className = `badge-tag ${cfg.themeClass}`;
  }
}

function renderMasterHero(mp, engines) {
  const totalBalance = mp.total_balance ?? 300.0;
  const totalUnreal = mp.total_unrealized_pnl ?? 0.0;
  const realtimeEquity = totalBalance + totalUnreal;
  const todayRealized = mp.today_realized_pnl ?? 0.0;
  const openCount = mp.total_open_positions ?? 0;
  const winRate = mp.combined_win_rate ?? 0.0;
  const wins = mp.today_wins ?? 0;
  const losses = mp.today_losses ?? 0;

  // 1. Total Portfolio Equity
  setElementText("lblEquityTitle", "Total Portfolio Equity");
  setElementText("valRealtimeEquity", `$${realtimeEquity.toFixed(2)}`);
  setElementText("valStartingBase", `$${(mp.starting_base ?? 300.0).toFixed(2)}`);
  setElementText("valBalanceBreakdown", `Balance: $${totalBalance.toFixed(2)}`);

  // 2. Floating Unrealized PnL (PROMINENT HIGHLIGHT)
  setElementText("lblFloatingTitle", "Floating Unrealized PnL");
  const unSign = totalUnreal > 0 ? "+" : (totalUnreal < 0 ? "-" : "");
  const unEl = document.getElementById("valFloatingPnL");
  if (unEl) {
    unEl.textContent = `${unSign}$${Math.abs(totalUnreal).toFixed(2)}`;
    unEl.className = `kpi-value font-mono ${totalUnreal > 0 ? 'pnl-positive' : (totalUnreal < 0 ? 'pnl-negative' : '')}`;
  }

  // ROE approximation based on $25 margin per active slot
  const totalMargin = Math.max(25.0, openCount * 25.0);
  const roePct = Math.abs((totalUnreal / totalMargin) * 100).toFixed(2);
  const roeSign = totalUnreal > 0 ? "+" : (totalUnreal < 0 ? "-" : "");
  setElementText("valFloatingPct", openCount > 0 ? `ROE: ${roeSign}${roePct}%` : "No Open Risk");
  setElementText("valFloatingOpenCount", `${openCount} Position${openCount === 1 ? '' : 's'} Active`);

  // 3. Today's Realized Profit
  setElementText("lblRealizedTitle", "Today's Realized Profit");
  const realSign = todayRealized > 0 ? "+" : (todayRealized < 0 ? "-" : "");
  const realEl = document.getElementById("valTodayRealized");
  if (realEl) {
    realEl.textContent = `${realSign}$${Math.abs(todayRealized).toFixed(2)}`;
    realEl.className = `kpi-value font-mono ${todayRealized > 0 ? 'pnl-positive' : (todayRealized < 0 ? 'pnl-negative' : '')}`;
  }

  const target = 9.0;
  const progressPct = Math.min(100, Math.max(0, (todayRealized / target) * 100));
  setElementText("targetProgressLabel", `Progress to $${target.toFixed(2)} Target: ${progressPct.toFixed(0)}%`);
  const barEl = document.getElementById("targetProgressBar");
  if (barEl) barEl.style.width = `${progressPct}%`;

  // 4. Active Slots & Win Rate
  setElementText("lblSlotsTitle", "Active Slots & Win Rate");
  setElementText("valActiveSlots", `${openCount} / 9 Active`);
  setElementText("valWinRate", winRate > 0 ? `${winRate.toFixed(1)}%` : "90.8% (Hist)");
  setElementText("valTodayWinsLosses", `${wins}W / ${losses}L`);
}

function renderSingleHero(eng) {
  const balance = eng.current_balance ?? 100.0;
  const unreal = eng.unrealized_pnl ?? 0.0;
  const equity = balance + unreal;
  const todayRealized = eng.today_realized_pnl ?? 0.0;
  const openCount = (eng.active_positions || []).length;
  const maxSlots = eng.max_open_positions ?? 3;
  const winRate = eng.win_rate ?? 0.0;
  const wins = eng.today_wins ?? 0;
  const losses = eng.today_losses ?? 0;

  // 1. Single Engine Equity
  setElementText("lblEquityTitle", `${eng.engine_name || 'Strategy'} Equity`);
  setElementText("valRealtimeEquity", `$${equity.toFixed(2)}`);
  setElementText("valStartingBase", `$${(eng.starting_balance ?? 100.0).toFixed(2)}`);
  setElementText("valBalanceBreakdown", `Balance: $${balance.toFixed(2)}`);

  // 2. Single Engine Floating PnL
  setElementText("lblFloatingTitle", "Floating Unrealized PnL");
  const unSign = unreal > 0 ? "+" : (unreal < 0 ? "-" : "");
  const unEl = document.getElementById("valFloatingPnL");
  if (unEl) {
    unEl.textContent = `${unSign}$${Math.abs(unreal).toFixed(2)}`;
    unEl.className = `kpi-value font-mono ${unreal > 0 ? 'pnl-positive' : (unreal < 0 ? 'pnl-negative' : '')}`;
  }

  const margin = Math.max(25.0, openCount * 25.0);
  const roePct = Math.abs((unreal / margin) * 100).toFixed(2);
  const roeSign = unreal > 0 ? "+" : (unreal < 0 ? "-" : "");
  setElementText("valFloatingPct", openCount > 0 ? `ROE: ${roeSign}${roePct}%` : "No Open Risk");
  setElementText("valFloatingOpenCount", `${openCount}/${maxSlots} Active Slots`);

  // 3. Today's Profit
  setElementText("lblRealizedTitle", "Today's Realized Profit");
  const realSign = todayRealized > 0 ? "+" : (todayRealized < 0 ? "-" : "");
  const realEl = document.getElementById("valTodayRealized");
  if (realEl) {
    realEl.textContent = `${realSign}$${Math.abs(todayRealized).toFixed(2)}`;
    realEl.className = `kpi-value font-mono ${todayRealized > 0 ? 'pnl-positive' : (todayRealized < 0 ? 'pnl-negative' : '')}`;
  }

  const target = eng.daily_target ?? 3.0;
  const progressPct = Math.min(100, Math.max(0, (todayRealized / target) * 100));
  setElementText("targetProgressLabel", `Progress to $${target.toFixed(2)} Target: ${progressPct.toFixed(0)}%`);
  const barEl = document.getElementById("targetProgressBar");
  if (barEl) barEl.style.width = `${progressPct}%`;

  // 4. Slots & Win Rate
  setElementText("lblSlotsTitle", "Active Slots & Win Rate");
  setElementText("valActiveSlots", `${openCount} / ${maxSlots} Active`);
  const defaultHistWr = (eng.engine_id === "runner") ? "77.2% (Hist)" : "90.8% (Hist)";
  setElementText("valWinRate", winRate > 0 ? `${winRate.toFixed(1)}%` : defaultHistWr);
  setElementText("valTodayWinsLosses", `${wins}W / ${losses}L`);
}

function renderStrategyCards(ladder, trailing, runner) {
  // Ladder
  const lSlots = (ladder.active_positions || []).length;
  setElementText("stratCardLadderSlots", `${lSlots}/3 Slots Active`);
  setElementText("stratCardLadderBalance", `$${(ladder.current_balance ?? 100.0).toFixed(2)}`);
  updateCardPnL("stratCardLadderUnrealized", ladder.unrealized_pnl ?? 0.0);
  updateCardPnL("stratCardLadderRealized", ladder.today_realized_pnl ?? 0.0);

  // Trailing
  const tSlots = (trailing.active_positions || []).length;
  setElementText("stratCardTrailingSlots", `${tSlots}/3 Slots Active`);
  setElementText("stratCardTrailingBalance", `$${(trailing.current_balance ?? 100.0).toFixed(2)}`);
  updateCardPnL("stratCardTrailingUnrealized", trailing.unrealized_pnl ?? 0.0);
  updateCardPnL("stratCardTrailingRealized", trailing.today_realized_pnl ?? 0.0);

  // Runner
  const rSlots = (runner.active_positions || []).length;
  setElementText("stratCardRunnerSlots", `${rSlots}/3 Slots Active`);
  setElementText("stratCardRunnerBalance", `$${(runner.current_balance ?? 100.0).toFixed(2)}`);
  updateCardPnL("stratCardRunnerUnrealized", runner.unrealized_pnl ?? 0.0);
  updateCardPnL("stratCardRunnerRealized", runner.today_realized_pnl ?? 0.0);
}

function updateCardPnL(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  const sign = val > 0 ? "+" : (val < 0 ? "-" : "");
  el.textContent = `${sign}$${Math.abs(val).toFixed(2)}`;
  if (val > 0) {
    el.className = "strat-unrealized-val font-mono pnl-positive";
    el.style.color = "var(--profit-green)";
  } else if (val < 0) {
    el.className = "strat-unrealized-val font-mono pnl-negative";
    el.style.color = "var(--loss-red)";
  } else {
    el.className = "strat-unrealized-val font-mono";
    el.style.color = "var(--text-muted)";
  }
}

function renderActiveTrades(positions, isMasterView) {
  const tbody = document.getElementById("activeTradesTableBody");
  const countBadge = document.getElementById("lblActivePositionsCount");
  const titleEl = document.getElementById("lblActivePositionsTitle");

  if (titleEl) {
    titleEl.textContent = isMasterView 
      ? "Active Positions (All 3 Quant Strategies)" 
      : `${ENGINE_CONFIG[currentTab]?.name || 'Engine'} Active Positions`;
  }

  const count = positions ? positions.length : 0;
  if (countBadge) {
    countBadge.textContent = `${count} ACTIVE POSITION${count === 1 ? '' : 'S'} (5X ISOLATED)`;
    countBadge.style.color = count > 0 ? "var(--profit-green)" : "var(--text-dim)";
  }

  if (!tbody) return;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; color: var(--text-dim); padding: 32px;">
          <div style="font-size: 13px; font-weight: 500; color: var(--text-secondary); margin-bottom: 4px;">No Open Positions Currently Active</div>
          <div style="font-size: 11px; color: var(--text-dim);">Algorithms are continuously monitoring 1h candles across BTC, ETH, SOL, BNB, DOGE, and LINK for high-probability 9/21 EMA pullback setups.</div>
        </td>
      </tr>
    `;
    return;
  }

  let html = "";
  for (const pos of positions) {
    const isLong = pos.direction === "LONG";
    const pnl = pos.unrealized_pnl || 0.0;
    const pnlClass = pnl > 0 ? "pnl-positive" : (pnl < 0 ? "pnl-negative" : "");
    const margin = pos.margin || 25.0;
    const pnlPct = margin > 0 ? ((Math.abs(pnl) / margin) * 100).toFixed(2) : "0.00";
    const pnlSign = pnl > 0 ? "+" : (pnl < 0 ? "-" : "");

    // Protection Badge logic
    let protBadge = `<span class="badge-tag" style="background: rgba(255,255,255,0.05); color: var(--text-muted);">INITIAL SL DEFENSE</span>`;
    if (pos.step2_locked) {
      protBadge = `<span class="badge-tag theme-ladder">🪜 STEP 2 LOCKED (+1.0R)</span>`;
    } else if (pos.step1_locked) {
      protBadge = `<span class="badge-tag theme-ladder">🪜 STEP 1 LOCKED (+0.40R)</span>`;
    } else if (pos.trail_active) {
      protBadge = `<span class="badge-tag theme-trailing">⚡ TRAILING ACTIVE</span>`;
    } else if (pos.shield_locked || pos.be_locked) {
      protBadge = `<span class="badge-tag theme-ladder">🛡️ FEE SHIELD (ZERO RISK)</span>`;
    }

    // Engine Badge
    const eid = pos.engine_id || currentTab;
    const themeClass = eid === "ladder" ? "theme-ladder" : (eid === "trailing" ? "theme-trailing" : "theme-runner");
    const engineBadgeText = pos.engine_badge || (eid === "ladder" ? "🛡️ LADDER" : (eid === "trailing" ? "⚡ TRAILING" : "🎯 RUNNER"));

    html += `
      <tr>
        <td>
          <span class="badge-tag ${themeClass}" style="font-size: 11px; font-weight: 700;">
            ${engineBadgeText}
          </span>
        </td>
        <td>
          <div style="font-weight: 700; color: #fff; font-size: 13px;">${pos.symbol}</div>
          <span class="badge-tag ${isLong ? 'theme-ladder' : 'theme-runner'}" style="font-size: 10px; padding: 1px 5px;">
            ${pos.direction} 5X
          </span>
        </td>
        <td class="font-mono">$${formatPrice(pos.entry_price)}</td>
        <td class="font-mono" style="color: var(--loss-red);">$${formatPrice(pos.sl_price)}</td>
        <td class="font-mono" style="color: var(--profit-green);">$${formatPrice(pos.tp_price)}</td>
        <td>
          <div class="font-mono ${pnlClass}" style="font-weight: 700; font-size: 13px;">
            ${pnlSign}$${Math.abs(pnl).toFixed(2)}
          </div>
          <div class="font-mono ${pnlClass}" style="font-size: 10px;">
            ${pnlSign}${pnlPct}% (ROE)
          </div>
        </td>
        <td>${protBadge}</td>
        <td style="text-align: right;">
          <button class="btn-close-market" onclick="emergencyClose('${pos.symbol}', '${eid}')">
            Close Market
          </button>
        </td>
      </tr>
    `;
  }
  tbody.innerHTML = html;
}

function renderCombinedRecentTrades(engines) {
  const allTrades = [];
  for (const [eid, eng] of Object.entries(engines)) {
    for (const t of (eng.recent_trades || [])) {
      allTrades.push({ ...t, engine_id: eid });
    }
  }
  allTrades.sort((a, b) => (b.time || "").localeCompare(a.time || ""));
  renderRecentTrades(allTrades.slice(0, 15), true);
}

function renderRecentTrades(trades, isMasterView) {
  const tbody = document.getElementById("recentTradesTableBody");
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 25px;">No closed trades yet today.</td></tr>`;
    return;
  }

  let html = "";
  for (const t of trades) {
    const isWin = (t.net_pnl || 0) > 0;
    const pnlSign = isWin ? "+" : ((t.net_pnl || 0) < 0 ? "-" : "");
    const pnlClass = isWin ? "pnl-positive" : ((t.net_pnl || 0) < 0 ? "pnl-negative" : "");
    const eid = t.engine_id || currentTab;
    const themeClass = eid === "ladder" ? "theme-ladder" : (eid === "trailing" ? "theme-trailing" : "theme-runner");
    const engineBadgeText = eid === "ladder" ? "🛡️ LADDER" : (eid === "trailing" ? "⚡ TRAILING" : "🎯 RUNNER");

    html += `
      <tr>
        <td class="font-mono" style="font-size: 11px; color: var(--text-dim);">${(t.time || "").split(" ")[1] || t.time}</td>
        <td><span class="badge-tag ${themeClass}" style="font-size: 10px;">${engineBadgeText}</span></td>
        <td>
          <strong style="color: #fff;">${t.symbol}</strong>
          <span style="font-size: 10px; color: ${t.direction === 'LONG' ? 'var(--profit-green)' : 'var(--loss-red)'}; margin-left: 4px;">${t.direction}</span>
        </td>
        <td class="font-mono">$${formatPrice(t.entry_price)}</td>
        <td class="font-mono">$${formatPrice(t.exit_price)}</td>
        <td class="font-mono ${pnlClass}" style="font-weight: 700;">${pnlSign}$${Math.abs(t.net_pnl || 0).toFixed(2)}</td>
        <td><span class="badge-tag" style="font-size: 10px;">${t.reason || 'EXIT'}</span></td>
      </tr>
    `;
  }
  tbody.innerHTML = html;
}

function renderRadar(radarData) {
  const tbody = document.getElementById("radarTableBody");
  if (!tbody) return;

  if (!radarData || Object.keys(radarData).length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 25px;">Waiting for scan cycle...</td></tr>`;
    return;
  }

  let html = "";
  for (const [sym, info] of Object.entries(radarData)) {
    const isBull = info.regime === "BULLISH";
    const sigLabel = info.signal_label || "HOLD";
    const sigTheme = sigLabel === "BUY" ? "theme-ladder" : (sigLabel === "SELL" ? "theme-runner" : "");
    const price = info.price || 0.0;
    const atr = info.atr || 0.0;
    const emaDiff = (info.ema_diff_pct !== undefined) ? info.ema_diff_pct.toFixed(2) : "0.00";

    html += `
      <tr>
        <td><strong style="color: #fff;">${sym.replace("USDT", "")}</strong></td>
        <td class="font-mono">$${formatPrice(price)}</td>
        <td>
          <span class="badge-tag ${isBull ? 'theme-ladder' : 'theme-runner'}" style="font-size: 10px;">
            ${info.regime || 'NEUTRAL'}
          </span>
        </td>
        <td class="font-mono">$${formatPrice(atr)}</td>
        <td class="font-mono" style="color: var(--accent-blue);">Δ ${emaDiff}%</td>
        <td>
          <span class="badge-tag ${sigTheme}" style="font-size: 10px; font-weight: 700;">
            ${sigLabel}
          </span>
        </td>
      </tr>
    `;
  }
  tbody.innerHTML = html;
}

function renderLogs(logs) {
  const container = document.getElementById("terminalLogs");
  if (!container || !logs || logs.length === 0) return;

  let html = "";
  for (let i = 0; i < Math.min(logs.length, 30); i++) {
    const log = logs[i];
    const isLatest = (i === 0);
    const color = getLogColor(log.level);
    html += `
      <div class="log-row" style="${isLatest ? 'background: rgba(255,255,255,0.02);' : ''}">
        <span class="log-time">[${log.time}]</span>
        <span style="color: ${color}; font-weight: 700; flex-shrink: 0; min-width: 60px;">[${log.level}]</span>
        <span class="log-msg">${log.msg}</span>
      </div>
    `;
  }
  container.innerHTML = html;
}

function getLogColor(level) {
  switch (level) {
    case "TRADE": return "var(--accent-blue)";
    case "PROFIT": return "var(--profit-green)";
    case "DEFENSE": return "var(--loss-red)";
    case "WARNING": return "var(--warning-amber)";
    case "ERROR": return "var(--loss-red)";
    case "TICK": return "#38bdf8";
    case "ACTION": return "var(--accent-purple)";
    default: return "var(--text-dim)";
  }
}

function formatPrice(p) {
  if (!p || p === 0) return "0.00";
  if (p < 1) return p.toFixed(4);
  if (p < 50) return p.toFixed(3);
  return p.toFixed(2);
}

function setElementText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

async function toggleEngine() {
  const action = isEngineRunning ? "pause" : "resume";
  const eid = currentTab === "master" ? "all" : currentTab;
  try {
    const res = await fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action, engine_id: eid })
    });
    await res.json();
    fetchStatus();
  } catch (err) {
    console.error("Error toggling engine:", err);
  }
}

async function emergencyClose(symbol, engineId) {
  if (!confirm(`Are you sure you want to market close ${symbol} on ${engineId.toUpperCase()} strategy?`)) return;
  try {
    const res = await fetch("/api/close_position", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: symbol, engine_id: engineId })
    });
    await res.json();
    fetchStatus();
  } catch (err) {
    console.error("Error closing position:", err);
  }
}

// Initial fetch and 2-second background sync
fetchStatus();
setInterval(fetchStatus, 2000);
