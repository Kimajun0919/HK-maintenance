#!/bin/bash
set -euo pipefail

VERSION="${1:-dev}"
OUTPUT_DIR="${2:-dist}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/$OUTPUT_DIR"
WORK="$DIST/macos-app"
APP="$WORK/HK Maintenance.app"
ZIP="$DIST/HKMaintenance-macOS-$VERSION.zip"

mkdir -p "$DIST"
rm -rf "$WORK" "$ZIP"
mkdir -p "$WORK"

if ! command -v osacompile >/dev/null 2>&1; then
  echo "osacompile is required. Run this on macOS."
  exit 1
fi

cat > "$WORK/HKMaintenance.applescript" <<'APPLESCRIPT'
on run
  do shell script "open http://127.0.0.1:7860"
end run
APPLESCRIPT

osacompile -o "$APP" "$WORK/HKMaintenance.applescript"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
echo "Created $ZIP"
