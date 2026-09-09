import Foundation

public struct ToolResultContentItem: @unchecked Sendable {
    let dictionary: [String: Any]

    public static func text(_ text: String) -> ToolResultContentItem {
        ToolResultContentItem(
            dictionary: [
                "type": "text",
                "text": text,
            ]
        )
    }

    public static func pngImage(_ data: Data) -> ToolResultContentItem {
        ToolResultContentItem(
            dictionary: [
                "type": "image",
                "data": data.base64EncodedString(),
                "mimeType": "image/png",
            ]
        )
    }
}

public struct ToolResultApplication: Sendable {
    public let applicationIdentifier: String
    public let displayName: String
    public let iconDataURL: String?
    public let processID: Int
    public let windowID: Int?
    public let windowTitle: String

    public init(
        applicationIdentifier: String,
        displayName: String,
        iconDataURL: String?,
        processID: Int,
        windowID: Int?,
        windowTitle: String
    ) {
        self.applicationIdentifier = applicationIdentifier
        self.displayName = displayName
        self.iconDataURL = iconDataURL
        self.processID = processID
        self.windowID = windowID
        self.windowTitle = windowTitle
    }

    var asDictionary: [String: Any] {
        var result: [String: Any] = [
            "application_id": applicationIdentifier,
            "display_name": displayName,
            "process_id": processID,
            "window_title": windowTitle,
            "window_state": [:],
        ]
        if let iconDataURL {
            result["icon_data_url"] = iconDataURL
        }
        if let windowID {
            result["window_id"] = windowID
        }
        return result
    }
}

public struct ToolCallResult: @unchecked Sendable {
    public let content: [ToolResultContentItem]
    public let isError: Bool
    public let diagnostics: [String]
    public let inputResult: [String: String]
    public let application: ToolResultApplication?

    public init(
        content: [ToolResultContentItem],
        isError: Bool = false,
        diagnostics: [String] = [],
        inputResult: [String: String] = [:],
        application: ToolResultApplication? = nil
    ) {
        self.content = content
        self.isError = isError
        self.diagnostics = diagnostics
        self.inputResult = inputResult
        self.application = application
    }

    public var primaryText: String? {
        content.first(where: { $0.dictionary["type"] as? String == "text" })?.dictionary["text"] as? String
    }

    public var asDictionary: [String: Any] {
        var result: [String: Any] = [
            "content": content.map(\.dictionary),
            "isError": isError,
            "diagnostics": diagnostics,
            "input_result": inputResult,
        ]
        if let application {
            result["application"] = application.asDictionary
        }
        return result
    }

    public static func text(_ text: String, isError: Bool = false) -> ToolCallResult {
        ToolCallResult(content: [.text(text)], isError: isError)
    }
}
