import AppKit
import ApplicationServices
import Foundation

/// Temporarily lends the single interactive application focus to one CU action.
/// The previous application is restored only while CU still owns the lease; a
/// foreground change is treated as user/system intervention.
enum ApplicationFocusLease {
    private static let lock = NSLock()

    static func preservingCurrentApplication<T>(
        targetPID: pid_t,
        diagnostic: (String) -> Void,
        body: () throws -> T
    ) throws -> T {
        guard lock.try() else {
            throw ComputerUseError.message("[input.busy] Another foreground input transaction is running")
        }
        defer { lock.unlock() }

        let previousApp = NSWorkspace.shared.frontmostApplication
        let previousWindow = previousApp.flatMap { focusedWindow(pid: $0.processIdentifier) }
        defer {
            restorePreviousApplication(
                previousApp, window: previousWindow, targetPID: targetPID,
                required: previousApp?.processIdentifier != targetPID, diagnostic: diagnostic
            )
        }
        return try body()
    }

    static func withTarget<T>(
        app: RunningAppDescriptor,
        window: AXUIElement,
        diagnostic: (String) -> Void,
        body: () throws -> T
    ) throws -> T {
        guard lock.try() else {
            throw ComputerUseError.message("[input.busy] Another foreground input transaction is running")
        }
        defer { lock.unlock() }

        let previousApp = NSWorkspace.shared.frontmostApplication
        let previousWindow = previousApp.flatMap { focusedWindow(pid: $0.processIdentifier) }
        let mustRestore = previousApp?.processIdentifier != app.pid

        if mustRestore {
            diagnostic("focus lease acquire target_pid=\(app.pid) previous_pid=\(String(describing: previousApp?.processIdentifier))")
            _ = app.runningApplication.activate(options: [.activateAllWindows])
        }
        _ = AXUIElementPerformAction(window, kAXRaiseAction as CFString)
        setWindowFocus(window)

        defer {
            restorePreviousApplication(
                previousApp, window: previousWindow, targetPID: app.pid,
                required: mustRestore, diagnostic: diagnostic
            )
        }

        guard waitUntil({ NSWorkspace.shared.frontmostApplication?.processIdentifier == app.pid }) else {
            throw ComputerUseError.message("[input.activation_failed] The target application did not become active")
        }

        let result = try body()
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.pid else {
            throw ComputerUseError.message("[input.interrupted_by_user] Foreground ownership changed during input; delivery may be partial")
        }
        return result
    }

    static func requireOwnership(of pid: pid_t) throws {
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid else {
            throw ComputerUseError.message("[input.interrupted_by_user] Foreground ownership changed during input; delivery may be partial")
        }
    }

    private static func focusedWindow(pid: pid_t) -> AXUIElement? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            AXUIElementCreateApplication(pid), kAXFocusedWindowAttribute as CFString, &value
        ) == .success, let value, CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return (value as! AXUIElement)
    }

    private static func restorePreviousApplication(
        _ previousApp: NSRunningApplication?, window: AXUIElement?, targetPID: pid_t,
        required: Bool, diagnostic: (String) -> Void
    ) {
        guard required else { return }
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == targetPID else {
            diagnostic("focus lease restore skipped because foreground ownership changed")
            return
        }
        guard let previousApp, !previousApp.isTerminated else {
            diagnostic("focus lease restore skipped because previous application is unavailable")
            return
        }
        _ = previousApp.activate(options: [.activateAllWindows])
        if let window {
            _ = AXUIElementPerformAction(window, kAXRaiseAction as CFString)
            setWindowFocus(window)
        }
        let restored = waitUntil {
            NSWorkspace.shared.frontmostApplication?.processIdentifier == previousApp.processIdentifier
        }
        diagnostic("focus lease restore previous_pid=\(previousApp.processIdentifier) restored=\(restored)")
    }

    private static func setWindowFocus(_ window: AXUIElement) {
        _ = AXUIElementSetAttributeValue(window, kAXMainAttribute as CFString, kCFBooleanTrue)
        _ = AXUIElementSetAttributeValue(window, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    }

    private static func waitUntil(_ condition: () -> Bool) -> Bool {
        let deadline = ProcessInfo.processInfo.systemUptime + KeyboardReceiverPolicy.timeout
        repeat {
            if condition() { return true }
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            if remaining <= 0 { return false }
            RunLoop.current.run(until: Date(timeIntervalSinceNow: min(KeyboardReceiverPolicy.pollInterval, remaining)))
        } while true
    }
}
