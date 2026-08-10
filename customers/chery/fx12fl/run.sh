#!/bin/bash
# Chery FX12FL CAN CRC Checker
cd "$(dirname "$0")"
CONFIG="${1:-config.json}"
if [ ! -f "$CONFIG" ]; then
    echo "Config not found: $CONFIG"
    exit 1
fi
echo "Chery FX12FL CAN CRC Check: $CONFIG"
./crc-check.exe run -c "$CONFIG" -v
