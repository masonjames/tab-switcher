import XCTest
import EventTapLifecycle

final class EventTapLifecycleTests: XCTestCase {
    private final class Tap {
        var enabled = false
    }

    func testRecoversAfterPermissionIsGrantedWithoutRestarting() {
        var allowed = false
        var attempts = 0
        let tap = Tap()
        let listener = EventTapLifecycle<Tap>(create: {
            attempts += 1
            return allowed ? tap : nil
        }, isEnabled: { $0.enabled }, enable: { $0.enabled = true })

        XCTAssertFalse(listener.ensureEnabled())
        XCTAssertFalse(listener.isEnabled)
        XCTAssertFalse(listener.ensureEnabled())
        allowed = true
        XCTAssertTrue(listener.ensureEnabled())
        XCTAssertEqual(attempts, 3)
        XCTAssertTrue(listener.isEnabled)
        XCTAssertTrue(listener.ensureEnabled())
        XCTAssertEqual(attempts, 3, "Healthy listeners must not be installed twice")
    }

    func testReenablesExistingListenerAfterTimeout() {
        var creations = 0
        var enables = 0
        let tap = Tap()
        let listener = EventTapLifecycle<Tap>(create: {
            creations += 1
            return tap
        }, isEnabled: { $0.enabled }, enable: {
            enables += 1
            $0.enabled = true
        })

        XCTAssertTrue(listener.ensureEnabled())
        tap.enabled = false // macOS disables the event tap on a callback timeout.
        XCTAssertFalse(listener.isEnabled)
        XCTAssertTrue(listener.ensureEnabled())
        XCTAssertEqual(creations, 1)
        XCTAssertEqual(enables, 2)
    }

    func testFailedEnableRemainsUnhealthyAndCanRetry() {
        let tap = Tap()
        var canEnable = false
        let listener = EventTapLifecycle<Tap>(create: { tap },
            isEnabled: { $0.enabled }, enable: { $0.enabled = canEnable })

        XCTAssertFalse(listener.ensureEnabled())
        canEnable = true
        XCTAssertTrue(listener.ensureEnabled())
    }

    func testRetainsListenerForLaterRecovery() {
        weak var retainedTap: Tap?
        let listener = EventTapLifecycle<Tap>(create: {
            let tap = Tap()
            retainedTap = tap
            return tap
        }, isEnabled: { $0.enabled }, enable: { $0.enabled = true })

        XCTAssertTrue(listener.ensureEnabled())
        XCTAssertNotNil(retainedTap)
        retainedTap?.enabled = false
        XCTAssertTrue(listener.ensureEnabled())
    }
}
