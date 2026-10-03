#!/usr/bin/env bash

# ==============================================================================
# VELOCITY SCALPER: 24/7 Service Controller
# Controls the systemd service with sleep / lock / lid inhibition
# ==============================================================================
DIR="/home/rahat/Documents/claude/aggresive"
PORT=8088
ACTION="${1:-status}"
SERVICE="velocity-scalper.service"

cd "$DIR" || exit 1

case "$ACTION" in
    start)
        echo "Starting Velocity Scalper 24/7 service..."
        systemctl --user start "$SERVICE"
        sleep 2
        systemctl --user is-active --quiet "$SERVICE" && echo "✅ Velocity Scalper started successfully at http://localhost:${PORT}" || echo "❌ Failed to start."
        ;;
    stop)
        echo "Stopping Velocity Scalper service..."
        systemctl --user stop "$SERVICE"
        echo "Velocity Scalper stopped."
        ;;
    restart)
        echo "Restarting Velocity Scalper service..."
        systemctl --user restart "$SERVICE"
        sleep 2
        systemctl --user is-active --quiet "$SERVICE" && echo "✅ Velocity Scalper restarted successfully at http://localhost:${PORT}" || echo "❌ Failed to restart."
        ;;
    status)
        systemctl --user status "$SERVICE" --no-pager
        echo ""
        echo "--- Sleep / Lock / Lid Inhibitor Lock ---"
        systemd-inhibit --list | grep -E 'Velocity|COMM'
        echo ""
        echo "--- Live Engine Status ---"
        curl -s --max-time 2 "http://localhost:${PORT}/api/status" | python3 -m json.tool 2>/dev/null | grep -E 'trading_mode|unrealized_pnl|today_realized_pnl|is_loop_healthy|thread_alive|seconds_since_last_scan|last_scan_time' || echo "API offline"
        ;;
    logs)
        journalctl --user -u "$SERVICE" -f
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
