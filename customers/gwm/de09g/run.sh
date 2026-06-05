#!/bin/bash
# GWM CAN CRC Checker
# Usage: ./run.sh [config.json]   (default: config.json)

cd "$(dirname "$0")"
CONFIG="${1:-config.json}"

if [ ! -f "$CONFIG" ]; then
    echo "Config not found: $CONFIG"
    exit 1
fi

echo "GWM CAN CRC Check: $CONFIG"
./crc-check.exe run -c "$CONFIG" -v
