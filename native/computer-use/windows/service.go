package main

import (
    "bytes"
    "encoding/base64"
    "image/png"
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
    "reflect"
	"strconv"
	"strings"
	"time"
)

var version = "0.3.3"

var clickMethodValues = []string{"auto", "accessibility", "app_post"}

//go:embed runtime.ps1
var windowsRuntimeScript string

const serverInstructions = "Computer Use tools operate Windows apps through observations and actions. Begin with get_app_state. Every action consumes the latest observation_id, even on failure; use the next returned observation before acting again. Coordinates are screenshot pixels. Prefer the exact observed element; clicks do not substitute other controls. Use scroll for moving through a page, list, conversation, document, or other content. Target an observed scrollable element when available; otherwise provide x/y inside the intended scroll region and the executor sends a window-targeted wheel message without holding a mouse button. Never use drag to imitate ordinary scrolling. Use drag only when the task explicitly requires holding the primary mouse button to move an object, handle, slider, selection, or other draggable control. set_input_target binds either an editable element_index or explicit x/y in the latest screenshot. The local executor uses directed background messages when the native receiver is available. If an inactive application has no confirmed receiver, it automatically obtains a short foreground focus lease, restores the same bound element or position, sends one input transaction through the system keyboard queue, and restores the previous foreground window. The model must not use Raise, repeated clicks, or repeated text to prepare or retry input. set_value requires a native Edit/RichEdit receiver, selects all through its native protocol, and confirms the full range before sending text or Backspace. Other receivers reject replacement before input; type_text is insertion only. Modifier chords remain unsupported. Foreground ownership changes abort delivery. Posted or interrupted input is never permission to replay. Inspect the fresh observation before further external action."

type toolDefinition struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Annotations map[string]any `json:"annotations,omitempty"`
	InputSchema map[string]any `json:"inputSchema"`
}

type contentItem struct {
	Type     string `json:"type"`
	Text     string `json:"text,omitempty"`
	Data     string `json:"data,omitempty"`
	MimeType string `json:"mimeType,omitempty"`
}

type toolCallResult struct {
    Diagnostics []string `json:"diagnostics,omitempty"`
    InputResult map[string]string `json:"input_result,omitempty"`
	Content []contentItem `json:"content"`
	IsError bool          `json:"isError"`
}

func textResult(text string, isError bool) toolCallResult {
	return toolCallResult{Content: []contentItem{{Type: "text", Text: text}}, IsError: isError}
}

type appDescriptor struct {
	Name             string `json:"name"`
	BundleIdentifier string `json:"bundleIdentifier,omitempty"`
	PID              int    `json:"pid"`
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
		Content: []contentItem{{Type: "text", Text: s.renderedText()}},
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

func runPowerShell(request psRequest) (*psResponse, error) {
	if runtime.GOOS != "windows" {
		return nil, errors.New("Windows Computer Use runtime requires powershell.exe on Windows")
	}

	tempDir, err := os.MkdirTemp("", "open-computer-use-windows-*")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(tempDir)

	scriptPath := filepath.Join(tempDir, "runtime.ps1")
	operationPath := filepath.Join(tempDir, "operation.json")
	if err := os.WriteFile(scriptPath, []byte(windowsRuntimeScript), 0o600); err != nil {
		return nil, err
	}
	operationData, err := json.Marshal(request)
	if err != nil {
		return nil, err
	}
	if err := os.WriteFile(operationPath, operationData, 0o600); err != nil {
		return nil, err
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", scriptPath, operationPath)
	output, err := cmd.CombinedOutput()
	if ctx.Err() == context.DeadlineExceeded {
		return nil, errors.New("Windows runtime timed out after 30s")
	}
	if err != nil {
		text := strings.TrimSpace(string(output))
		if text == "" {
			text = err.Error()
		}
		return nil, fmt.Errorf("Windows runtime failed: %s", text)
	}

	var response psResponse
	if err := json.Unmarshal(output, &response); err != nil {
		return nil, fmt.Errorf("Windows runtime returned invalid JSON: %w: %s", err, strings.TrimSpace(string(output)))
	}
	return &response, nil
}

func requiredString(args map[string]any, key string) string {
	value, _ := args[key].(string)
	return strings.TrimSpace(value)
}

func optionalString(args map[string]any, key string) string {
	value, _ := args[key].(string)
	return value
}

func requiredElementIndex(args map[string]any) string {
	return strings.TrimSpace(optionalElementIndex(args))
}

func optionalElementIndex(args map[string]any) string {
	return elementIndexString(args["element_index"])
}

func elementIndexString(value any) string {
	switch value := value.(type) {
	case string:
		return value
	case json.Number:
		if integer, err := value.Int64(); err == nil {
			return strconv.FormatInt(integer, 10)
		}
		if float, err := value.Float64(); err == nil {
			return integerElementIndexFloat(float)
		}
	case float64:
		return integerElementIndexFloat(value)
	case int:
		return strconv.Itoa(value)
	case int64:
		return strconv.FormatInt(value, 10)
	}
	return ""
}

func integerElementIndexFloat(value float64) string {
	if math.IsNaN(value) || math.IsInf(value, 0) || math.Trunc(value) != value {
		return ""
	}
	return strconv.FormatInt(int64(value), 10)
}

func requiredFloat(args map[string]any, key string) *float64 {
	return optionalFloat(args, key)
}

func optionalFloat(args map[string]any, key string) *float64 {
	switch value := args[key].(type) {
	case float64:
		return &value
	case int:
		float := float64(value)
		return &float
	case json.Number:
		float, err := value.Float64()
		if err == nil {
			return &float
		}
	}
	return nil
}

func optionalTextLimit(args map[string]any, key string) (*textLimit, error) {
	value, ok := args[key]
	if !ok {
		return nil, nil
	}
	return textLimitFromValue(value, key)
}

func textLimitFromValue(value any, key string) (*textLimit, error) {
	if stringValue, ok := value.(string); ok {
		if strings.EqualFold(stringValue, "max") {
			return &textLimit{max: true}, nil
		}
		return nil, fmt.Errorf("%s must be a positive integer or max", key)
	}
	integer, err := positiveIntFromValue(value, key)
	if err != nil {
		return nil, fmt.Errorf("%s must be a positive integer or max", key)
	}
	return &textLimit{count: *integer}, nil
}

func optionalPositiveInt(args map[string]any, key string) (*int, error) {
	value, ok := args[key]
	if !ok {
		return nil, nil
	}
	return positiveIntFromValue(value, key)
}

func positiveIntFromValue(value any, key string) (*int, error) {
	switch typed := value.(type) {
	case int:
		return positiveIntFromInt64(int64(typed), key)
	case float64:
		if !isWholeNumber(typed) {
			return nil, fmt.Errorf("%s must be a positive integer", key)
		}
		return positiveIntFromFloat64(typed, key)
	case json.Number:
		integer, err := typed.Int64()
		if err != nil {
			return nil, fmt.Errorf("%s must be a positive integer", key)
		}
		return positiveIntFromInt64(integer, key)
	default:
		return nil, fmt.Errorf("%s must be a positive integer", key)
	}
}

func positiveIntFromFloat64(value float64, key string) (*int, error) {
	if !isWholeNumber(value) || value <= 0 || value > float64(maxInt()) {
		return nil, fmt.Errorf("%s must be a positive integer", key)
	}
	integer := int(value)
	return &integer, nil
}

func positiveIntFromInt64(value int64, key string) (*int, error) {
	if value <= 0 || value > int64(maxInt()) {
		return nil, fmt.Errorf("%s must be a positive integer", key)
	}
	integer := int(value)
	return &integer, nil
}

func isWholeNumber(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0) && math.Trunc(value) == value
}

func maxInt() int {
	return int(^uint(0) >> 1)
}

func intValue(value *float64, fallback int) int {
	if value == nil {
		return fallback
	}
	return int(*value)
}

func floatValue(value *float64, fallback float64) float64 {
	if value == nil {
		return fallback
	}
	return *value
}

func defaultString(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}

func parseClickMethod(value string) (string, error) {
	normalized := strings.ToLower(strings.TrimSpace(value))
	if normalized == "" {
		return "auto", nil
	}
	for _, candidate := range clickMethodValues {
		if normalized == candidate {
			return normalized, nil
		}
	}
	return "", fmt.Errorf("Invalid click_method %q. Expected one of: %s", value, strings.Join(clickMethodValues, ", "))
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
