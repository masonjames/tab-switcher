"""Generate the isolated unpacked extension and bind its ID into the local app."""
import base64
import hashlib
import json
import pathlib
import plistlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOST = "com.masonjames.tabswitcher.local"
key = (ROOT / "native-host/local-extension/public-key.txt").read_text().strip()
digest = hashlib.sha256(base64.b64decode(key, validate=True)).hexdigest()[:32]
extension_id = "".join(chr(ord("a") + int(char, 16)) for char in digest)
destination = ROOT / "dist/extension-local"
destination.mkdir(parents=True, exist_ok=True)
manifest = json.loads((ROOT / "manifest.json").read_text())
manifest.update(name="Tab Switcher Local", short_name="TabSwitch Local", key=key)
(destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
for name in ["popup.html", "popup.js", *manifest["icons"].values()]:
    shutil.copyfile(ROOT / name, destination / name)
worker = (ROOT / "mainsw.js").read_text()
assert worker.count('connectNative("com.tabswitcher.native")') == 1
worker = worker.replace('connectNative("com.tabswitcher.native")', f'connectNative("{HOST}")')
# Keep local users on the local setup instructions rather than the upstream migration banner.
worker = worker.replace('checkForUpdates();\nsetInterval(checkForUpdates, VERSION_CHECK_INTERVAL);', '')
worker = worker.replace('chrome.tabs.create({ url: SETUP_PAGE_URL });', '// Local migration instructions are supplied with the build.')
(destination / "mainsw.js").write_text(worker)
plist_path = ROOT / "dist/Tab Switcher Local.app/Contents/Info.plist"
with plist_path.open("rb") as file:
    info = plistlib.load(file)
info["TabSwitcherLocalExtensionID"] = extension_id
with plist_path.open("wb") as file:
    plistlib.dump(info, file)
print(f"Local extension: {destination} (ID {extension_id})")
