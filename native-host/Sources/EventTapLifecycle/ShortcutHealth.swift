import Foundation

public enum ShortcutHealth: String {
    case ready, permissionDenied, listenerUnavailable, originalConflict, secureInput, unknown

    public static func sample(trusted: Bool, listenerEnabled: Bool, originalConflict: Bool,
                              secureInput: Bool) -> ShortcutHealth {
        if originalConflict { return .originalConflict }
        if !trusted { return .permissionDenied }
        if secureInput { return .secureInput }
        return listenerEnabled ? .ready : .listenerUnavailable
    }
}

/// Main-run-loop request broker. No cached health: only the elected owner's fresh
/// response can succeed, while the owner is still alive and before the deadline.
public final class ShortcutHealthProbe {
    private struct Pending {
        let owner: Int32
        let deadline: TimeInterval
        let completion: (ShortcutHealth) -> Void
    }
    private var pending: [String: Pending] = [:]
    private let owner: () -> Int32?
    private let now: () -> TimeInterval
    public init(owner: @escaping () -> Int32?, now: @escaping () -> TimeInterval) {
        self.owner = owner
        self.now = now
    }
    @discardableResult
    public func request(localPID: Int32, localSample: () -> ShortcutHealth?,
                        send: (String) -> Void, completion: @escaping (ShortcutHealth) -> Void) -> String? {
        guard let elected = owner() else { completion(.unknown); return nil }
        if elected == localPID {
            let health = localSample() ?? .unknown
            completion(owner() == elected ? health : .unknown)
            return nil
        }
        let id = UUID().uuidString
        pending[id] = Pending(owner: elected, deadline: now() + 1, completion: completion)
        send(id)
        return id
    }
    public func receive(id: String, owner respondingOwner: Int32, health: ShortcutHealth) {
        guard let request = pending[id], request.owner == respondingOwner else { return }
        pending.removeValue(forKey: id)
        request.completion(now() < request.deadline && owner() == respondingOwner ? health : .unknown)
    }
    public func expire(id: String) {
        pending.removeValue(forKey: id)?.completion(.unknown)
    }
}
