#!/bin/bash
# Chery T1LFL1 CAN CRC Checker
cd "$(dirname "$0")"
CONFIG="${1:-config.json}"
if [ ! -f "$CONFIG" ]; then
    echo "Config not found: $CONFIG"
    exit 1
fi
echo "Chery T1LFL1 CAN CRC Check: $CONFIG"
./crc-check.exe run -c "$CONFIG" -v
