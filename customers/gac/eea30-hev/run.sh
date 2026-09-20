#!/bin/bash
# GAC EEA3.0 hybrid platform CAN CRC Checker
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

echo "GAC EEA3.0 hybrid CAN CRC Check: $CONFIG"
"$BIN" run -c "$CONFIG" -v
