import XCTest
@testable import CompanionPolicy

final class CompanionPolicyTests: XCTestCase {
    func testDefaultsAndMigration() throws {
        let defaults = CompanionPreferences()
        XCTAssertTrue(defaults.showDockIcon)
        XCTAssertFalse(defaults.showMenuBarIcon)
        XCTAssertFalse(defaults.launchAtLogin)
        XCTAssertEqual(defaults.recentTabLimit, 5)
        let migrated = try JSONDecoder().decode(CompanionPreferences.self, from: Data(#"{"showDockIcon":false}"#.utf8))
        XCTAssertFalse(migrated.showDockIcon)
        XCTAssertFalse(migrated.showMenuBarIcon)
        XCTAssertEqual(migrated.recentTabLimit, 5)
        XCTAssertEqual(try JSONDecoder().decode(CompanionPreferences.self, from: Data(#"{"recentTabLimit":999}"#.utf8)).recentTabLimit, 12)
    }
    func testPersistenceAndCorruptFallback() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("preferences.json")
        var settings = CompanionPreferences()
        settings.showDockIcon = false
        settings.showMenuBarIcon = true
        settings.launchAtLogin = true
        settings.recentTabLimit = 5
        try settings.save(to: url)
        XCTAssertEqual(CompanionPreferences.load(from: url), settings)
        try Data("broken".utf8).write(to: url)
        XCTAssertEqual(CompanionPreferences.load(from: url), CompanionPreferences())
    }
    func testRolePolicyAndIndependentIcons() {
        var settings = CompanionPreferences()
        XCTAssertEqual(StartupRole.resolve(nativeHost: true, loginItem: true), .nativeHost)
        XCTAssertEqual(StartupRole.resolve(nativeHost: false, loginItem: true), .login)
        XCTAssertEqual(StartupRole.resolve(nativeHost: false, loginItem: false), .interactive)
        XCTAssertFalse(StartupRole.login.showsSettingsOnLaunch)
        XCTAssertFalse(StartupRole.nativeHost.showsSettingsOnLaunch)
        XCTAssertTrue(StartupRole.interactive.showsSettingsOnLaunch)
        for dock in [false, true] {
            for menu in [false, true] {
                settings.showDockIcon = dock
                settings.showMenuBarIcon = menu
                XCTAssertEqual(StartupRole.login.showsDock(preferences: settings), dock)
                XCTAssertEqual(StartupRole.interactive.showsMenu(preferences: settings), menu)
                XCTAssertFalse(StartupRole.nativeHost.showsDock(preferences: settings))
                XCTAssertFalse(StartupRole.nativeHost.showsMenu(preferences: settings))
            }
        }
    }
    func testAtomicInstanceLockAndExitRecovery() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: url) }
        var first: InstanceLock? = InstanceLock()
        let second = InstanceLock()
        XCTAssertTrue(try first!.acquire(at: url))
        XCTAssertFalse(try second.acquire(at: url))
        first = nil
        XCTAssertTrue(try second.acquire(at: url))
    }
    func testReverseRequiresSessionAndSameBaseModifiers() {
        func direction(_ key: Int64, _ mods: UInt64, _ active: Bool, base: UInt64 = 1) -> Int? {
            switchDirection(key: key, primaryKey: 48, graveKey: 50, baseModifiers: base,
                            currentModifiers: mods, shiftMask: 2, inProgress: active)
        }
        XCTAssertEqual(direction(48, 1, false), 1)
        XCTAssertEqual(direction(48, 3, false), -1)
        XCTAssertNil(direction(50, 1, false))
        XCTAssertEqual(direction(50, 1, true), -1)
        XCTAssertNil(direction(50, 5, true))
        XCTAssertEqual(direction(50, 4, true, base: 4), -1)
        XCTAssertNil(direction(48, 0, false, base: 0))
    }

    func testLocalRegistrationNeverChangesUpstreamManifest() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let upstream = NativeHostRegistration(localExtensionID: nil, upstreamID: "store", legacyID: "manual")
        let local = NativeHostRegistration(localExtensionID: String(repeating: "a", count: 32), upstreamID: "store")
        try upstream.update(directory: directory, executable: "/original", enabled: true)
        let upstreamURL = directory.appendingPathComponent("com.tabswitcher.native.json")
        let original = try Data(contentsOf: upstreamURL)
        try local.update(directory: directory, executable: "/local", enabled: false)
        XCTAssertEqual(try Data(contentsOf: upstreamURL), original)
        try local.update(directory: directory, executable: "/local", enabled: true)
        let localURL = directory.appendingPathComponent("com.masonjames.tabswitcher.local.json")
        let manifest = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: localURL)) as? [String: Any])
        XCTAssertEqual(manifest["allowed_origins"] as? [String], ["chrome-extension://" + String(repeating: "a", count: 32) + "/"])
        XCTAssertEqual(manifest["name"] as? String, local.name)
        try local.update(directory: directory, executable: "/local", enabled: false)
        XCTAssertFalse(FileManager.default.fileExists(atPath: localURL.path))
        XCTAssertEqual(try Data(contentsOf: upstreamURL), original)
    }

    func testOriginalLeaderConflictIncludesLeaderWithoutTapAndRecoversAfterExit() {
        XCTAssertTrue(originalLeaderIsAlive(record: "123\n", isAlive: { $0 == 123 }))
        XCTAssertFalse(originalLeaderIsAlive(record: "123", isAlive: { _ in false }))
        for invalid in [nil, "", "bad", "0", "-1", "1"] as [String?] {
            XCTAssertFalse(originalLeaderIsAlive(record: invalid, isAlive: { _ in true }))
        }
    }

    func testHeldSessionDoesNotTransferToAnotherBrowser() {
        XCTAssertTrue(acceptsSessionBrowser(target: nil, frontmost: "Chrome"))
        XCTAssertTrue(acceptsSessionBrowser(target: "Chrome", frontmost: "Chrome"))
        XCTAssertFalse(acceptsSessionBrowser(target: "Chrome", frontmost: "Brave"))
    }

    func testBrowserSaveNotificationReloadsExistingListener() throws {
        let namespace = "com.tabswitcher.test." + UUID().uuidString
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: url) }
        try Data("false".utf8).write(to: url)
        var cached = try String(contentsOf: url, encoding: .utf8)
        let reloaded = expectation(description: "Existing helper reloads saved configuration")
        let center = NotificationCenter() // Exercise reload without requiring the macOS notification daemon.
        let observer = observeBrowserConfigurationChanges(namespace: namespace, center: center) {
            cached = (try? String(contentsOf: url, encoding: .utf8)) ?? "missing"
            reloaded.fulfill()
        }
        defer { center.removeObserver(observer) }
        try Data("true".utf8).write(to: url, options: .atomic)
        center.post(name: browserConfigurationNotification(namespace: namespace), object: nil)
        wait(for: [reloaded], timeout: 3)
        XCTAssertEqual(cached, "true")
    }
}
