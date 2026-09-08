import ApplicationServices
import Foundation

/// CU-owned editing state. Neither the system focus nor a human caret selects this target.
final class InputTarget {
    let element: AXUIElement
    let window: AXUIElement
    let windowID: CGWindowID?
    var value: String
    var selection: CFRange?

    init(element: AXUIElement, window: AXUIElement, windowID: CGWindowID?, value: String, selection: CFRange?) {
        self.element = element
        self.window = window
        self.windowID = windowID
        self.value = value
        self.selection = selection
    }
}
