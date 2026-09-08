import ApplicationServices
import Foundation

/// AX exposes keyboard targeting through the application receiver and the control's focus flag.
/// Neither requires the application to be the system foreground application.
struct KeyboardTargetEvidence {
    let receiver: AXUIElement?
    let receiverStatus: AXError
    let controlFocused: Bool?
    let controlStatus: AXError

    init(pid: pid_t, target: AXUIElement) {
        var rawReceiver: CFTypeRef?
        receiverStatus = AXUIElementCopyAttributeValue(
            AXUIElementCreateApplication(pid), kAXFocusedUIElementAttribute as CFString, &rawReceiver
        )
        if receiverStatus == .success, let rawReceiver,
           CFGetTypeID(rawReceiver) == AXUIElementGetTypeID() {
            receiver = (rawReceiver as! AXUIElement)
        } else {
            receiver = nil
        }
        var rawFocused: CFTypeRef?
        controlStatus = AXUIElementCopyAttributeValue(target, kAXFocusedAttribute as CFString, &rawFocused)
        controlFocused = controlStatus == .success ? rawFocused as? Bool : nil
    }

    func resolves(to target: AXUIElement) -> Bool {
        // A control flag can remain true on a proxy with no actual keyboard receiver.
        guard let receiver else { return false }
        return CFEqual(receiver, target)
    }
}
