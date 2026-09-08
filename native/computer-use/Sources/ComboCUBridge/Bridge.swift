import AppKit
import Darwin
import Foundation
import OpenComputerUseKit

@MainActor
private enum Sessions {
    static var dispatchers: [String: ComputerUseToolDispatcher] = [:]

    static func handle(_ request: [String: Any]) throws -> [String: Any] {
        let operation = request["op"] as? String ?? ""
        if operation == "permissions" {
            let current = PermissionDiagnostics.current()
            return ["required": true, "accessibility": current.accessibilityTrusted,
                    "screen_recording": current.screenCaptureGranted]
        }
        if operation == "request_permission" {
            let kind = request["permission"] as? String == "accessibility"
                ? SystemPermissionKind.accessibility : .screenRecording
            if kind == .accessibility { PermissionSupport.requestAccessibilityPrompt() }
            PermissionSupport.openSystemSettings(for: kind)
            return ["ok": true]
        }
        if operation == "tools" {
            return ["tools": ToolDefinitions.all.map(\.asDictionary),
                    "instructions": computerUseServerInstructions]
        }
        guard let session = request["session_id"] as? String else {
            throw BridgeError("missing session_id")
        }
        if operation == "start" {
            dispatchers[session] = ComputerUseToolDispatcher()
            return ["ok": true]
        }
        if operation == "stop" {
            dispatchers.removeValue(forKey: session)
            resetOpenComputerUseVisualCursor()
            return ["ok": true]
        }
        guard operation == "call", let dispatcher = dispatchers[session],
              let name = request["name"] as? String,
              let arguments = request["arguments"] as? [String: Any] else {
            throw BridgeError("invalid native call or inactive session")
        }
        return dispatcher.callToolAsResult(name: name, arguments: arguments).asDictionary
    }
}

private struct BridgeError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

// The Tauri host invokes this on its AppKit main thread. No MCP server is started.
@_cdecl("combo_cu_dispatch")
public func dispatch(_ input: UnsafePointer<CChar>) -> UnsafeMutablePointer<CChar>? {
    // Copy caller-owned memory at the ABI boundary; only Sendable text enters the actor.
    let requestText = String(cString: input)
    let output: String = MainActor.assumeIsolated {
        let response: [String: Any]
        do {
            guard let request = try JSONSerialization.jsonObject(with: Data(requestText.utf8)) as? [String: Any] else {
                throw BridgeError("request must be an object")
            }
            response = try Sessions.handle(request)
        } catch {
            response = ["bridge_error": error.localizedDescription]
        }
        guard let data = try? JSONSerialization.data(withJSONObject: response),
              let text = String(data: data, encoding: .utf8) else { return "{\"bridge_error\":\"response encoding failed\"}" }
        return text
    }
    return strdup(output)
}

@_cdecl("combo_cu_free")
public func releaseResponse(_ response: UnsafeMutablePointer<CChar>?) { free(response) }
