#!/bin/bash
# GAC radar buses (FR/FLR/FRR/RLR/RRR) CAN CRC Checker
# Usage: ./run.sh [config.json]   (default: config.json)

cd "$(dirname "$0")"
CONFIG="${1:-config.json}"

if [ ! -f "$CONFIG" ]; then
    echo "Config not found: $CONFIG"
    exit 1
fi

if [ -x ./crc-check ]; then
    BIN=./crc-check
else
    BIN=./crc-check.exe
fi

echo "GAC radar CAN CRC Check: $CONFIG"
"$BIN" run -c "$CONFIG" -v
