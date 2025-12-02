# Fuhlen D90S Battery Monitor for Linux (GNOME)

This project provides a simple solution to display the battery percentage of the **Fuhlen D90S** wireless mouse on Linux (specifically tested on Ubuntu/GNOME).

It consists of:
1.  **Backend:** A Python script (`fuhlen-monitor.py`) that reads battery data from the USB receiver via `pyusb`.
2.  **Service:** A systemd service (`fuhlen-monitor.service`) to run the backend in the background.
3.  **Frontend:** A shell script (`fuhlen-icon.sh`) designed to work with the **Executor** GNOME extension to display the battery status on the top bar.

## Features
*   **Real-time monitoring:** Updates every 10 seconds.
*   **Auto-hide:** The icon automatically disappears from the top bar when the mouse (USB receiver) is disconnected.
*   **Robust:** Handles USB disconnects/reconnects gracefully without crashing.
*   **Lightweight:** Minimal resource usage.

## Prerequisites

*   Python 3
*   `pyusb` library
*   GNOME Shell (for the frontend display)
*   **Executor** GNOME Extension: [Install here](https://extensions.gnome.org/extension/2932/executor/)

## Installation

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/fuhlen-d90s-linux-battery.git
cd fuhlen-d90s-linux-battery
```

### 2. Run the install script
```bash
chmod +x install.sh
./install.sh
```
This script will:
*   Install necessary Python dependencies (`python3-usb`).
*   Copy the backend script to `/usr/local/bin/`.
*   Install the systemd service and a **system-sleep hook** that automatically restarts the service after suspend/resume, ensuring the receiver hotplug is detected.
*   Copy the icon script to your home directory (`~/fuhlen-icon.sh`).

### 3. Configure Executor Extension
1.  Open **Executor** settings in GNOME Extensions.
2.  Add a new command:
    *   **Command:** `bash /home/YOUR_USERNAME/fuhlen-icon.sh` (Replace `YOUR_USERNAME` with your actual username)
    *   **Interval:** `5` or `10` seconds.
3.  Save and enjoy!

## Manual Installation
If you prefer to install manually, check the `install.sh` script to see the steps involved.

## Troubleshooting
*   **Check service status:** `systemctl status fuhlen-monitor.service`
*   **Check raw output:** `cat /tmp/fuhlen_battery`
*   **Check script output:** `bash ~/fuhlen-icon.sh`

## License
MIT
