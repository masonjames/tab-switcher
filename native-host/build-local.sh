#!/bin/bash
# Local only: no installation, credentials, registration, notarization, or GUI launch.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP="$PROJECT_DIR/dist/Tab Switcher Local.app"
BUILD="$SCRIPT_DIR/.build-local"
mkdir -p "$BUILD/cache" "$BUILD/module-cache" "$BUILD/tmp"
export TMPDIR="$BUILD/tmp"
export CLANG_MODULE_CACHE_PATH="$BUILD/module-cache"
SWIFT_ARGS=(--package-path "$SCRIPT_DIR" --disable-sandbox --cache-path "$BUILD/cache" --scratch-path "$BUILD" -Xswiftc -module-cache-path -Xswiftc "$BUILD/module-cache")
swift build "${SWIFT_ARGS[@]}" -c release --force-resolved-versions
BIN_DIR=$(swift build "${SWIFT_ARGS[@]}" -c release --show-bin-path)
# Recreate only this script's output bundle, never an installed application.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Frameworks" "$APP/Contents/Resources"
cp "$BIN_DIR/tab-switcher" "$APP/Contents/MacOS/"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.masonjames.tabswitcher.local</string>
<key>CFBundleName</key><string>Tab Switcher Local</string>
<key>CFBundleDisplayName</key><string>Tab Switcher Local</string>
<key>CFBundleExecutable</key><string>tab-switcher</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>3.7.6</string>
<key>CFBundleVersion</key><string>3.7.6</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
<key>TabSwitcherLocalBuild</key><true/>
<key>SUEnableAutomaticChecks</key><false/>
<key>SUAutomaticallyUpdate</key><false/>
</dict></plist>
PLIST
python3 "$SCRIPT_DIR/generate-local-extension.py"
# SPM downloads/checks the binary artifact from the exact Sparkle 2.8.1 pin.
FRAMEWORK=$(find "$BUILD/artifacts" -type d -name Sparkle.framework -print -quit)
test -n "$FRAMEWORK"
ditto "$FRAMEWORK" "$APP/Contents/Frameworks/Sparkle.framework"
install_name_tool -add_rpath @executable_path/../Frameworks "$APP/Contents/MacOS/tab-switcher"
SPARKLE="$APP/Contents/Frameworks/Sparkle.framework/Versions/B"
for component in "$SPARKLE/XPCServices/Downloader.xpc" "$SPARKLE/XPCServices/Installer.xpc" "$SPARKLE/Autoupdate" "$SPARKLE/Updater.app" "$APP/Contents/Frameworks/Sparkle.framework"; do
    codesign --force --sign - --timestamp=none "$component"
done
codesign --force --sign - --timestamp=none "$APP"
codesign --verify --deep --strict "$APP"
plutil -lint "$APP/Contents/Info.plist"
printf 'Local artifact: %s\n' "$APP"
