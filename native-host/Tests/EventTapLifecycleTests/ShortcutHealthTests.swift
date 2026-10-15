import XCTest
import EventTapLifecycle

final class ShortcutHealthTests: XCTestCase {
    func testEffectivePermissionAndRecovery() {
        XCTAssertEqual(ShortcutHealth.sample(trusted: false, listenerEnabled: true, originalConflict: false, secureInput: false), .permissionDenied)
        XCTAssertEqual(ShortcutHealth.sample(trusted: true, listenerEnabled: false, originalConflict: false, secureInput: false), .listenerUnavailable)
        XCTAssertEqual(ShortcutHealth.sample(trusted: true, listenerEnabled: true, originalConflict: false, secureInput: false), .ready)
        XCTAssertEqual(ShortcutHealth.sample(trusted: true, listenerEnabled: true, originalConflict: true, secureInput: false), .originalConflict)
        XCTAssertEqual(ShortcutHealth.sample(trusted: true, listenerEnabled: true, originalConflict: false, secureInput: true), .secureInput)
    }

    func testLeaderSamplesEveryRequestIncludingRevocation() {
        let probe = ShortcutHealthProbe(owner: { 1 }, now: { 0 })
        var trusted = true
        var results: [ShortcutHealth] = []
        for _ in 0..<2 {
            probe.request(localPID: 1, localSample: {
                .sample(trusted: trusted, listenerEnabled: true, originalConflict: false, secureInput: false)
            }, send: { _ in XCTFail("Local owner needs no IPC") }, completion: { results.append($0) })
            trusted = false
        }
        XCTAssertEqual(results, [.ready, .permissionDenied])
    }

    func testNonleaderUsesOwnerRatherThanItsMissingTap() {
        let probe = ShortcutHealthProbe(owner: { 2 }, now: { 0 })
        var results: [ShortcutHealth] = []
        let id = probe.request(localPID: 1, localSample: { XCTFail("Must not sample nonleader"); return .listenerUnavailable }, send: { _ in }, completion: { results.append($0) })!
        probe.receive(id: id, owner: 3, health: .ready)
        XCTAssertTrue(results.isEmpty)
        probe.receive(id: id, owner: 2, health: .permissionDenied)
        probe.expire(id: id)
        XCTAssertEqual(results, [.permissionDenied])
        let retry = probe.request(localPID: 1, localSample: { nil }, send: { _ in }, completion: { results.append($0) })!
        probe.receive(id: id, owner: 2, health: .ready) // Stale response cannot resolve retry.
        XCTAssertEqual(results.count, 1)
        probe.receive(id: retry, owner: 2, health: .ready)
        XCTAssertEqual(results, [.permissionDenied, .ready])
    }

    func testDeathHandoffAndLateResponsesFailClosed() {
        for nextOwner: Int32? in [nil, 3, 2] {
            var owner: Int32? = 2
            var now: Double = 0
            let probe = ShortcutHealthProbe(owner: { owner }, now: { now })
            var result: ShortcutHealth?
            let id = probe.request(localPID: 1, localSample: { nil }, send: { _ in }, completion: { result = $0 })!
            owner = nextOwner
            if nextOwner == 2 { now = 1.1 }
            probe.receive(id: id, owner: 2, health: .ready)
            XCTAssertEqual(result, .unknown)
        }
    }

    func testMissingOwnerMissingResponseAndOverlappingRequests() {
        var owner: Int32?
        let probe = ShortcutHealthProbe(owner: { owner }, now: { 0 })
        var results: [ShortcutHealth] = []
        probe.request(localPID: 1, localSample: { nil }, send: { _ in XCTFail() }, completion: { results.append($0) })
        owner = 2
        let first = probe.request(localPID: 1, localSample: { nil }, send: { _ in }, completion: { results.append($0) })!
        let second = probe.request(localPID: 1, localSample: { nil }, send: { _ in }, completion: { results.append($0) })!
        probe.expire(id: first)
        probe.receive(id: first, owner: 2, health: .ready)
        probe.receive(id: second, owner: 2, health: .ready)
        XCTAssertEqual(results, [.unknown, .unknown, .ready])
    }
}
