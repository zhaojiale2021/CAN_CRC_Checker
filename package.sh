#!/bin/bash
# ============================================================
#  CAN CRC Checker — Package customer release
#
#  Usage:
#    ./package.sh              Package all customers
#    ./package.sh gac/t75      Package GAC T75 only
#    ./package.sh gwm/de09g    Package GWM DE09G only
#    ./package.sh chery/t1jfl3 Package Chery T1JFL3 only
#    ./package.sh chery/fx12fl Package Chery FX12FL only
#    ./package.sh chery/t1lfl1 Package Chery T1LFL1 only
#    ./package.sh baic/b81vs   Package BAIC B81VS only
# ============================================================
set -e

RELEASE_DIR="release"
ALL_CUSTOMERS=(
    "gac/t75"
    "gwm/de09g"
    "gwm/b06-5"
    "chery/t1jfl3"
    "chery/fx12fl"
    "chery/t1lfl1"
    "baic/b81vs"
)

package_one() {
    local CUST="$1"
    local CUST_SRC="customers/$CUST"
    local CUST_OUT="$RELEASE_DIR/$CUST"

    if [ ! -d "$CUST_SRC" ]; then
        echo "[WARN] Not found: $CUST_SRC"
        return
    fi

    echo "Packaging: $CUST"

    mkdir -p "$CUST_OUT" "$CUST_OUT/dbc" "$CUST_OUT/trace"

    cp dist/crc-check.exe "$CUST_OUT/" 2>/dev/null || true
    cp "$CUST_SRC"/config.json "$CUST_OUT/" 2>/dev/null || true
    cp "$CUST_SRC"/run.bat     "$CUST_OUT/" 2>/dev/null || true
    cp "$CUST_SRC"/run.sh      "$CUST_OUT/" 2>/dev/null || true
    cp "$CUST_SRC"/README.md   "$CUST_OUT/" 2>/dev/null || true
    cp "$CUST_SRC"/dbc/*.dbc   "$CUST_OUT/dbc/" 2>/dev/null || true
    cp "$CUST_SRC"/dbc/dataid.json "$CUST_OUT/dbc/" 2>/dev/null || true

    echo "  Done: $CUST_OUT"
}

# Check / build exe
if [ ! -f "dist/crc-check.exe" ]; then
    echo "Building exe..."
    cmd.exe /c build.bat
    if [ ! -f "dist/crc-check.exe" ]; then
        echo "Build failed!"
        exit 1
    fi
fi

# Clean release
rm -rf "$RELEASE_DIR"

echo
echo "========================================"
echo " CAN CRC Checker — Package Release"
echo "========================================"
echo

if [ -n "${1:-}" ]; then
    package_one "$1"
else
    for CUST in "${ALL_CUSTOMERS[@]}"; do
        package_one "$CUST"
    done
fi

echo
echo "========================================"
echo " Package Complete: $RELEASE_DIR"
echo "========================================"
ls -d "$RELEASE_DIR"/*/ 2>/dev/null || true
echo
