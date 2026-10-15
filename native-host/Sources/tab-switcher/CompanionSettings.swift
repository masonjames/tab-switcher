import AppKit
import SwiftUI
import ServiceManagement
import CompanionPolicy
import EventTapLifecycle

let isLocalBuild = Bundle.main.object(forInfoDictionaryKey: "TabSwitcherLocalBuild") as? Bool == true
let configurationDirectory = isLocalBuild ? "TabSwitcherLocal" : "TabSwitcher"
let ipcNamespace = isLocalBuild ? "com.masonjames.tabswitcher.local" : "com.tabswitcher"
let companionInstanceLock = InstanceLock()
var companionOwnsInstance = false

func originalHelperConflict() -> Bool {
    guard isLocalBuild else { return false }
    let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".tabswitcher_eventtap.lock")
    return originalLeaderIsAlive(record: try? String(contentsOf: url, encoding: .utf8)) {
        kill($0, 0) == 0 || errno == EPERM
    }
}

let permissionRecoveryGuidance = "Open System Settings → Privacy & Security → Device Control and Data Access (macOS 27), or Accessibility on older macOS. The switch may already be ON even when macOS denies access. " + (isLocalBuild
    ? "Remove only the Tab Switcher Local entry, add the exact /Applications/Tab Switcher Local.app again, and enable it."
    : "Remove only the Tab Switcher entry, add /Applications/Tab Switcher.app again, and enable it.") + " Then retry. Shortcut access is also checked again automatically."

func openPermissionSettings() {
    if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
        NSWorkspace.shared.open(url)
    }
}

func shortcutHealthDescription(_ health: ShortcutHealth) -> String {
    switch health {
    case .ready: return "Shortcuts ready — permission and listener checks passed."
    case .permissionDenied: return "Shortcuts unavailable — macOS is denying permission. " + permissionRecoveryGuidance
    case .listenerUnavailable: return "Shortcuts unavailable — the keyboard listener is inactive. Retry in a few seconds. If it persists, check permission. " + permissionRecoveryGuidance
    case .originalConflict: return "Shortcuts unavailable — the original Tab Switcher helper is running. Disable its extension in every browser/profile and quit the original companion."
    case .secureInput: return "Shortcuts unavailable — Secure Input is active. Finish entering passwords or turn off Secure Keyboard Entry in the app using it, then retry."
    case .unknown: return "Couldn’t verify shortcuts. Retry in a moment. If this continues, quit and reopen the app and check that the latest version is installed."
    }
}

final class CompanionSettings: ObservableObject {
    static let shared = CompanionSettings()
    private let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        .appendingPathComponent(configurationDirectory).appendingPathComponent("companion.json")
    @Published var preferences: CompanionPreferences
    @Published var loginStatus: SMAppService.Status = .notRegistered
    @Published var errorMessage: String?
    @Published var shortcutHealth: ShortcutHealth = .unknown
    @Published var checkingHealth = false
    func refreshHealth() {
        guard !checkingHealth else { return }
        checkingHealth = true
        shortcutHealth = .unknown
        requestShortcutHealth { [weak self] health in
            self?.shortcutHealth = health
            self?.checkingHealth = false
        }
    }
    @Published var originalConflict = false
    func refreshConflict() { originalConflict = originalHelperConflict() }

    init() { preferences = CompanionPreferences.load(from: url) }
    func refreshLoginStatus() { loginStatus = SMAppService.mainApp.status }
    var loginEnabled: Bool { loginStatus == .enabled || loginStatus == .requiresApproval }
    var loginDescription: String {
        switch loginStatus {
        case .enabled: return "Enabled"
        case .notRegistered: return "Off"
        case .requiresApproval: return "Approval required in System Settings → General → Login Items"
        case .notFound: return "Unavailable: macOS could not find the app service"
        @unknown default: return "Unknown macOS registration status"
        }
    }
    func save() {
        do {
            try preferences.save(to: url)
            errorMessage = nil
            DistributedNotificationCenter.default().postNotificationName(
                NSNotification.Name(ipcNamespace + ".preferencesChanged"), object: nil,
                userInfo: nil, deliverImmediately: true)
            (NSApp.delegate as? AppDelegate)?.applyCompanionAppearance()
        } catch { errorMessage = "Could not save settings: \(error.localizedDescription)" }
    }
    func reload() { preferences = CompanionPreferences.load(from: url) }
    // Only a settings control calls this; launch and preference loading never register.
    func setLaunchAtLogin(_ enabled: Bool) {
        guard companionOwnsInstance else { return }
        do {
            if enabled { try SMAppService.mainApp.register() }
            else { try SMAppService.mainApp.unregister() }
            preferences.launchAtLogin = enabled
            save()
        } catch { errorMessage = "Login setting failed: \(error.localizedDescription)" }
        refreshLoginStatus()
    }
}

struct CompanionSettingsView: View {
    @ObservedObject var settings = CompanionSettings.shared
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Companion").font(.headline)
            Text(settings.checkingHealth ? "Checking shortcuts…" : shortcutHealthDescription(settings.shortcutHealth))
                .font(.caption).foregroundColor(settings.shortcutHealth == .ready ? .secondary : .orange)
            HStack {
                Button("Open permission settings") { openPermissionSettings() }
                Button("Retry") { settings.refreshHealth() }.disabled(settings.checkingHealth)
                Button("Reveal app") {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: isLocalBuild
                        ? "/Applications/Tab Switcher Local.app" : "/Applications/Tab Switcher.app")])
                }
            }
            if isLocalBuild {
                Text(settings.originalConflict
                    ? "Original Tab Switcher leader is still running. Local keyboard shortcuts are paused. Disable the original extension in every browser/profile, then quit the original companion before enabling Local."
                    : "Before enabling Local: disable the original extension in every browser/profile and quit the original companion. Load dist/extension-local, then enable your browser here.")
                    .font(.caption).foregroundStyle(settings.originalConflict ? .orange : .secondary)
            }
            Toggle("Launch at login", isOn: Binding(get: { settings.loginEnabled }, set: { settings.setLaunchAtLogin($0) }))
            Text(settings.loginDescription).font(.caption).foregroundStyle(.secondary)
            if settings.loginStatus == .requiresApproval || settings.loginStatus == .notFound {
                Button("Open Login Items Settings") { SMAppService.openSystemSettingsLoginItems() }
            }
            Toggle("Show Dock icon", isOn: $settings.preferences.showDockIcon)
                .onChange(of: settings.preferences.showDockIcon) { settings.save() }
            Toggle("Show menu bar icon", isOn: $settings.preferences.showMenuBarIcon)
                .onChange(of: settings.preferences.showMenuBarIcon) { settings.save() }
            Stepper("Recent tabs: \(settings.preferences.recentTabLimit)", value: $settings.preferences.recentTabLimit, in: 2...12)
                .onChange(of: settings.preferences.recentTabLimit) { settings.save() }
            Text("Both icons can be hidden. Reopen the app from Applications or Spotlight for settings. Closing this window keeps the helper running; ⌘Q quits.")
                .font(.caption).foregroundStyle(.secondary)
            if let error = settings.errorMessage { Text(error).font(.caption).foregroundStyle(.red) }
        }
        .onAppear { settings.refreshLoginStatus(); settings.refreshConflict(); settings.refreshHealth() }
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in settings.refreshConflict(); settings.refreshHealth() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in settings.refreshLoginStatus() }
    }
}
