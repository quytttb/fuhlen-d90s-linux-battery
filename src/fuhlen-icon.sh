#!/bin/bash
set -euo pipefail

# Read battery status, default to N/A if file missing
BAT=$(cat /tmp/fuhlen_battery 2>/dev/null || echo "N/A")

if [ "$BAT" == "N/A" ]; then 
    # An icon khi khong co chuot
    exit 0
fi

# Extract number
NUM=${BAT%\%}

# Check if NUM is a valid integer
if ! [[ "$NUM" =~ ^[0-9]+$ ]]; then
    echo "🖱️?"
    exit 0
fi

ICON="🖱️"

echo "$ICON $BAT"
