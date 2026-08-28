#!/usr/bin/env bash
# Build BitForensics macOS .app + DMG into release/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$ROOT/release/stage-macos"
APP="$STAGE/BitForensics.app"
RES="$APP/Contents/Resources/app"
DMG="$ROOT/release/BitForensics-macOS-$(uname -m).dmg"
VOL="BitForensics"

rm -rf "$STAGE"
mkdir -p "$APP/Contents/MacOS" "$RES" "$ROOT/release"

# Copy application payload
rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'venv' \
  --exclude 'node_modules' \
  --exclude 'release' \
  --exclude '.cursor' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'data/bitforensics.db' \
  --exclude 'data/exports' \
  --exclude 'data/geoip/*.mmdb' \
  --exclude 'data/geoip/*.mmdb.gz' \
  --exclude '.DS_Store' \
  "$ROOT/" "$RES/"

# Native desktop entry + helpers
cp "$ROOT/packaging/desktop_app.py" "$RES/desktop_app.py"
cp "$ROOT/packaging/launch_bitforensics.py" "$RES/launch_bitforensics.py"

# Executable stub — native window (no browser / no Terminal)
cat > "$APP/Contents/MacOS/BitForensics" <<'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$DIR/../Resources/app"
cd "$APP_ROOT"
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    PY="$(command -v "$c")"
    break
  fi
done
if [ -z "$PY" ]; then
  osascript -e 'display dialog "Python 3.9+ is required to run BitForensics.\n\nInstall from python.org (tick Add to PATH), then open the app again." buttons {"OK"} default button 1 with title "BitForensics"'
  exit 1
fi

export PORT="${PORT:-8765}"
export BITFORENSICS_RELOAD=0
export HOST=127.0.0.1
export PYTHONUNBUFFERED=1

# First-run notice
if [ ! -f "$APP_ROOT/.venv/.desktop-ok" ]; then
  osascript -e 'display dialog "First launch: BitForensics will install its engine (needs internet once, ~1–3 min). Then a desktop window opens — not a browser tab." buttons {"Continue"} default button 1 with title "BitForensics Setup"' >/dev/null || true
fi

LOG="$APP_ROOT/data/desktop.log"
mkdir -p "$APP_ROOT/data"
# Run native desktop app (API + OS window)
"$PY" "$APP_ROOT/desktop_app.py" >>"$LOG" 2>&1
STATUS=$?
if [ $STATUS -ne 0 ]; then
  osascript -e "display dialog \"BitForensics failed to start. See log:\n$LOG\" buttons {\"OK\"} default button 1 with title \"BitForensics\""
fi
exit $STATUS
EOF
chmod +x "$APP/Contents/MacOS/BitForensics"

# Info.plist
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>BitForensics</string>
  <key>CFBundleDisplayName</key><string>BitForensics</string>
  <key>CFBundleIdentifier</key><string>com.ntro.bitforensics</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>BitForensics</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsArbitraryLoads</key><true/>
  </dict>
</dict>
</plist>
EOF

# Icon (build outside the DMG contents so iconset folder is NOT on the disk)
if [ -f "$ROOT/icon.png" ]; then
  ICONSET="$ROOT/release/_AppIcon.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  sips -z 16 16     "$ROOT/icon.png" --out "$ICONSET/icon_16x16.png" >/dev/null
  sips -z 32 32     "$ROOT/icon.png" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 32 32     "$ROOT/icon.png" --out "$ICONSET/icon_32x32.png" >/dev/null
  sips -z 64 64     "$ROOT/icon.png" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 128 128   "$ROOT/icon.png" --out "$ICONSET/icon_128x128.png" >/dev/null
  sips -z 256 256   "$ROOT/icon.png" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 256 256   "$ROOT/icon.png" --out "$ICONSET/icon_256x256.png" >/dev/null
  sips -z 512 512   "$ROOT/icon.png" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 512 512   "$ROOT/icon.png" --out "$ICONSET/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ROOT/icon.png" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true
  rm -rf "$ICONSET"
fi

# Clean DMG root: ONLY the app + Applications shortcut (+ short install note)
DMG_ROOT="$ROOT/release/dmg-root"
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
cp -R "$APP" "$DMG_ROOT/BitForensics.app"
ln -sf /Applications "$DMG_ROOT/Applications"
cat > "$DMG_ROOT/How to Install.txt" <<'EOF'
Install BitForensics
====================

1. Drag "BitForensics" onto the "Applications" folder (in this window).
2. Open Applications → BitForensics (first time: right-click → Open).
3. A desktop app window opens (not a browser).

Needs Python 3.9+ once. First launch may take 1–3 minutes online.
EOF

rm -f "$DMG"
hdiutil create \
  -volname "$VOL" \
  -srcfolder "$DMG_ROOT" \
  -ov -format UDZO \
  "$DMG"

rm -rf "$DMG_ROOT" "$STAGE"

echo ""
echo "Built: $DMG"
ls -lh "$DMG"
echo ""
echo "Open the DMG → drag BitForensics into Applications → then launch the app."
