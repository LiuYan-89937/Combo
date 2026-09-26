package main

const serverInstructions = "Computer Use tools operate Windows apps through observations and actions. Begin with get_app_state. Every action consumes the latest observation_id, even on failure; use the next returned observation before acting again. Coordinates are screenshot pixels. Prefer the exact observed element; clicks do not substitute other controls. Use scroll for moving through a page, list, conversation, document, or other content. Target an observed scrollable element when available; otherwise provide x/y inside the intended scroll region and the executor sends a window-targeted wheel message without holding a mouse button. Never use drag to imitate ordinary scrolling. Use drag only when the task explicitly requires holding the primary mouse button to move an object, handle, slider, selection, or other draggable control. set_input_target binds either an editable element_index or explicit x/y in the latest screenshot. The local executor uses directed background messages when the native receiver is available. If an inactive application has no confirmed receiver, it automatically obtains a short foreground focus lease, restores the same bound element or position, sends one input transaction through the system keyboard queue, and restores the previous foreground window. The model must not use Raise, repeated clicks, or repeated text to prepare or retry input. set_value requires a native Edit/RichEdit receiver, selects all through its native protocol, and confirms the full range before sending text or Backspace. Other receivers reject replacement before input; type_text is insertion only. Modifier chords remain unsupported. Foreground ownership changes abort delivery. Posted or interrupted input is never permission to replay. Inspect the fresh observation before further external action."

type toolDefinition struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Annotations map[string]any `json:"annotations,omitempty"`
	InputSchema map[string]any `json:"inputSchema"`
}

func toolDefinitions() []toolDefinition {
	definitions := []toolDefinition{
		{
			Name:        "click",
			Description: "Click an element by index or pixel coordinates from screenshot. This tool is part of plugin `Computer Use`.",
			Annotations: defaultAnnotations(),
			InputSchema: elementOrPointObjectSchema(map[string]any{
				"app":           stringProperty("App name or bundle identifier"),
				"element_index": stringProperty("Element index to click"),
				"x":             numberProperty("X coordinate in screenshot pixel coordinates"),
				"y":             numberProperty("Y coordinate in screenshot pixel coordinates"),
				"click_count":   integerProperty("Number of clicks. Defaults to 1"),
				"mouse_button":  enumStringProperty("Mouse button to click. Defaults to left.", []string{"left", "right", "middle"}),
				"click_method":  enumStringProperty("Click implementation: auto (default), accessibility, or app_post through HWND messages. Accessibility requires element_index.", clickMethodValues),
			}, []string{"app"}),
		},
		{
			Name:        "drag",
			Description: "Press and hold the primary mouse button while moving an object, handle, slider, or other explicitly draggable control between screenshot coordinates. Never use drag to scroll a page, list, conversation, document, or other content; use scroll with x/y when no accessibility element is exposed. This tool is part of plugin `Computer Use`.",
			Annotations: defaultAnnotations(),
			InputSchema: objectSchema(map[string]any{
				"app":    stringProperty("App name or bundle identifier"),
				"from_x": numberProperty("Start X coordinate"),
				"from_y": numberProperty("Start Y coordinate"),
				"to_x":   numberProperty("End X coordinate"),
				"to_y":   numberProperty("End Y coordinate"),
			}, []string{"app", "from_x", "from_y", "to_x", "to_y"}),
		},
		{
			Name:        "get_app_state",
			Description: "Get the state of an already running app's key window and return a screenshot and accessibility tree. This must be called once per assistant turn before interacting with the app. This tool is part of plugin `Computer Use`.",
			Annotations: readOnlyAnnotations(),
			InputSchema: objectSchema(map[string]any{
				"app":            stringProperty("App name or bundle identifier"),
				"text_limit":     textLimitProperty("Maximum text characters to return. Use \"max\" for full text. Defaults to 500."),
				"max_tree_nodes": positiveIntegerProperty("Maximum accessibility tree nodes to render. Defaults to 1200."),
				"max_tree_depth": positiveIntegerProperty("Maximum accessibility tree depth to render. Defaults to 64."),
			}, []string{"app"}),
		},
		{
			Name:        "list_apps",
			Description: "List the apps on this computer. Returns the set of apps that are currently running, as well as any that have been used in the last 14 days, including details on usage frequency. This tool is part of plugin `Computer Use`.",
			Annotations: readOnlyAnnotations(),
			InputSchema: objectSchema(map[string]any{}, nil),
		},
		{
			Name:        "perform_secondary_action",
			Description: "Invoke a secondary accessibility action exposed by an element. This tool is part of plugin `Computer Use`.",
			Annotations: defaultAnnotations(),
			InputSchema: objectSchema(map[string]any{
				"app":           stringProperty("App name or bundle identifier"),
				"element_index": stringProperty("Element identifier"),
				"action":        stringProperty("Secondary accessibility action name"),
			}, []string{"app", "element_index", "action"}),
		},
			{
				Name:        "press_key",
				Description: "Post an unmodified key to the bound receiver. The executor uses directed background delivery when confirmed and otherwise obtains and restores a short foreground focus lease. Modifier chords are unsupported. Delivery does not prove consumption; observe the returned state.",
			Annotations: defaultAnnotations(),
			InputSchema: objectSchema(map[string]any{
				"app": stringProperty("App name or bundle identifier"),
				"key": stringProperty("Unmodified key to press"),
                "element_index": stringProperty("Optional observed editable target; otherwise use the CU-bound control"),
			}, []string{"app", "key"}),
		},
		{
			Name:        "scroll",
			Description: "Scroll page, list, conversation, document, or other content without pressing a mouse button. Target either an observed element_index or x/y inside the intended scroll region when accessibility does not expose one. Never emulate ordinary scrolling with drag. This tool is part of plugin `Computer Use`.",
			Annotations: defaultAnnotations(),
			InputSchema: elementOrPointObjectSchema(map[string]any{
				"app":           stringProperty("App name or bundle identifier"),
				"direction":     stringProperty("Scroll direction: up, down, left, or right"),
				"element_index": stringProperty("Observed scroll target; provide this or x/y"),
				"x":             numberProperty("X coordinate inside the intended scroll region in screenshot pixels; provide with y instead of element_index"),
				"y":             numberProperty("Y coordinate inside the intended scroll region in screenshot pixels; provide with x instead of element_index"),
				"pages":         numberProperty("Number of pages to scroll. Fractional values are supported. Defaults to 1"),
			}, []string{"app", "direction"}),
		},
		{
			Name:        "set_value",
			Description: "Replace through a native Edit/RichEdit receiver after confirming the complete selection. The executor chooses directed background delivery or a short foreground lease and restores the previous window. Never prepare or retry with Raise, click, or type_text.",
			Annotations: defaultAnnotations(),
			InputSchema: objectSchema(map[string]any{
				"app":           stringProperty("App name or bundle identifier"),
				"element_index": stringProperty("Element identifier"),
				"value":         stringProperty("Value to assign"),
			}, []string{"app", "value"}),
		},
        {
            Name: "set_input_target",
            Description: "Bind either element_index or x/y in the latest screenshot. The executor retains this identity and automatically reestablishes it inside a short foreground lease when background focus is unavailable. Choose exactly one targeting form.",
            Annotations: defaultAnnotations(),
            InputSchema: elementOrPointObjectSchema(map[string]any{
                "app": stringProperty("Application"),
                "element_index": stringProperty("Observed editable target"),
                "x": numberProperty("Input position x in screenshot pixels; provide with y"),
                "y": numberProperty("Input position y in screenshot pixels; provide with x"),
            }, []string{"app"}),
        },
		{
			Name:        "type_text",
			Description: "Insert text at the bound receiver's current selection. The executor chooses directed background delivery or a short foreground lease and restores the previous window. This preserves existing text; never use it to retry a replacement.",
			Annotations: defaultAnnotations(),
			InputSchema: objectSchema(map[string]any{
				"app":  stringProperty("App name or bundle identifier"),
				"text": stringProperty("Literal text to type"),
					"element_index": stringProperty("Optional editable target; otherwise use the CU-bound target"),
			}, []string{"app", "text"}),
		},
	}
    for i := range definitions {
        d := &definitions[i]
        if d.Annotations["readOnlyHint"] == true { continue }
        props := d.InputSchema["properties"].(map[string]any)
        props["observation_id"] = stringProperty("Observation ID from the latest state of this app. Each action refreshes state; never reuse an older ID.")
        d.InputSchema["required"] = append(d.InputSchema["required"].([]string), "observation_id")

    }
    return definitions

}

func objectSchema(properties map[string]any, required []string) map[string]any {
	schema := map[string]any{
		"type":                 "object",
		"properties":           properties,
		"additionalProperties": false,
	}
	if len(required) > 0 {
		schema["required"] = required
	}
	return schema
}

func elementOrPointObjectSchema(properties map[string]any, required []string) map[string]any {
	schema := objectSchema(properties, required)
	schema["oneOf"] = []any{
		map[string]any{"required": []string{"element_index"}},
		map[string]any{"required": []string{"x", "y"}},
	}
	return schema
}

func defaultAnnotations() map[string]any {
	return map[string]any{"destructiveHint": false, "openWorldHint": false}
}

func readOnlyAnnotations() map[string]any {
	return map[string]any{"destructiveHint": false, "idempotentHint": true, "openWorldHint": false, "readOnlyHint": true}
}

func stringProperty(description string) map[string]any {
	return map[string]any{"type": "string", "description": description}
}

func enumStringProperty(description string, values []string) map[string]any {
	property := stringProperty(description)
	property["enum"] = values
	return property
}

func numberProperty(description string) map[string]any {
	return map[string]any{"type": "number", "description": description}
}

func integerProperty(description string) map[string]any {
	return map[string]any{"type": "integer", "description": description}
}

func positiveIntegerProperty(description string) map[string]any {
	return map[string]any{"type": "integer", "minimum": 1, "description": description}
}

func textLimitProperty(description string) map[string]any {
	return map[string]any{
		"anyOf": []any{
			map[string]any{"type": "integer", "minimum": 1},
			map[string]any{"type": "string", "enum": []string{"max"}},
		},
		"description": description,
	}
}
