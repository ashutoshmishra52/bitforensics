#!/usr/bin/env bash
# Build BitForensics Linux installable tarball into release/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$ROOT/release/BitForensics-linux"
OUT="$ROOT/release/BitForensics-linux-x86_64.tar.gz"

rm -rf "$STAGE"
mkdir -p "$STAGE/app" "$STAGE/bin" "$ROOT/release"

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
  "$ROOT/" "$STAGE/app/"

cp "$ROOT/packaging/launch_bitforensics.py" "$STAGE/app/launch_bitforensics.py"
cp "$ROOT/icon.png" "$STAGE/bitforensics.png" 2>/dev/null || true

# CLI launcher
cat > "$STAGE/bin/bitforensics" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HERE/app"
cd "$APP"

PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    PY="$(command -v "$c")"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9+ required. Install python3 and retry."
  exit 1
fi

export PORT="${PORT:-8000}"
export BITFORENSICS_RELOAD=0
export HOST=127.0.0.1
exec "$PY" "$APP/launch_bitforensics.py"
EOF
chmod +x "$STAGE/bin/bitforensics"

# install.sh
cat > "$STAGE/install.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local/share/bitforensics}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
APP_DIR="$PREFIX"

echo "Installing BitForensics → $APP_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR"
rsync -a --delete "$HERE/app/" "$APP_DIR/app/"
install -m 755 "$HERE/bin/bitforensics" "$BIN_DIR/bitforensics"
# Rewrite launcher paths for installed location
cat > "$BIN_DIR/bitforensics" <<INNER
#!/usr/bin/env bash
set -euo pipefail
APP="$APP_DIR/app"
cd "\$APP"
PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  command -v "\$c" >/dev/null 2>&1 && PY="\$(command -v "\$c")" && break
done
[ -n "\$PY" ] || { echo "Python 3.9+ required"; exit 1; }
export PORT="\${PORT:-8000}" BITFORENSICS_RELOAD=0 HOST=127.0.0.1
exec "\$PY" "\$APP/launch_bitforensics.py"
INNER
chmod +x "$BIN_DIR/bitforensics"

# Desktop entry
DESK="$HOME/.local/share/applications"
mkdir -p "$DESK"
ICON="$APP_DIR/bitforensics.png"
[ -f "$HERE/bitforensics.png" ] && cp "$HERE/bitforensics.png" "$ICON"
cat > "$DESK/bitforensics.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=BitForensics
Comment=Offline Bitcoin forensic dashboard (SIH PS 26146)
Exec=$BIN_DIR/bitforensics
Icon=$ICON
Terminal=true
Categories=Science;Security;
StartupNotify=true
DESK

echo ""
echo "Installed."
echo "  Run:  bitforensics"
echo "  Or:   $BIN_DIR/bitforensics"
echo "  UI:   http://localhost:8000"
echo ""
echo "Ensure $BIN_DIR is on PATH (e.g. export PATH=\"\$HOME/.local/bin:\$PATH\")."
echo "First launch installs Python packages (internet once)."
EOF
chmod +x "$STAGE/install.sh"

cat > "$STAGE/uninstall.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
PREFIX="${PREFIX:-$HOME/.local/share/bitforensics}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
rm -f "$BIN_DIR/bitforensics"
rm -f "$HOME/.local/share/applications/bitforensics.desktop"
rm -rf "$PREFIX"
echo "BitForensics removed."
EOF
chmod +x "$STAGE/uninstall.sh"

cat > "$STAGE/README-INSTALL.txt" <<'EOF'
BitForensics — Linux install
============================

Requirements: Python 3.9+, pip, internet once (first launch).

  tar -xzf BitForensics-linux-x86_64.tar.gz
  cd BitForensics-linux
  ./install.sh
  bitforensics

Browser opens http://localhost:8000

Uninstall:
  ./uninstall.sh

SIH 2026 · PS 26146 · NTRO
EOF

# Also ship a desktop template
cat > "$STAGE/bitforensics.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=BitForensics
Comment=Offline Bitcoin forensic dashboard (SIH PS 26146)
Exec=bitforensics
Icon=bitforensics
Terminal=true
Categories=Science;Security;
EOF

tar -C "$ROOT/release" -czf "$OUT" BitForensics-linux
echo ""
echo "Built: $OUT"
ls -lh "$OUT"
