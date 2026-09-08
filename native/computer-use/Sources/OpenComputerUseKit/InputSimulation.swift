import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

enum MouseButtonKind: String {
    case left
    case right
    case middle

    var cgButton: CGMouseButton {
        switch self {
        case .left:
            return .left
        case .right:
            return .right
        case .middle:
            return .center
        }
    }

    var downEvent: CGEventType {
        switch self {
        case .left:
            return .leftMouseDown
        case .right:
            return .rightMouseDown
        case .middle:
            return .otherMouseDown
        }
    }

    var upEvent: CGEventType {
        switch self {
        case .left:
            return .leftMouseUp
        case .right:
            return .rightMouseUp
        case .middle:
            return .otherMouseUp
        }
    }
}

enum InputSimulation {
    static let maxKeyboardUnicodeChunkLength = 64

    static func scrollTargeted(at point: CGPoint, direction: String, pages: Double, target: SkyClickTarget) throws {
        guard let source = CGEventSource(stateID: .privateState),
              let event = CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 2, wheel1: wheel1(direction: direction, pages: pages), wheel2: wheel2(direction: direction, pages: pages), wheel3: 0) else {
            throw ComputerUseError.message("Failed to create scroll event.")
        }

        event.location = point
        event.flags = []
        try SkyClickDispatcher.postWindowEvent(event, target: target, pointer: true)
        Thread.sleep(forTimeInterval: 0.1)
    }

    static func dragTargeted(from start: CGPoint, to end: CGPoint, target: SkyClickTarget) throws {
        guard let source = CGEventSource(stateID: .privateState) else {
            throw ComputerUseError.message("Failed to create targeted event source.")
        }

        try postMouseEventToWindow(type: .mouseMoved, source: source, point: start, button: .left, clickState: 1, target: target)
        try postMouseEventToWindow(type: .leftMouseDown, source: source, point: start, button: .left, clickState: 1, target: target)

        for step in 1...10 {
            let progress = CGFloat(step) / 10
            let point = CGPoint(
                x: start.x + ((end.x - start.x) * progress),
                y: start.y + ((end.y - start.y) * progress)
            )
            try postMouseEventToWindow(type: .leftMouseDragged, source: source, point: point, button: .left, clickState: 1, target: target)
        }

        try postMouseEventToWindow(type: .leftMouseUp, source: source, point: end, button: .left, clickState: 1, target: target)
    }

    static func typeText(_ text: String, target: SkyClickTarget, validateTarget: (() throws -> Void)? = nil) throws {
        guard let source = CGEventSource(stateID: .privateState) else {
            throw ComputerUseError.message("Failed to create private input event source")
        }
        for chunk in keyboardUnicodeChunks(for: text) {
            try validateTarget?()
            var mutableChunk = chunk
            guard let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else {
                throw ComputerUseError.message("Failed to create keyboard event.")
            }

            mutableChunk.withUnsafeMutableBufferPointer { buffer in
                guard let baseAddress = buffer.baseAddress else {
                    return
                }

                down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: baseAddress)
                up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: baseAddress)
            }
            down.flags = []
            up.flags = []
            try SkyClickDispatcher.postWindowEvent(down, target: target)
            try SkyClickDispatcher.postWindowEvent(up, target: target)
            Thread.sleep(forTimeInterval: 0.02)
        }
    }

    static func keyboardUnicodeChunks(for text: String, maxUTF16Units: Int = maxKeyboardUnicodeChunkLength) -> [[UniChar]] {
        precondition(maxUTF16Units > 0, "maxUTF16Units must be positive")

        var chunks: [[UniChar]] = []
        var current: [UniChar] = []

        for character in text {
            let units = Array(String(character).utf16)
            if !current.isEmpty, current.count + units.count > maxUTF16Units {
                chunks.append(current)
                current.removeAll(keepingCapacity: true)
            }

            current.append(contentsOf: units)
        }

        if !current.isEmpty {
            chunks.append(current)
        }

        return chunks
    }

    static func pressKey(_ specification: String, target: SkyClickTarget) throws {
        guard let source = CGEventSource(stateID: .privateState) else {
            throw ComputerUseError.message("Failed to create private input event source")
        }
        let parsed = try KeyPressParser.parse(specification)
        var activeFlags: CGEventFlags = []
        var presses: [CGEvent] = []
        var releases: [CGEvent] = []
        for modifier in parsed.modifiers {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: modifier.keyCode, keyDown: true) else {
                throw ComputerUseError.message("Failed to create modifier event")
            }
            activeFlags.insert(modifier.flag)
            event.type = .flagsChanged
            event.flags = activeFlags
            presses.append(event)
        }
        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: parsed.keyCode, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: parsed.keyCode, keyDown: false) else {
            throw ComputerUseError.message("Failed to create key event")
        }
        keyDown.flags = activeFlags
        keyUp.flags = activeFlags
        presses.append(contentsOf: [keyDown, keyUp])
        for modifier in parsed.modifiers.reversed() {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: modifier.keyCode, keyDown: false) else {
                throw ComputerUseError.message("Failed to create modifier release")
            }
            activeFlags.remove(modifier.flag)
            event.type = .flagsChanged
            event.flags = activeFlags
            releases.append(event)
        }
        do {
            for event in presses { try SkyClickDispatcher.postWindowEvent(event, target: target) }
        } catch {
            for event in releases { try? SkyClickDispatcher.postWindowEvent(event, target: target) }
            throw error
        }
        for event in releases { try SkyClickDispatcher.postWindowEvent(event, target: target) }

        Thread.sleep(forTimeInterval: 0.1)
    }

    private static func postMouseEventToWindow(type: CGEventType, source: CGEventSource, point: CGPoint, button: CGMouseButton, clickState: Int, target: SkyClickTarget) throws {
        guard let event = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: point, mouseButton: button) else {
            throw ComputerUseError.message("Failed to create mouse event \(type.rawValue).")
        }

        event.setIntegerValueField(.mouseEventClickState, value: Int64(clickState))
        event.flags = []
        try SkyClickDispatcher.postWindowEvent(event, target: target, pointer: true)
        Thread.sleep(forTimeInterval: 0.03)
    }

    private static func wheel1(direction: String, pages: Double) -> Int32 {
        switch direction {
        case "up":
            return scrollWheelDelta(for: pages)
        case "down":
            return -scrollWheelDelta(for: pages)
        default:
            return 0
        }
    }

    private static func wheel2(direction: String, pages: Double) -> Int32 {
        switch direction {
        case "left":
            return scrollWheelDelta(for: pages)
        case "right":
            return -scrollWheelDelta(for: pages)
        default:
            return 0
        }
    }

    private static func scrollWheelDelta(for pages: Double) -> Int32 {
        let rawValue = (12.0 * pages).rounded(.toNearestOrAwayFromZero)
        let clamped = min(Double(Int32.max), max(1, rawValue))
        return Int32(clamped)
    }
}
