package main

import (
    "bytes"
    "encoding/base64"
    "fmt"
    "image/png"
    "math"
    "reflect"
    "strconv"
    "strings"
)

type contentItem struct {
	Type     string `json:"type"`
	Text     string `json:"text,omitempty"`
	Data     string `json:"data,omitempty"`
	MimeType string `json:"mimeType,omitempty"`
}

type toolCallResult struct {
	Diagnostics []string               `json:"diagnostics,omitempty"`
	InputResult map[string]string       `json:"input_result,omitempty"`
	Content     []contentItem           `json:"content"`
	IsError     bool                    `json:"isError"`
	Application *toolResultApplication `json:"application,omitempty"`
}

func textResult(text string, isError bool) toolCallResult {
	return toolCallResult{Content: []contentItem{{Type: "text", Text: text}}, IsError: isError}
}

type appDescriptor struct {
	Name             string `json:"name"`
	BundleIdentifier string `json:"bundleIdentifier,omitempty"`
	IconDataURL      string `json:"iconDataUrl,omitempty"`
	PID              int    `json:"pid"`
}

type toolResultApplication struct {
	ApplicationIdentifier string         `json:"application_id"`
	DisplayName           string         `json:"display_name"`
	IconDataURL           string         `json:"icon_data_url,omitempty"`
	ProcessID             int            `json:"process_id"`
	WindowID              int64          `json:"window_id,omitempty"`
	WindowTitle           string         `json:"window_title"`
	WindowState           map[string]any `json:"window_state"`
}

type frame struct {
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
}

func (f frame) renderedLocalFrame() string {
	return fmt.Sprintf("{{x: %.0f, y: %.0f, width: %.0f, height: %.0f}}", f.X, f.Y, f.Width, f.Height)
}

type elementRecord struct {
	Index                int      `json:"index"`
	RuntimeID            []int    `json:"runtimeId,omitempty"`
	AutomationID         string   `json:"automationId,omitempty"`
	Name                 string   `json:"name,omitempty"`
	ControlType          string   `json:"controlType,omitempty"`
	LocalizedControlType string   `json:"localizedControlType,omitempty"`
	ClassName            string   `json:"className,omitempty"`
	Value                string   `json:"value,omitempty"`
	NativeWindowHandle   int64    `json:"nativeWindowHandle,omitempty"`
	Frame                *frame   `json:"frame,omitempty"`
	Actions              []string `json:"actions,omitempty"`
}

type appSnapshot struct {
    ObservationID string `json:"observationID"`
    WindowHandle int64 `json:"windowHandle"`
	App                 appDescriptor   `json:"app"`
	WindowTitle         string          `json:"windowTitle,omitempty"`
	WindowBounds        *frame          `json:"windowBounds,omitempty"`
	ScreenshotPNGBase64 string          `json:"screenshotPngBase64,omitempty"`
	TreeLines           []string        `json:"treeLines,omitempty"`
	FocusedSummary      string          `json:"focusedSummary,omitempty"`
	SelectedText        string          `json:"selectedText,omitempty"`
	Elements            []elementRecord `json:"elements,omitempty"`
}

func (s *appSnapshot) renderedText() string {
	if s == nil {
		return ""
	}
	appRef := s.App.BundleIdentifier
	if appRef == "" {
		appRef = s.App.Name
	}
	title := s.WindowTitle
	if strings.TrimSpace(title) == "" {
		title = s.App.Name
	}

	lines := []string{
		fmt.Sprintf("App=%s (pid %d)", appRef, s.App.PID),
        fmt.Sprintf("Observation: %s. Use this observation_id for the next action.", s.ObservationID),
		fmt.Sprintf("Window: %q, App: %s.", title, s.App.Name),
	}
    if width, height, err := s.screenshotSize(); err == nil {
        lines = append(lines, fmt.Sprintf("Screenshot: %dx%d pixels. Origin is top-left; x increases right, y increases down. Valid coordinates: 0 <= x < %d, 0 <= y < %d. Use screenshot pixels, not desktop or window dimensions.", width, height, width, height))
    } else {
        lines = append(lines, "Screenshot unavailable. Do not infer coordinates from an older image; refresh the observation or use an exposed element.")
    }
	lines = append(lines, s.TreeLines...)
	if strings.TrimSpace(s.SelectedText) != "" {
		lines = append(lines, "", fmt.Sprintf("Selected text: [%s]", s.SelectedText))
	} else if strings.TrimSpace(s.FocusedSummary) != "" {
		lines = append(lines, "", fmt.Sprintf("The focused UI element is %s.", s.FocusedSummary))
	}
	return strings.Join(lines, "\n")
}

func (s *appSnapshot) screenshotSize() (int, int, error) {
    data, err := base64.StdEncoding.DecodeString(s.ScreenshotPNGBase64)
    if err != nil { return 0, 0, err }
    config, err := png.DecodeConfig(bytes.NewReader(data))
    if err != nil { return 0, 0, err }
    return config.Width, config.Height, nil
}

func (s *appSnapshot) validateScreenshotPoint(x, y *float64) error {
    width, height, err := s.screenshotSize()
    if err != nil { return fmt.Errorf("[observation.unavailable] Coordinate actions require the current screenshot") }
    if x == nil || y == nil { return fmt.Errorf("[coordinates.out_of_bounds] Both x and y are required") }
    if math.IsNaN(*x) || math.IsInf(*x, 0) || math.IsNaN(*y) || math.IsInf(*y, 0) || *x < 0 || *y < 0 || *x >= float64(width) || *y >= float64(height) {
        return fmt.Errorf("[coordinates.out_of_bounds] Received (%g, %g); screenshot %dx%d, valid range 0 <= x < %d, 0 <= y < %d", *x, *y, width, height, width, height)
    }
    return nil
}

func (s *appSnapshot) result() toolCallResult {
	result := toolCallResult{
		Content:     []contentItem{{Type: "text", Text: s.renderedText()}},
		Application: s.applicationResult(),
	}
	if s != nil && s.ScreenshotPNGBase64 != "" {
		result.Content = append(result.Content, contentItem{
			Type:     "image",
			Data:     s.ScreenshotPNGBase64,
			MimeType: "image/png",
		})
	}
	return result
}

func (s *appSnapshot) applicationResult() *toolResultApplication {
	if s == nil {
		return nil
	}
	identifier := s.App.BundleIdentifier
	if identifier == "" {
		identifier = s.App.Name
	}
	return &toolResultApplication{
		ApplicationIdentifier: identifier,
		DisplayName:           s.App.Name,
		IconDataURL:           s.App.IconDataURL,
		ProcessID:             s.App.PID,
		WindowID:              s.WindowHandle,
		WindowTitle:           s.WindowTitle,
		WindowState:           map[string]any{},
	}
}

type inputTarget struct {
    Scope string `json:"scope"`
    KeyboardHandle int64 `json:"keyboard_handle,omitempty"`
    Bounds *frame `json:"bounds,omitempty"`
    PID int `json:"pid"`
    WindowHandle int64 `json:"window_handle"`
    Element *elementRecord `json:"element"`
    PointX int `json:"point_x,omitempty"`
    PointY int `json:"point_y,omitempty"`
}

type psRequest struct {
    InputTarget *inputTarget `json:"input_target,omitempty"`
    ObservationID string `json:"observation_id,omitempty"`
    WindowHandle int64 `json:"window_handle,omitempty"`
    TargetPID int `json:"target_pid,omitempty"`
	Tool         string         `json:"tool"`
	App          string         `json:"app,omitempty"`
	Element      *elementRecord `json:"element,omitempty"`
	X            *float64       `json:"x,omitempty"`
	Y            *float64       `json:"y,omitempty"`
	FromX        *float64       `json:"from_x,omitempty"`
	FromY        *float64       `json:"from_y,omitempty"`
	ToX          *float64       `json:"to_x,omitempty"`
	ToY          *float64       `json:"to_y,omitempty"`
	ClickCount   int            `json:"click_count,omitempty"`
	MouseButton  string         `json:"mouse_button,omitempty"`
	ClickMethod  string         `json:"click_method,omitempty"`
	Action       string         `json:"action,omitempty"`
	Direction    string         `json:"direction,omitempty"`
	Pages        float64        `json:"pages,omitempty"`
	Text         string         `json:"text,omitempty"`
	Key          string         `json:"key,omitempty"`
	Value        string         `json:"value"`
	WindowBounds *frame         `json:"windowBounds,omitempty"`
	TextLimit    any            `json:"text_limit,omitempty"`
	MaxTreeNodes int            `json:"max_tree_nodes,omitempty"`
	MaxTreeDepth int            `json:"max_tree_depth,omitempty"`
}

type textLimit struct {
	max   bool
	count int
}

func (limit textLimit) runtimeValue() any {
	if limit.max {
		return "max"
	}
	return limit.count
}

type psResponse struct {
    InputTarget *inputTarget `json:"input_target,omitempty"`
    Diagnostics []string `json:"diagnostics,omitempty"`
    InputResult map[string]string `json:"input_result,omitempty"`
	OK       bool         `json:"ok"`
	Text     string       `json:"text,omitempty"`
	Error    string       `json:"error,omitempty"`
	Snapshot *appSnapshot `json:"snapshot,omitempty"`
}

type service struct {
	snapshots map[string]*appSnapshot
    inputTargets map[int]*inputTarget
}

func newService() *service {
	return &service{snapshots: map[string]*appSnapshot{}, inputTargets: map[int]*inputTarget{}}
}

func (s *service) callTool(name string, args map[string]any) toolCallResult {
    for _, definition := range toolDefinitions() {
        if definition.Name != name || definition.Annotations["readOnlyHint"] == true { continue }
        snapshot := s.currentSnapshot(requiredString(args, "app"))
        if snapshot == nil || requiredString(args, "observation_id") == "" || snapshot.ObservationID != requiredString(args, "observation_id") {
            return textResult("[observation.stale] Run get_app_state and use the latest observation_id before acting.", true)
        }
        defer s.retireObservation(snapshot.ObservationID)
        if name == "click" || name == "scroll" || name == "drag" || name == "perform_secondary_action" {
            if saved := s.inputTargets[snapshot.App.PID]; saved != nil && saved.Scope == "window" {
                delete(s.inputTargets, snapshot.App.PID)
            }
        }
        break
    }
    switch name {
	case "list_apps":
		return s.listApps()
	case "get_app_state":
		maxTreeNodes, err := optionalPositiveInt(args, "max_tree_nodes")
		if err != nil {
			return textResult(err.Error(), true)
		}
		maxTreeDepth, err := optionalPositiveInt(args, "max_tree_depth")
		if err != nil {
			return textResult(err.Error(), true)
		}
		textLimit, err := optionalTextLimit(args, "text_limit")
		if err != nil {
			return textResult(err.Error(), true)
		}
		return s.getAppState(requiredString(args, "app"), textLimit, maxTreeNodes, maxTreeDepth)
	case "click":
		clickMethod, err := parseClickMethod(optionalString(args, "click_method"))
		if err != nil {
			return textResult(err.Error(), true)
		}
		return s.click(
			requiredString(args, "app"),
			optionalElementIndex(args),
			optionalFloat(args, "x"),
			optionalFloat(args, "y"),
			intValue(optionalFloat(args, "click_count"), 1),
			defaultString(optionalString(args, "mouse_button"), "left"),
			clickMethod,
		)
	case "perform_secondary_action":
		return s.performSecondaryAction(
			requiredString(args, "app"),
			requiredElementIndex(args),
			requiredString(args, "action"),
		)
	case "scroll":
		return s.scroll(
			requiredString(args, "app"),
			requiredString(args, "direction"),
			optionalElementIndex(args),
			optionalFloat(args, "x"),
			optionalFloat(args, "y"),
			floatValue(optionalFloat(args, "pages"), 1),
		)
	case "drag":
		return s.drag(
			requiredString(args, "app"),
			requiredFloat(args, "from_x"),
			requiredFloat(args, "from_y"),
			requiredFloat(args, "to_x"),
			requiredFloat(args, "to_y"),
		)
	case "set_input_target":
        app := requiredString(args, "app")
        snapshot := s.currentSnapshot(app)
        if snapshot == nil { return textResult("[observation.required] Run get_app_state first", true) }
        index := optionalElementIndex(args)
        x, y := optionalFloat(args, "x"), optionalFloat(args, "y")
        if index != "" {
            if x != nil || y != nil { return textResult("Choose element_index or x/y, not both", true) }
            record, err := lookupElement(snapshot, index)
            if err != nil { return textResult(err.Error(), true) }
            return s.actionResult(app, psRequest{Tool: "set_input_target", App: app, Element: record})
        }
        if x == nil || y == nil { return textResult("Provide element_index or both screenshot coordinates x and y", true) }
        return s.actionResult(app, psRequest{Tool: "set_input_target", App: app, X: x, Y: y})
    case "type_text":
		return s.typeText(requiredString(args, "app"), optionalString(args, "text"), requiredElementIndex(args))
	case "press_key":
		return s.pressKey(requiredString(args, "app"), requiredString(args, "key"), optionalElementIndex(args))
	case "set_value":
		return s.setValue(requiredString(args, "app"), requiredElementIndex(args), optionalString(args, "value"))
	default:
		return textResult(fmt.Sprintf("unsupportedTool(%q)", name), true)
	}
}

func (s *service) listApps() toolCallResult {
	response, err := runPowerShell(psRequest{Tool: "list_apps"})
	if err != nil {
		return textResult(err.Error(), true)
	}
	if !response.OK {
		return textResult(response.Error, true)
	}
	if strings.TrimSpace(response.Text) == "" {
		response.Text = "No running top-level apps are visible to this Windows runtime."
	}
	return textResult(response.Text, false)
}

func (s *service) getAppState(app string, textLimit *textLimit, maxTreeNodes, maxTreeDepth *int) toolCallResult {
	if app == "" {
		return textResult("Missing required argument: app", true)
	}
	request := psRequest{Tool: "get_app_state", App: app}
	if textLimit != nil {
		request.TextLimit = textLimit.runtimeValue()
	}
	if maxTreeNodes != nil {
		request.MaxTreeNodes = *maxTreeNodes
	}
	if maxTreeDepth != nil {
		request.MaxTreeDepth = *maxTreeDepth
	}
	snapshot, result := s.refreshSnapshot(app, request)
	if result.IsError {
		return result
	}
	return snapshot.result()
}

func (s *service) click(app, elementIndex string, x, y *float64, clickCount int, mouseButton, clickMethod string) toolCallResult {
	if app == "" {
		return textResult("Missing required argument: app", true)
	}
	if elementIndex == "" && (x == nil || y == nil) {
		return textResult("click requires either element_index or x/y", true)
	}
	if clickMethod == "accessibility" && elementIndex == "" {
		return textResult("click_method 'accessibility' requires element_index", true)
	}
	if clickMethod == "global" {
		return textResult("click_method 'global' is not supported on Windows", true)
	}
	if clickMethod == "sky_click" {
		return textResult("click_method 'sky_click' is not supported on Windows", true)
	}
	snapshot := s.currentSnapshot(app)
	if snapshot == nil {
		return textResult("No app state is available for "+app+". Run get_app_state before action tools.", true)
	}
	request := psRequest{
		Tool:         "click",
		App:          app,
		X:            x,
		Y:            y,
		ClickCount:   clickCount,
		MouseButton:  mouseButton,
		ClickMethod:  clickMethod,
		WindowBounds: snapshot.WindowBounds,
	}
	if elementIndex != "" {
		record, err := lookupElement(snapshot, elementIndex)
		if err != nil {
			return textResult(err.Error(), true)
		}
		request.Element = record
	}
	return s.actionResult(app, request)
}

func (s *service) performSecondaryAction(app, elementIndex, action string) toolCallResult {
	if app == "" {
		return textResult("Missing required argument: app", true)
	}
	if elementIndex == "" {
		return textResult("Missing required argument: element_index", true)
	}
	if action == "" {
		return textResult("Missing required argument: action", true)
	}
	snapshot := s.currentSnapshot(app)
	if snapshot == nil {
		return textResult("No app state is available for "+app+". Run get_app_state before action tools.", true)
	}
	record, err := lookupElement(snapshot, elementIndex)
	if err != nil {
		return textResult(err.Error(), true)
	}
	return s.actionResult(app, psRequest{Tool: "perform_secondary_action", App: app, Element: record, Action: action})
}

func (s *service) scroll(app, direction, elementIndex string, x, y *float64, pages float64) toolCallResult {
	if app == "" {
		return textResult("Missing required argument: app", true)
	}
	normalized := strings.ToLower(direction)
	if normalized != "up" && normalized != "down" && normalized != "left" && normalized != "right" {
		return textResult("Invalid scroll direction: "+direction, true)
	}
	if math.IsNaN(pages) || math.IsInf(pages, 0) || pages <= 0 {
		return textResult("pages must be > 0", true)
	}
	snapshot := s.currentSnapshot(app)
	if snapshot == nil {
		return textResult("No app state is available for "+app+". Run get_app_state before action tools.", true)
	}
	hasElement := elementIndex != ""
	hasPoint := x != nil || y != nil
	if hasElement == hasPoint || (hasPoint && (x == nil || y == nil)) {
		return textResult("scroll requires exactly one target: element_index or both screenshot coordinates x and y", true)
	}
	request := psRequest{Tool: "scroll", App: app, X: x, Y: y, Direction: normalized, Pages: pages}
	if hasElement {
		record, err := lookupElement(snapshot, elementIndex)
		if err != nil {
			return textResult(err.Error(), true)
		}
		request.Element = record
	}
	return s.actionResult(app, request)
}

func (s *service) drag(app string, fromX, fromY, toX, toY *float64) toolCallResult {
	if app == "" {
		return textResult("Missing required argument: app", true)
	}
	if fromX == nil {
		return textResult("Missing required argument: from_x", true)
	}
	if fromY == nil {
		return textResult("Missing required argument: from_y", true)
	}
	if toX == nil {
		return textResult("Missing required argument: to_x", true)
	}
	if toY == nil {
		return textResult("Missing required argument: to_y", true)
	}
	snapshot := s.currentSnapshot(app)
	if snapshot == nil {
		return textResult("No app state is available for "+app+". Run get_app_state before action tools.", true)
	}
	return s.actionResult(app, psRequest{Tool: "drag", App: app, FromX: fromX, FromY: fromY, ToX: toX, ToY: toY, WindowBounds: snapshot.WindowBounds})
}

func (s *service) typeText(app, text, elementIndex string) toolCallResult {
	if app == "" {
		return textResult("Missing required argument: app", true)
	}
	if text == "" {
		return textResult("Missing required argument: text", true)
	}
	if s.currentSnapshot(app) == nil {
		return textResult("No app state is available for "+app+". Run get_app_state before action tools.", true)
	}
	var record *elementRecord
    if elementIndex != "" {
        var err error
        record, err = lookupElement(s.currentSnapshot(app), elementIndex)
        if err != nil { return textResult("[input.target_invalid] " + err.Error(), true) }
    }
    return s.actionResult(app, psRequest{Tool: "type_text", App: app, Text: text, Element: record})
}

func (s *service) pressKey(app, key, elementIndex string) toolCallResult {
	if app == "" {
		return textResult("Missing required argument: app", true)
	}
	if key == "" {
		return textResult("Missing required argument: key", true)
	}
	if s.currentSnapshot(app) == nil {
		return textResult("No app state is available for "+app+". Run get_app_state before action tools.", true)
	}
	var record *elementRecord
    if elementIndex != "" {
        var err error
        record, err = lookupElement(s.currentSnapshot(app), elementIndex)
        if err != nil { return textResult("[input.target_invalid] " + err.Error(), true) }
    }
    return s.actionResult(app, psRequest{Tool: "press_key", App: app, Key: key, Element: record})
}

func (s *service) setValue(app, elementIndex, value string) toolCallResult {
    snapshot := s.currentSnapshot(app)
    if snapshot == nil { return textResult("[observation.required] Run get_app_state first", true) }
    var record *elementRecord
    if elementIndex != "" {
        var err error
        record, err = lookupElement(snapshot, elementIndex)
        if err != nil { return textResult("[input.target_invalid] " + err.Error(), true) }
    }
    return s.actionResult(app, psRequest{Tool: "set_value", App: app, Element: record, Value: value})
}

func (s *service) actionResult(app string, request psRequest) toolCallResult {
    observed := s.currentSnapshot(app)
    if observed == nil { return textResult("[observation.required] Run get_app_state before acting.", true) }
	var points [][2]*float64
	if request.Tool == "drag" { points = append(points, [2]*float64{request.FromX, request.FromY}, [2]*float64{request.ToX, request.ToY}) }
	if (request.Tool == "click" || request.Tool == "scroll" || request.Tool == "set_input_target") && request.Element == nil {
        points = append(points, [2]*float64{request.X, request.Y})
    }
    for _, point := range points {
        if err := observed.validateScreenshotPoint(point[0], point[1]); err != nil { return textResult(err.Error(), true) }
    }
    if request.Tool == "set_input_target" { delete(s.inputTargets, observed.App.PID) }
    if request.Tool == "type_text" || request.Tool == "press_key" || request.Tool == "set_value" {
        saved := s.inputTargets[observed.App.PID]
        if saved != nil && saved.WindowHandle == observed.WindowHandle &&
            (request.Element == nil || (saved.Element != nil && reflect.DeepEqual(saved.Element.RuntimeID, request.Element.RuntimeID))) {
            copy := *saved
            request.InputTarget = &copy
            request.Element = saved.Element
        }
        if request.Element == nil && request.InputTarget == nil {
            return textResult("[input.target_required] Specify element_index or use set_input_target; CU never adopts human focus.", true)
        }
    }
    request.TargetPID = observed.App.PID
    request.ObservationID = observed.ObservationID
    request.WindowHandle = observed.WindowHandle
    request.WindowBounds = observed.WindowBounds
    snapshot, result := s.refreshSnapshot(app, request)
    if result.IsError { return result }
    state := snapshot.result()
    if request.Tool == "set_input_target" {
        state.Content = append(state.Content, contentItem{Type: "text", Text: "CU target bound. Coordinate binding sends a message click to the observed window; inspect the screenshot to confirm the input position. Window scope does not prove an editable control. Rebind after focus or pointer changes."})
    }
    if request.Tool == "press_key" {
        state.Content = append(state.Content, contentItem{Type: "text", Text: "Key events posted to the bound control; consumption is unconfirmed. Observe the effect."})
    }
    state.Diagnostics = result.Diagnostics
    state.InputResult = result.InputResult
    if result.InputResult["delivery"] == "posted" {
        state.Content = append(state.Content, contentItem{Type: "text", Text: "Keyboard events posted. Inspect the returned observation to verify their effect; do not automatically replay."})
    }
    return state
}

func (s *service) currentSnapshot(app string) *appSnapshot {
	return s.snapshots[strings.ToLower(app)]
}

func (s *service) retireObservation(observationID string) {
    for key, cached := range s.snapshots {
        if cached.ObservationID == observationID { delete(s.snapshots, key) }
    }
}

func (s *service) refreshSnapshot(app string, request psRequest) (*appSnapshot, toolCallResult) {
    // A native input call must explicitly return a surviving binding. Transport
    // failures and rejected targets cannot leave a previous receiver cached.
    inputCall := request.Tool == "set_input_target" || request.Tool == "type_text" || request.Tool == "set_value" || request.Tool == "press_key"
    if inputCall { delete(s.inputTargets, request.TargetPID) }
	response, err := runPowerShell(request)
	if err != nil {
        failure := textResult(err.Error(), true)
        if inputCall {
            failure.InputResult = map[string]string{"delivery": "unknown", "verification": "unconfirmed", "reason": "native_transport_failed"}
            failure.Content = append(failure.Content, contentItem{Type: "text", Text: "Native input outcome is unknown and the binding has been cleared. Observe and rebind before further input; do not automatically replay."})
        }
        return nil, failure
	}
    // Editing state is private to this native session, including on verification/snapshot failure.
    if inputCall && response.InputTarget != nil && response.InputTarget.PID == request.TargetPID &&
        response.InputTarget.WindowHandle == request.WindowHandle {
        s.inputTargets[response.InputTarget.PID] = response.InputTarget
    }
	if !response.OK {
        failure := textResult(response.Error, true)
        failure.Diagnostics = response.Diagnostics
        failure.InputResult = response.InputResult
        return nil, failure
	}
	if response.Snapshot == nil {
        failure := textResult("[observation.unavailable] Windows runtime did not return an app snapshot. Do not replay the action.", true)
        failure.InputResult = response.InputResult
        failure.Diagnostics = response.Diagnostics
        return nil, failure
	}
	s.rememberSnapshot(app, response.Snapshot)
	return response.Snapshot, toolCallResult{Diagnostics: response.Diagnostics, InputResult: response.InputResult}
}

func (s *service) rememberSnapshot(query string, snapshot *appSnapshot) {
	keys := []string{query, snapshot.App.Name, snapshot.App.BundleIdentifier, strconv.Itoa(snapshot.App.PID)}
	for _, key := range keys {
		key = strings.ToLower(strings.TrimSpace(key))
		if key != "" {
			s.snapshots[key] = snapshot
		}
	}
}

func lookupElement(snapshot *appSnapshot, elementIndex string) (*elementRecord, error) {
	index, err := strconv.Atoi(elementIndex)
	if err != nil {
		return nil, fmt.Errorf("unknown element_index %q", elementIndex)
	}
	for _, record := range snapshot.Elements {
		if record.Index == index {
			copy := record
			return &copy, nil
		}
	}
	return nil, fmt.Errorf("unknown element_index %q", elementIndex)
}
