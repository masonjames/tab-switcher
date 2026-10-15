# Tab Switcher

> **Mason’s maintained fork:** For the customized version, follow [Mason’s local fork](#masons-local-fork) below and run `bash native-host/build-local.sh`. It builds the paired Local app and extension with five previews, backtick reverse, keyboard-listener recovery, and login/icon settings. The upstream download links and installation instructions below describe the original distribution; they do not install this fork. Local builds have upstream auto-updates disabled.

**Ctrl+Tab, reimagined.** Switch between browser tabs the way you switch between apps — with visual previews and most-recently-used ordering.

[Website](https://tabswitcher.app) · [Download](https://tabswitcher.app/Tab%20Switcher.dmg) · [Setup Guide](https://tabswitcher.app/setup)

## Features

- **Visual tab previews** — See thumbnails, favicons, and titles as you cycle through tabs
- **Most recently used order** — Tabs ordered by recency, not position. One Ctrl+Tab instantly jumps to your last tab
- **Copy URL shortcut** — Press Cmd+Shift+C to copy the current tab's URL to your clipboard with a confirmation toast
- **Customizable shortcuts** — Remap both the tab switcher and copy URL shortcuts to any key combination
- **Native performance** — A lightweight macOS companion app intercepts shortcuts at the system level
- **Multi-browser support** — Chrome, Brave, Edge, Arc, Vivaldi, Opera, and any Chromium-based browser
- **Auto-updates** — The native app updates itself automatically via Sparkle

## How It Works

Hold **Ctrl** and press **Tab** to bring up the visual switcher. Keep holding Ctrl and press Tab repeatedly to cycle through your tabs. Release Ctrl to switch to the selected tab.

Press **Cmd+Shift+C** to instantly copy the active tab's URL to your clipboard.

Works exactly like macOS app switching (Cmd+Tab), but for your browser tabs.

## Installation

Tab Switcher requires two components: a browser extension and a native macOS app.

### 1. Install the Extension

1. Download or clone this repository
2. Open Chrome and go to `chrome://extensions`
3. Enable **Developer mode** (toggle in top right)
4. Click **Load unpacked** and select this folder
5. Note the **Extension ID** shown (you'll need this later)

### 2. Install the Native App

Download the macOS app from [tabswitcher.app](https://tabswitcher.app/Tab%20Switcher.dmg).

1. Open the DMG and drag Tab Switcher to Applications
2. Open Tab Switcher from Applications
3. Grant Accessibility permission when prompted
4. Click **Enable** for your browser
5. Enter the **Extension ID** from step 1.5 and click **Save**

### 3. Grant Accessibility Permissions

If not prompted automatically:

1. Open **System Settings > Privacy & Security > Accessibility**
2. Enable the toggle next to Tab Switcher

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Ctrl+Tab** | Open switcher, cycle forward |
| **Ctrl+Shift+Tab** | Cycle backward |
| **Ctrl+`** | Cycle backward within an open switch session |
| **Cmd+Shift+C** | Copy current tab URL |
| **Alt+W** | Quick switch to last tab (no UI) |

All shortcuts can be customized in the app's setup window.

## Requirements

- macOS 14.0 or later
- Any Chromium-based browser (Chrome, Brave, Edge, Arc, Vivaldi, Opera, etc.)
- Accessibility permissions for the native app

## Privacy

Tab Switcher operates entirely locally. No data is collected, stored, or transmitted. See our [Privacy Policy](https://tabswitcher.app/privacy).

## Building from Source

### Extension
The extension files are in the root directory. Load unpacked in Chrome.

### Native App
```bash
cd native-host
swift build -c release
```

The built binary will be at `native-host/.build/release/tab-switcher`. To create a full app bundle with the Sparkle framework embedded:

```bash
cd native-host
./build.sh
```

The app bundle will be at `dist/Tab Switcher.app`. Code signing and notarization require a valid Apple Developer ID certificate and are optional for local development:

```bash
./build.sh --sign              # build + code sign
./build.sh --sign --notarize   # build + sign + notarize
```

## Project Structure

```
├── manifest.json          # Chrome extension manifest
├── mainsw.js              # Extension service worker
├── popup.html/js          # Extension popup UI
├── icon*.png              # Extension icons
├── native-host/
│   ├── Package.swift      # Swift package definition
│   ├── Sources/
│   │   └── tab-switcher/
│   │       └── main.swift # Native macOS app
│   ├── build.sh           # Build + sign + notarize script
│   ├── install.sh         # Install native messaging host
│   └── uninstall.sh       # Uninstall native messaging host
└── docs/                  # Website (GitHub Pages)
    ├── index.html
    ├── setup.html
    └── privacy.html
```

## Troubleshooting

**Extension shows "Not connected":**
- Make sure the Tab Switcher app is running
- Check that you've granted Accessibility permissions
- Verify the Extension ID was entered correctly

**Ctrl+Tab doesn't work:**
- Verify Accessibility permissions are enabled for the native app.
- Make sure the browser window is focused.
- In the original v3.7.5 app, granting permission after first launch can leave the keyboard listener inactive. Quit and reopen the **Tab Switcher app**; restarting Chrome alone does not restart the app that owns the listener.
- This branch retries an inactive keyboard listener every five seconds after Accessibility permission is granted, and re-enables listeners disabled by macOS after a timeout.
- The extension's “Connected” status confirms native messaging, not keyboard-listener health.

**Run the keyboard-listener recovery tests:**
```bash
cd native-host
swift test
```

For more help, visit the [Setup Guide](https://tabswitcher.app/setup).

## License

MIT License — see [LICENSE](LICENSE)

## Mason’s local fork

For repeatable signed, notarized releases, see [Releasing the Local fork](docs/releasing.md).

Run `bash native-host/build-local.sh` from a clean checkout to produce
`dist/Tab Switcher Local.app`. This standalone, ad-hoc signed bundle embeds the
pinned Sparkle 2.8.1 framework and fixes its runtime search path. The script needs
Swift/Xcode command-line tools and network access for SwiftPM dependencies; it
uses repository-local caches and disables the nested SwiftPM build sandbox so it
can run under an enclosing build sandbox. It does not install or launch anything,
use signing credentials, notarize, or register a login item. The original
`build.sh` is the upstream publishing workflow; do not use it for this fork.

The local bundle ID is `com.masonjames.tabswitcher.local`. Upstream app updates
are disabled in code and the generated plist. Settings use
`~/Library/Application Support/TabSwitcherLocal`, separate from the upstream app;
missing companion settings migrate to Dock on, menu bar off, login off, and five
recent tabs. Build output `dist/extension-local` is the paired unpacked extension;
load that directory, not the repository root, for Local. Its checked-in public
manifest key produces a stable extension ID, embedded in the app's Info.plist.
The local app writes/removes only `com.masonjames.tabswitcher.local.json` native
host manifests, authorizing only that extension. The source extension in the
repository root remains compatible with the upstream host.

Before enabling Local, disable the original extension in **every browser/profile**
and quit the original companion. Then load `dist/extension-local` and enable your
browser in Local settings. Local passes browser shortcuts through while the PID
in the original event-tap leader record is alive, including a leader whose tap
initially failed. Settings displays this conflict and refreshes automatically.
No process is stopped automatically and upstream registrations are left intact.
A stale record pointing to a reused live PID conservatively blocks Local; inspect
that situation rather than deleting live state blindly. Build steps do not edit
live browser registrations, preferences, or Accessibility permissions.

Ctrl+Tab immediately requests the visual MRU switcher with the previous tab
selected. Repeated Tab advances; backtick (`) or Shift+Tab reverses in the same
session; release Ctrl commits. Custom shortcuts use the same base modifiers for
backtick, which is intercepted only during a switch. The recent-tab limit is
configurable from 2–12 (default 5, including the current tab), after filtering to
the current window. The existing all-windows setting remains available. Cards shrink together to fit
the switcher panel. Panel placement on secondary monitors or partly offscreen
browser windows still needs runtime verification. Cmd+Shift+C still copies the URL.

Companion settings independently control Dock and menu bar visibility. Both can
be off; reopen the app from Applications/Spotlight to show settings. Closing
settings keeps the helper alive; Cmd+Q or the optional menu’s Quit exits.
Launch at login uses `SMAppService.mainApp`, registers only on a user toggle,
and shows actual macOS status, approval requirements, and errors. Login launches
show no setup window or permission prompts. Native messaging children never own
companion icons or register login items. Accessibility may need to be granted
separately to this local identity; ad-hoc signing does not bypass permission or
login-item approval.

Local checks: `cd native-host && swift test`; from the repository root,
`bash native-host/build-local.sh && bun test tests` (the packaging test inspects
the generated app/extension pair). Runtime launch/reopen, Accessibility,
login approval and hidden startup, all icon combinations, native messaging,
copy URL, and Chrome keyboard behavior still require attended testing.

Validation on macOS 27.0.1 with Chrome 155 (October 14, 2026): 13 Swift tests and
7 Bun tests passed; the local app/extension connected, five-tab overlays and
forward/reverse events appeared in native logs, and settings reopened with both
icons hidden. macOS reported launch at login enabled. Exact physical backtick
behavior, the clipboard result, and startup after an actual login remain attended
checks; no logout or reboot was performed.
