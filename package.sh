#!/bin/bash
# ============================================================
#  CAN CRC Checker — Package for customer distribution
#  Usage: ./package.sh <customer>   (e.g. ./package.sh gwm)
# ============================================================
set -e

CUSTOMER="${1:-}"
if [ -z "$CUSTOMER" ]; then
    echo "Usage: ./package.sh <customer>"
    echo "  e.g. ./package.sh gwm"
    echo
    echo "Available customers:"
    for d in customers/*/; do echo "  - $(basename "$d")"; done
    exit 1
fi

CUST_DIR="customers/$CUSTOMER"
if [ ! -d "$CUST_DIR" ]; then
    echo "Customer directory not found: $CUST_DIR"
    exit 1
fi

echo
echo "=== Packaging for: $CUSTOMER ==="
echo

# Check / build exe
if [ ! -f "dist/crc-check.exe" ]; then
    echo "Building exe..."
    ./build.bat || {
        echo "Build failed!"
        exit 1
    }
fi

# Create output dir
OUT_DIR="release/$CUSTOMER"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# Copy exe
echo "Copying crc-check.exe..."
cp dist/crc-check.exe "$OUT_DIR/"

# Copy customer files
echo "Copying $CUSTOMER files..."
cp -r "$CUST_DIR"/* "$OUT_DIR/"

# Clean up traces from package
rm -rf "$OUT_DIR/trace"
mkdir -p "$OUT_DIR/trace"
rm -f "$OUT_DIR/report.html"

echo
echo "=== Package ready: $OUT_DIR ==="
ls -la "$OUT_DIR/"
echo
echo "To distribute, zip the $OUT_DIR folder."
