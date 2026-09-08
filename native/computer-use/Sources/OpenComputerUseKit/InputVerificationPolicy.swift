import Foundation

struct InputVerificationPolicy {
    // Shared contract defaults with the Windows worker; milliseconds in the tool schema.
    static let defaultTimeout: TimeInterval = 1
    static let defaultPollInterval: TimeInterval = 0.05
    let timeout: TimeInterval
    let pollInterval: TimeInterval

    init(timeout: TimeInterval?) {
        self.timeout = timeout ?? Self.defaultTimeout
        self.pollInterval = Self.defaultPollInterval
    }
}
