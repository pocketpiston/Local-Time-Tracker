#!/bin/bash
# Build "Time Tracker.app" — a real macOS bundle wrapping timer_app.py, so the
# Dock and menu bar show "Time Tracker" and the project icon instead of
# "Python" and the generic rocket.
#
# Uses only macOS's own sips/iconutil — nothing to install.
#
#   ./build_app.sh            # build into ./dist
#   ./build_app.sh /Applications
#
# The bundle points back at this folder, so edits to timer_app.py take effect
# immediately — no rebuild needed unless you move the project or change Python.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$PROJECT_DIR/dist}"
APP="$DEST/Time Tracker.app"
PYTHON="$(command -v python3)"
PYTHON="$(cd "$(dirname "$PYTHON")" && pwd)/$(basename "$PYTHON")"

echo "Project : $PROJECT_DIR"
echo "Python  : $PYTHON"
echo "Target  : $APP"

if ! "$PYTHON" -c 'import tkinter' 2>/dev/null; then
  echo "ERROR: $PYTHON has no tkinter — the app needs a Python built with Tk." >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ── Icon: icon.png -> icon.icns at every size the Dock asks for ──────
if [ -f "$PROJECT_DIR/icon.png" ]; then
  ICONSET="$(mktemp -d)/icon.iconset"
  mkdir -p "$ICONSET"
  # Only these five base sizes are valid iconset names; adding e.g. 64 makes
  # iconutil reject the whole set with "Failed to generate ICNS".
  # -s format png is required: icon.png is really a JPEG, and sips keeps the
  # input format, so without this every tile is a JPEG named .png and iconutil
  # rejects the set with "Failed to generate ICNS".
  for size in 16 32 128 256 512; do
    double=$((size * 2))
    sips -s format png -z $size $size "$PROJECT_DIR/icon.png" \
         --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1
    sips -s format png -z $double $double "$PROJECT_DIR/icon.png" \
         --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/icon.icns"
  rm -rf "$(dirname "$ICONSET")"
  echo "Icon    : built from icon.png"
else
  echo "Icon    : icon.png not found — using the default"
fi

# ── Launcher ─────────────────────────────────────────────────────────
# Finder gives a bundle a minimal PATH, so the interpreter is referenced by
# absolute path rather than relying on `python3` resolving.
cat > "$APP/Contents/MacOS/TimeTracker" <<LAUNCHER
#!/bin/bash
cd "$PROJECT_DIR"
exec "$PYTHON" "$PROJECT_DIR/timer_app.py"
LAUNCHER
chmod +x "$APP/Contents/MacOS/TimeTracker"

# ── Info.plist ───────────────────────────────────────────────────────
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Time Tracker</string>
  <key>CFBundleDisplayName</key>       <string>Time Tracker</string>
  <key>CFBundleExecutable</key>        <string>TimeTracker</string>
  <key>CFBundleIdentifier</key>        <string>local.timetracker.desktop</string>
  <key>CFBundleIconFile</key>          <string>icon</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key>           <string>1</string>
  <key>NSHighResolutionCapable</key>   <true/>
  <key>LSMinimumSystemVersion</key>    <string>11.0</string>
</dict>
</plist>
PLIST

plutil -lint "$APP/Contents/Info.plist" >/dev/null
touch "$APP"   # nudge Finder to pick up the new icon

echo
echo "Built: $APP"
echo "Open it, or drag it to /Applications to launch from Spotlight and the Dock."
