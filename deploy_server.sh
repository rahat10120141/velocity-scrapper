#!/usr/bin/env bash
# ==============================================================================
# VELOCITY SCALPER: Automated Linux VPS Deployment Script (Ubuntu / Debian)
# Sets up Python Virtualenv, dependencies, and a production systemd daemon
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="velocity-scalper"
CURRENT_USER="$(id -un)"

echo "⚡ Starting Velocity Scalper Server Deployment..."
echo "📂 Project Directory: $DIR"
echo "👤 Service User: $CURRENT_USER"

# 1. Install system prerequisites if apt is available
if command -v apt-get &> /dev/null; then
    echo "📦 Checking system packages..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv curl
fi

# 2. Setup Python virtual environment
if [ ! -d "$DIR/venv" ]; then
    echo "🐍 Creating virtual environment at $DIR/venv..."
    python3 -m venv "$DIR/venv"
fi

echo "📦 Installing / Upgrading Python dependencies..."
"$DIR/venv/bin/pip" install --upgrade pip
"$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"

# 3. Create or check .env
if [ ! -f "$DIR/.env" ]; then
    if [ -f "$DIR/.env.example" ]; then
        echo "📝 Creating initial .env from .env.example..."
        cp "$DIR/.env.example" "$DIR/.env"
        echo "⚠️  Remember to update your API keys in $DIR/.env"
    fi
fi

# 4. Generate and install systemd service unit
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "⚙️  Configuring systemd service at $SERVICE_FILE..."

sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=Velocity Scalper 24/7 Automated Trading Daemon
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8088
Restart=always
RestartSec=5
StandardOutput=append:$DIR/server.log
StandardError=append:$DIR/server.log
KillMode=mixed
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF"

# 5. Reload systemd, enable and start service
echo "🚀 Enabling and starting $SERVICE_NAME..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

sleep 2

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "=================================================================="
    echo "✅ Velocity Scalper successfully deployed and running 24/7!"
    echo "🌐 Dashboard URL: http://$(curl -s ifconfig.me 2>/dev/null || echo '<YOUR_SERVER_IP>'):8088"
    echo ""
    echo "Control commands:"
    echo "  sudo systemctl status $SERVICE_NAME"
    echo "  sudo systemctl restart $SERVICE_NAME"
    echo "  sudo systemctl stop $SERVICE_NAME"
    echo "  sudo journalctl -u $SERVICE_NAME -f"
    echo "=================================================================="
else
    echo "❌ Service failed to start. Check logs with: sudo journalctl -u $SERVICE_NAME -e"
fi
