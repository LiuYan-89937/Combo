import ApplicationServices
import Foundation

enum ReplacementSelectionError: Error {
    case unavailable
    case unconfirmed

    var message: String {
        switch self {
        case .unavailable:
            return "[input.replacement_unsupported] The receiver does not expose a verifiable text selection. No replacement text was sent. Do not emulate replacement with press_key followed by type_text."
        case .unconfirmed:
            return "[input.selection_unconfirmed] Select All did not establish the complete selection in the same receiver. No replacement text was sent. Do not retry by inserting text."
        }
    }
}

/// Read evidence only from the identity-checked keyboard receiver, never a tree summary.
struct ReplacementSelection {
    let length: Int
    let range: CFRange

    var coversDocument: Bool { range.location == 0 && range.length == length }

    func selectAll(in element: AXUIElement) throws -> Bool {
        var settable = DarwinBoolean(false)
        guard AXUIElementIsAttributeSettable(element, kAXSelectedTextRangeAttribute as CFString, &settable) == .success,
              settable.boolValue else { return false }
        var fullRange = CFRange(location: 0, length: length)
        guard let value = AXValueCreate(.cfRange, &fullRange),
              AXUIElementSetAttributeValue(element, kAXSelectedTextRangeAttribute as CFString, value) == .success else {
            throw ReplacementSelectionError.unconfirmed
        }
        return true
    }

    static func read(_ element: AXUIElement?) throws -> ReplacementSelection {
        guard let element else { throw ReplacementSelectionError.unavailable }
        var count: CFTypeRef?
        var selection: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXNumberOfCharactersAttribute as CFString, &count) == .success,
              let count = count as? NSNumber, count.intValue >= 0,
              AXUIElementCopyAttributeValue(element, kAXSelectedTextRangeAttribute as CFString, &selection) == .success,
              let selection, CFGetTypeID(selection) == AXValueGetTypeID() else {
            throw ReplacementSelectionError.unavailable
        }
        var range = CFRange()
        guard AXValueGetValue(selection as! AXValue, .cfRange, &range),
              range.location >= 0, range.length >= 0,
              range.location <= count.intValue, range.length <= count.intValue - range.location else {
            throw ReplacementSelectionError.unavailable
        }
        return ReplacementSelection(length: count.intValue, range: range)
    }
}
