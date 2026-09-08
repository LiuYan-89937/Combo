import ApplicationServices
import Foundation

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

    var element: AXUIElement? {
        if case .element(let element) = receiver { return element }
        return nil
    }

    var scope: String { element == nil ? "window" : "element" }

    init(receiver: Receiver, window: AXUIElement, windowID: CGWindowID?, windowBounds: CGRect?) {
        self.receiver = receiver
        self.window = window
        self.windowID = windowID
        self.windowBounds = windowBounds
    }
}
