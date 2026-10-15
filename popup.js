// Each refresh asks the elected native listener for a fresh runtime sample.
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("status-text");
const healthDetailEl = document.getElementById("health-detail");
const refreshEl = document.getElementById("refresh-health");
let healthRequest = 0;
const companionApp = chrome.runtime.getManifest().name === "Tab Switcher Local" ? "Tab Switcher Local" : "Tab Switcher";
const healthDetails = {
  permissionDenied: `macOS is denying keyboard access even if its switch is ON. In System Settings → Privacy & Security → Device Control and Data Access (or Accessibility), remove only ${companionApp}. Add /Applications/${companionApp}.app again, enable it, then recheck.`,
  listenerUnavailable: "The keyboard listener is inactive. Wait a few seconds and recheck. If it persists, open the app’s settings for permission recovery steps.",
  originalConflict: "The original Tab Switcher helper is running. Disable its extension in every browser/profile and quit the original companion, then recheck.",
  secureInput: "Secure Input is active. Finish password entry or turn off Secure Keyboard Entry in the app using it, then recheck.",
  unknown: "Couldn’t verify shortcuts. Recheck in a moment. If this continues, quit and reopen the app, or update the app if it is an older version.",
  ready: "Permission and listener checks passed. Try your shortcuts to confirm they work in this browser."
};
function refreshHealth() {
  const request = ++healthRequest;
  statusEl.className = "status warning";
  statusTextEl.textContent = "Checking shortcuts…";
  healthDetailEl.textContent = "";
  refreshEl.disabled = true;
  chrome.runtime.sendMessage({ action: "ping_native_host" }, function(response) {
    if (request !== healthRequest) return;
    refreshEl.disabled = false;
    if (chrome.runtime.lastError || !response || !response.connected) {
      statusEl.className = "status disconnected";
      statusTextEl.textContent = "Not connected — is the app running?";
      healthDetailEl.textContent = "The app did not respond. Recheck after opening the app.";
      return;
    }
    const health = Object.prototype.hasOwnProperty.call(healthDetails, response.shortcutHealth) ? response.shortcutHealth : "unknown";
    statusEl.className = health === "ready" ? "status connected" : "status warning";
    statusTextEl.textContent = health === "ready" ? "Shortcuts ready"
      : health === "unknown" ? "App connected — shortcut status unknown"
      : "App connected — shortcuts unavailable";
    healthDetailEl.textContent = healthDetails[health];
  });
}
refreshEl.addEventListener("click", refreshHealth);
refreshHealth();

// Version info and update banner
function compareVersions(a, b) {
  var partsA = a.split(".").map(Number);
  var partsB = b.split(".").map(Number);
  for (var i = 0; i < Math.max(partsA.length, partsB.length); i++) {
    var numA = partsA[i] || 0;
    var numB = partsB[i] || 0;
    if (numA < numB) return -1;
    if (numA > numB) return 1;
  }
  return 0;
}

var versionLabel = document.getElementById("version-label");
var currentVersion = chrome.runtime.getManifest().version;
versionLabel.textContent = "v" + currentVersion;

// Load custom shortcut display from storage
chrome.storage.local.get("shortcuts", function(data) {
  if (data.shortcuts) {
    if (data.shortcuts.tabSwitch) {
      var el = document.getElementById("tab-switch-keys");
      if (el) el.innerHTML = '<span class="key">' + data.shortcuts.tabSwitch + '</span>';
    }
    if (data.shortcuts.copyUrl) {
      var el = document.getElementById("copy-url-keys");
      if (el) el.innerHTML = '<span class="key">' + data.shortcuts.copyUrl + '</span>';
    }
  }
});

chrome.runtime.sendMessage({ action: "get_version_info" }, function(info) {
  if (chrome.runtime.lastError || !info) return;

  var banner = document.getElementById("update-banner");

  // Priority 1: CWS migration banner for manual installs
  if (info.isManualInstall && info.chromeWebStoreUrl) {
    banner.className = "update-banner cws";
    banner.innerHTML = 'Now on the Chrome Web Store! <a href="' + info.chromeWebStoreUrl + '" target="_blank">Install for automatic updates</a>';
    banner.style.display = "block";
    return;
  }

  // Priority 2: Update available for manual installs
  if (info.isManualInstall && info.latestExtensionVersion && compareVersions(currentVersion, info.latestExtensionVersion) < 0) {
    banner.className = "update-banner update";
    banner.innerHTML = 'Update available (v' + info.latestExtensionVersion + ') — <a href="https://tabswitcher.app/setup" target="_blank">Download</a>';
    banner.style.display = "block";
  }
});
