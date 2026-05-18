#!/bin/bash
set -euo pipefail

VERSION="${1:-dev}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"

mkdir -p "$DIST"
cd "$ROOT/apps/android"

if command -v ./gradlew >/dev/null 2>&1; then
  ./gradlew assembleDebug
else
  gradle assembleDebug
fi

cp "$ROOT/apps/android/app/build/outputs/apk/debug/app-debug.apk" "$DIST/HKMaintenance-Android-$VERSION-debug.apk"
echo "Created $DIST/HKMaintenance-Android-$VERSION-debug.apk"
