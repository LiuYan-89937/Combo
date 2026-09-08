import ApplicationServices
import Foundation

enum KeyboardDeliveryCapability: String {
    case directedBackground = "directed_background"
    case foregroundLease = "foreground_lease"

    var requiresForegroundLease: Bool { self == .foregroundLease }
}

/// Session-owned receiver identity. Text and selection belong to the target application.
final class InputTarget {
    enum Receiver {
        case element(AXUIElement)
        case windowPoint(CGPoint)
    }
    let receiver: Receiver
    let window: AXUIElement
    let windowID: CGWindowID?
    let windowBounds: CGRect?
    let anchorElement: AXUIElement?
    let anchorFrame: CGRect?

    var element: AXUIElement? {
        if case .element(let element) = receiver { return element }
        return nil
    }

    var scope: String { element == nil ? "window" : "element" }

    var boundPoint: CGPoint? {
        if case .windowPoint(let point) = receiver { return point }
        return nil
    }

    init(receiver: Receiver, window: AXUIElement, windowID: CGWindowID?, windowBounds: CGRect?,
         anchorElement: AXUIElement? = nil, anchorFrame: CGRect? = nil) {
        self.receiver = receiver
        self.window = window
        self.windowID = windowID
        self.windowBounds = windowBounds
        self.anchorElement = anchorElement
        self.anchorFrame = anchorFrame
    }
}
