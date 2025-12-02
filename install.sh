#!/bin/bash
set -e

echo "Installing Fuhlen D90S Battery Monitor..."

# 1. Install dependencies
echo "[1/4] Installing dependencies..."
if command -v apt &> /dev/null; then
    sudo apt update
    sudo apt install -y python3 python3-usb
else
    echo "Warning: 'apt' not found. Please ensure 'python3' and 'python3-usb' (or pyusb) are installed manually."
fi

# 2. Install Backend Script
echo "[2/4] Installing backend script..."
sudo cp src/fuhlen-monitor.py /usr/local/bin/fuhlen-monitor.py
sudo chmod 755 /usr/local/bin/fuhlen-monitor.py

# 3. Install Systemd Service
echo "[3/5] Installing systemd service..."
sudo cp systemd/fuhlen-monitor.service /etc/systemd/system/fuhlen-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now fuhlen-monitor.service

# 4. Install system-sleep hook to restart service after resume
echo "[4/5] Installing system-sleep hook..."
sudo cp systemd/system-sleep/fuhlen-monitor /lib/systemd/system-sleep/fuhlen-monitor
sudo chmod 755 /lib/systemd/system-sleep/fuhlen-monitor

# 5. Install Frontend Script
echo "[5/5] Installing frontend script..."
# Copy to user's home directory to make it easy to reference in Executor
cp src/fuhlen-icon.sh "$HOME/fuhlen-icon.sh"
chmod +x "$HOME/fuhlen-icon.sh"

echo "----------------------------------------------------------------"
echo "Installation Complete!"
echo ""
echo "Next Step: Configure 'Executor' GNOME Extension:"
echo "  Command: bash $HOME/fuhlen-icon.sh"
echo "  Interval: 5"
echo ""
echo "Service Status:"
systemctl status fuhlen-monitor.service --no-pager
