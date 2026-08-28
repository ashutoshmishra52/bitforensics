# BitForensics installers

Built packages land in `release/`.

## macOS (.dmg) — native desktop app

```bash
./packaging/build_macos_dmg.sh
```

Output: `release/BitForensics-macOS-arm64.dmg`

- Opens a **real macOS application window** (pywebview) — not Chrome/Safari localhost
- Drag `BitForensics.app` to Applications
- First launch installs Python packages once (internet required once)
- Needs Python 3.9+ on the Mac


## Linux (.tar.gz installer)

```bash
chmod +x packaging/build_linux.sh
./packaging/build_linux.sh
```

Output: `release/BitForensics-linux-x86_64.tar.gz`

On Linux:

```bash
tar -xzf BitForensics-linux-x86_64.tar.gz
cd BitForensics-linux
./install.sh
bitforensics
```

Uninstall: `./uninstall.sh`

Needs **Python 3.9+**. First launch installs pip packages (internet once).

## Dev (no installer)

```bash
npm run dev
# or
python run.py
```
