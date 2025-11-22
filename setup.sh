#!/bin/bash
set -u

APP_NAME="ojp91xx-cert-renew"
INSTALL_DIR="/opt/$APP_NAME"
CONF_DIR="/etc/$APP_NAME"
SYSTEMD_DIR="/etc/systemd/system"

# Root Check
if [[ "$EUID" -ne 0 ]]; then
   echo "CRITICAL: Run as root."
   exit 1
fi

echo "--- Step 1: Prepare Directories ---"
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONF_DIR"

echo "--- Step 2: Copy Files ---"
cp renew_cert.py issue_cert.py upload_cert.py requirements.txt "$INSTALL_DIR/"

# Handle Configs
# Handle Configs
if [[ -f "./config.env" ]]; then
    echo "Found local config.env, installing it..."
    cp ./config.env "$CONF_DIR/config.env"
elif [[ ! -f "$CONF_DIR/config.env" ]]; then
    echo "No local config found. Installing sample (You must edit this!)..."
    cp config.env.sample "$CONF_DIR/config.env"
fi
chmod 600 "$CONF_DIR/config.env"

# Handle Cloudflare INI
if [[ -f "cloudflare.ini" ]]; then
    echo "Installing cloudflare.ini..."
    cp cloudflare.ini "$CONF_DIR/"
    chmod 600 "$CONF_DIR/cloudflare.ini"
else
    echo "WARNING: cloudflare.ini not found in source. Please create it in $CONF_DIR manually."
fi

echo "--- Step 3: Python Environment (This takes a minute) ---"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    echo "Creating venv..."
    python3 -m venv "$INSTALL_DIR/.venv"
fi

echo "Installing requirements..."
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "Installing Playwright Browsers..."
"$INSTALL_DIR/.venv/bin/playwright" install chromium

echo "--- Step 4: Systemd Units ---"
cp "$APP_NAME.service" "$SYSTEMD_DIR/"
cp "$APP_NAME.timer" "$SYSTEMD_DIR/"
systemctl daemon-reload

echo "--- Step 5: Activation ---"
systemctl enable --now "$APP_NAME.timer"
systemctl list-timers --no-pager | grep "$APP_NAME"
echo "Done."
