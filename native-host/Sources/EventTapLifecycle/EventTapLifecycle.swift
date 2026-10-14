/// Retains a keyboard listener and retries creation or enabling after a failure.
/// Used on the main run loop; the injected operations keep recovery testable without
/// changing the user's macOS Accessibility permissions.
public final class EventTapLifecycle<Tap> {
    private var tap: Tap?
    private let create: () -> Tap?
    private let checkEnabled: (Tap) -> Bool
    private let enable: (Tap) -> Void

    public init(create: @escaping () -> Tap?, isEnabled: @escaping (Tap) -> Bool,
                enable: @escaping (Tap) -> Void) {
        self.create = create
        self.checkEnabled = isEnabled
        self.enable = enable
    }

    public var isEnabled: Bool {
        guard let tap else { return false }
        return checkEnabled(tap)
    }

    @discardableResult
    public func ensureEnabled() -> Bool {
        if tap == nil {
            tap = create()
        }
        guard let tap else { return false }
        if !checkEnabled(tap) {
            enable(tap)
        }
        return checkEnabled(tap)
    }
}
