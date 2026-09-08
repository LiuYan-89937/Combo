import Foundation

public struct ToolDefinition: @unchecked Sendable {
    public let name: String
    public let description: String
    public let annotations: [String: Any]
    public let inputSchema: [String: Any]

    public init(name: String, description: String, annotations: [String: Any], inputSchema: [String: Any]) {
        self.name = name
        self.description = description
        self.annotations = annotations
        var schema = inputSchema
        if annotations["readOnlyHint"] as? Bool != true {
            var properties = schema["properties"] as? [String: Any] ?? [:]
            properties["observation_id"] = stringProperty(description: "Observation ID from the latest state for this app. Each action refreshes state; never reuse an older ID.")
            schema["properties"] = properties
            schema["required"] = (schema["required"] as? [String] ?? []) + ["observation_id"]
        }
        self.inputSchema = schema
    }

    public var asDictionary: [String: Any] {
        var dictionary: [String: Any] = [
            "name": name,
            "description": description,
            "inputSchema": inputSchema,
        ]

        if !annotations.isEmpty {
            dictionary["annotations"] = annotations
        }

        return dictionary
    }
}

public enum ToolDefinitions {
    public static let all: [ToolDefinition] = [
        ToolDefinition(
            name: "click",
            description: "Click an element by index or pixel coordinates from screenshot. This tool is part of plugin `Computer Use`.",
            annotations: defaultAnnotations(),
            inputSchema: elementOrPointObjectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "element_index": stringProperty(description: "Element index to click"),
                    "x": numberProperty(description: "X coordinate in screenshot pixel coordinates"),
                    "y": numberProperty(description: "Y coordinate in screenshot pixel coordinates"),
                    "click_count": integerProperty(description: "Number of clicks. Defaults to 1"),
                    "mouse_button": stringProperty(
                        description: "Mouse button to click. Defaults to left.",
                        enumValues: ["left", "right", "middle"]
                    ),
                    "click_method": stringProperty(
                        description: "All clicks target the observed window. auto uses an exact window-owned accessibility target or the SkyLight window path. accessibility requires element_index. sky_click explicitly selects the window event path, which supports left single/double clicks. No process-only or global fallback.",
                        enumValues: ClickMethod.allCases.map(\.rawValue)
                    ),
                ],
                required: ["app"]
            )
        ),
        ToolDefinition(
            name: "drag",
            description: "Press and hold the primary mouse button while moving an object, handle, slider, or other explicitly draggable control between screenshot coordinates. Never use drag to scroll a page, list, conversation, document, or other content; use scroll with x/y when no accessibility element is exposed. This tool is part of plugin `Computer Use`.",
            annotations: defaultAnnotations(),
            inputSchema: objectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "from_x": numberProperty(description: "Start X coordinate"),
                    "from_y": numberProperty(description: "Start Y coordinate"),
                    "to_x": numberProperty(description: "End X coordinate"),
                    "to_y": numberProperty(description: "End Y coordinate"),
                ],
                required: ["app", "from_x", "from_y", "to_x", "to_y"]
            )
        ),
        ToolDefinition(
            name: "get_app_state",
            description: "Start an app use session if needed, then get the state of the app's key window and return a screenshot and accessibility tree. This must be called once per assistant turn before interacting with the app. This tool is part of plugin `Computer Use`.",
            annotations: readOnlyAnnotations(),
            inputSchema: objectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "text_limit": textLimitProperty(description: "Maximum text characters to return. Use \"max\" for full text. Defaults to 500."),
                    "max_tree_nodes": positiveIntegerProperty(description: "Maximum accessibility tree nodes to render. Defaults to 1200."),
                    "max_tree_depth": positiveIntegerProperty(description: "Maximum accessibility tree depth to render. Defaults to 64."),
                ],
                required: ["app"]
            )
        ),
        ToolDefinition(
            name: "list_apps",
            description: "List the apps on this computer. Returns the set of apps that are currently running, as well as any that have been used in the last 14 days, including details on usage frequency. This tool is part of plugin `Computer Use`.",
            annotations: readOnlyAnnotations(),
            inputSchema: objectSchema(properties: [:], required: [])
        ),
        ToolDefinition(
            name: "perform_secondary_action",
            description: "Invoke a secondary accessibility action exposed by an element. This tool is part of plugin `Computer Use`.",
            annotations: defaultAnnotations(),
            inputSchema: objectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "element_index": stringProperty(description: "Element identifier"),
                    "action": stringProperty(description: "Secondary accessibility action name"),
                ],
                required: ["app", "element_index", "action"]
            )
        ),
        ToolDefinition(
            name: "press_key",
            description: "Post a key or chord to the bound receiver. The executor uses directed background delivery when confirmed and otherwise obtains and restores a short foreground focus lease. Inspect the returned observation; posting does not prove consumption.",
            annotations: defaultAnnotations(),
            inputSchema: objectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "key": stringProperty(description: "Key or key combination to press"),
                    "element_index": stringProperty(description: "Optional observed editable target; otherwise use the CU-bound control"),
                ],
                required: ["app", "key"]
            )
        ),
        ToolDefinition(
            name: "scroll",
            description: "Scroll page, list, conversation, document, or other content without pressing a mouse button. Target either an observed element_index or x/y inside the intended scroll region when accessibility does not expose one. Never emulate ordinary scrolling with drag. This tool is part of plugin `Computer Use`.",
            annotations: defaultAnnotations(),
            inputSchema: elementOrPointObjectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "direction": stringProperty(description: "Scroll direction: up, down, left, or right"),
                    "element_index": stringProperty(description: "Observed scroll target; provide this or x/y"),
                    "x": numberProperty(description: "X coordinate inside the intended scroll region in screenshot pixels; provide with y instead of element_index"),
                    "y": numberProperty(description: "Y coordinate inside the intended scroll region in screenshot pixels; provide with x instead of element_index"),
                    "pages": numberProperty(description: "Number of pages to scroll. Fractional values are supported. Defaults to 1"),
                ],
                required: ["app", "direction"]
            )
        ),
        ToolDefinition(
            name: "set_value",
            description: "Replace through the bound receiver after verifying a complete selection. The executor uses directed background delivery when confirmed and otherwise obtains and restores a short foreground focus lease. Unsupported or unconfirmed selection stops before text is sent. Never prepare or retry this with Raise, click, press_key plus type_text.",
            annotations: defaultAnnotations(),
            inputSchema: objectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "element_index": stringProperty(description: "Element identifier"),
                    "value": stringProperty(description: "Value to assign"),
                ],
                required: ["app", "value"]
            )
        ),
        ToolDefinition(
            name: "set_input_target",
            description: "Bind a window-owned element_index or x/y in the latest screenshot. An element exposing text selection uses receiver identity; other elements locate an input position by their current frame and establish window scope with one directed click. No editable capability is inferred from role labels. Inspect the result before typing. Rebind after receiver/window changes or pointer actions.",
            annotations: defaultAnnotations(),
            inputSchema: elementOrPointObjectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "element_index": stringProperty(description: "Observed editable element"),
                    "x": numberProperty(description: "Input position x in screenshot pixels; provide with y instead of element_index"),
                    "y": numberProperty(description: "Input position y in screenshot pixels; provide with x instead of element_index"),
                ],
                required: ["app"]
            )
        ),
        ToolDefinition(
            name: "type_text",
            description: "Insert text at the actual selection of the bound receiver. The executor uses directed background delivery when confirmed and otherwise obtains and restores a short foreground focus lease. No AX text writes or clipboard fallback. Never replay unconfirmed input.",
            annotations: defaultAnnotations(),
            inputSchema: objectSchema(
                properties: [
                    "app": stringProperty(description: "App name or bundle identifier"),
                    "text": stringProperty(description: "Literal text to type"),
                    "element_index": stringProperty(description: "Optional editable target in the observed window; otherwise use the session-bound CU target"),
                ],
                required: ["app", "text"]
            )
        ),
    ]
}

private func objectSchema(properties: [String: Any], required: [String]) -> [String: Any] {
    var schema: [String: Any] = [
        "type": "object",
        "properties": properties,
        "additionalProperties": false,
    ]

    if !required.isEmpty {
        schema["required"] = required
    }

    return schema
}

private func elementOrPointObjectSchema(properties: [String: Any], required: [String]) -> [String: Any] {
    var schema = objectSchema(properties: properties, required: required)
    schema["oneOf"] = [
        ["required": ["element_index"]],
        ["required": ["x", "y"]],
    ]
    return schema
}

private func defaultAnnotations() -> [String: Any] {
    [
        "destructiveHint": false,
        "openWorldHint": false,
    ]
}

private func readOnlyAnnotations() -> [String: Any] {
    [
        "destructiveHint": false,
        "idempotentHint": true,
        "openWorldHint": false,
        "readOnlyHint": true,
    ]
}

private func stringProperty(description: String, enumValues: [String]? = nil) -> [String: Any] {
    var property: [String: Any] = [
        "type": "string",
        "description": description,
    ]

    if let enumValues {
        property["enum"] = enumValues
    }

    return property
}

private func integerProperty(description: String) -> [String: Any] {
    [
        "type": "integer",
        "description": description,
    ]
}

private func positiveIntegerProperty(description: String) -> [String: Any] {
    [
        "type": "integer",
        "minimum": 1,
        "description": description,
    ]
}

private func textLimitProperty(description: String) -> [String: Any] {
    [
        "anyOf": [
            [
                "type": "integer",
                "minimum": 1,
            ],
            [
                "type": "string",
                "enum": [SnapshotTextLimit.maxKeyword],
            ],
        ],
        "description": description,
    ]
}

private func numberProperty(description: String) -> [String: Any] {
    [
        "type": "number",
        "description": description,
    ]
}
