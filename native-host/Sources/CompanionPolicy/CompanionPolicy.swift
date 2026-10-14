import Foundation
import Darwin

public struct CompanionPreferences: Codable, Equatable {
    public var showDockIcon = true
    public var showMenuBarIcon = false
    public var launchAtLogin = false // User intent; ServiceManagement remains authoritative.
    public var recentTabLimit = 5
    public init() {}
    enum CodingKeys: String, CodingKey { case showDockIcon, showMenuBarIcon, launchAtLogin, recentTabLimit }
    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        showDockIcon = try values.decodeIfPresent(Bool.self, forKey: .showDockIcon) ?? true
        showMenuBarIcon = try values.decodeIfPresent(Bool.self, forKey: .showMenuBarIcon) ?? false
        launchAtLogin = try values.decodeIfPresent(Bool.self, forKey: .launchAtLogin) ?? false
        recentTabLimit = min(12, max(2, try values.decodeIfPresent(Int.self, forKey: .recentTabLimit) ?? 5))
    }
    public static func load(from url: URL) -> Self {
        guard let data = try? Data(contentsOf: url), let value = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        return value
    }
    public func save(to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONEncoder().encode(self).write(to: url, options: .atomic)
    }
}

public enum StartupRole: Equatable {
    case nativeHost, interactive, login
    public static func resolve(nativeHost: Bool, loginItem: Bool) -> Self {
        nativeHost ? .nativeHost : (loginItem ? .login : .interactive)
    }
    public var isCompanion: Bool { self != .nativeHost }
    public var showsSettingsOnLaunch: Bool { self == .interactive }
    public func showsDock(preferences: CompanionPreferences) -> Bool { isCompanion && preferences.showDockIcon }
    public func showsMenu(preferences: CompanionPreferences) -> Bool { isCompanion && preferences.showMenuBarIcon }
}

/// A held file descriptor makes election atomic and releases ownership on process exit.
/// Never unlink a flock file: contenders must all use the same inode.
public final class InstanceLock {
    private var descriptor: Int32 = -1
    public init() {}
    public func acquire(at url: URL) throws -> Bool {
        if descriptor >= 0 { return true }
        let fd = open(url.path, O_CREAT | O_RDWR | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard fd >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        if flock(fd, LOCK_EX | LOCK_NB) != 0 {
            let error = errno
            close(fd)
            if error == EWOULDBLOCK { return false }
            throw POSIXError(POSIXErrorCode(rawValue: error) ?? .EIO)
        }
        descriptor = fd
        return true
    }
    deinit { if descriptor >= 0 { close(descriptor) } }
}

public func switchDirection(key: Int64, primaryKey: Int64, graveKey: Int64,
                            baseModifiers: UInt64, currentModifiers: UInt64,
                            shiftMask: UInt64, inProgress: Bool) -> Int? {
    let base = baseModifiers & ~shiftMask
    guard base != 0, currentModifiers & ~shiftMask == base else { return nil }
    if key == graveKey && inProgress { return -1 }
    guard key == primaryKey else { return nil }
    return currentModifiers & shiftMask == 0 ? 1 : -1
}

public struct NativeHostRegistration {
    public let name: String
    public let extensionIDs: [String]
    public init(localExtensionID: String?, upstreamID: String, legacyID: String? = nil) {
        if let localExtensionID {
            name = "com.masonjames.tabswitcher.local"
            extensionIDs = [localExtensionID]
        } else {
            name = "com.tabswitcher.native"
            extensionIDs = [upstreamID] + (legacyID.map { $0.isEmpty || $0 == upstreamID ? [] : [$0] } ?? [])
        }
    }
    public func update(directory: URL, executable: String, enabled: Bool) throws {
        let path = directory.appendingPathComponent(name + ".json")
        if enabled {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let manifest: [String: Any] = ["name": name, "description": "Tab Switcher Native Helper",
                "path": executable, "type": "stdio",
                "allowed_origins": extensionIDs.map { "chrome-extension://\($0)/" }]
            try JSONSerialization.data(withJSONObject: manifest, options: .prettyPrinted).write(to: path, options: .atomic)
        } else if FileManager.default.fileExists(atPath: path.path) {
            try FileManager.default.removeItem(at: path)
        }
    }
}

/// Conservative: any live PID in the original leader record blocks local consumption.
/// This also covers an original leader whose first tap creation failed before permission.
public func originalLeaderIsAlive(record: String?, isAlive: (Int32) -> Bool) -> Bool {
    guard let record, let pid = Int32(record.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 1 else { return false }
    return isAlive(pid)
}

/// A held-modifier session cannot silently start cycling a second browser.
public func acceptsSessionBrowser(target: String?, frontmost: String) -> Bool {
    target == nil || target == frontmost
}

public func browserConfigurationNotification(namespace: String) -> Notification.Name {
    Notification.Name(namespace + ".browserConfigurationChanged")
}

public func observeBrowserConfigurationChanges(namespace: String, center: NotificationCenter = DistributedNotificationCenter.default(), reload: @escaping () -> Void) -> any NSObjectProtocol {
    center.addObserver(
        forName: browserConfigurationNotification(namespace: namespace), object: nil, queue: .main
    ) { _ in reload() }
}
