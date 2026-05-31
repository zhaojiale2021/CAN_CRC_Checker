#!/bin/bash
# Run CAN CRC Checker with config file
# Usage: ./run.sh [config.json]   (default: gwm_config.json)

cd "$(dirname "$0")"

CONFIG="${1:-gwm_config.json}"

if [ ! -f "$CONFIG" ]; then
    echo "Config not found: $CONFIG"
    exit 1
fi

echo "CRC Check: $CONFIG"
./crc-check.exe run -c "$CONFIG" -v
