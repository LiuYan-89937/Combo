import AppKit
import ApplicationServices
import Foundation
import ImageIO

struct VisualCursorTarget: Equatable {
    let point: CGPoint
    let window: CursorTargetWindow?
}

public enum ClickMethod: String, CaseIterable, Sendable {
    case auto
    case accessibility
    case appPost = "app_post"
    case skyClick = "sky_click"
    case global
}

func clickActionSnapshotRecoveryPolicy(for method: ClickMethod) -> SnapshotRecoveryPolicy {
    .readOnly
}

func parseClickMethod(_ rawValue: String?) throws -> ClickMethod {
    let normalized = rawValue?
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased() ?? ClickMethod.auto.rawValue

    guard let method = ClickMethod(rawValue: normalized) else {
        let expected = ClickMethod.allCases.map(\.rawValue).joined(separator: ", ")
        throw ComputerUseError.message(
            "Invalid click_method '\(rawValue ?? "")'. Expected one of: \(expected)"
        )
    }

    return method
}

func validateClickMethod(
    _ method: ClickMethod,
    hasElementIndex: Bool,
    environment: [String: String]
) throws {
    if method == .accessibility, !hasElementIndex {
        throw ComputerUseError.message("click_method 'accessibility' requires element_index")
    }

    if method == .global, !globalPointerFallbacksEnabled(environment: environment) {
        throw ComputerUseError.message(
            "click_method 'global' requires OPEN_COMPUTER_USE_ALLOW_GLOBAL_POINTER_FALLBACKS=1 because it may move the system pointer and change foreground focus"
        )
    }
}

func validateSkyClickArguments(
    method: ClickMethod,
    mouseButton: String,
    clickCount: Int
) throws {
    guard method == .skyClick else {
        return
    }

    guard mouseButton.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == MouseButtonKind.left.rawValue else {
        throw ComputerUseError.message(
            "click_method 'sky_click' only supports mouse_button 'left'"
        )
    }

    guard (1...2).contains(clickCount) else {
        throw ComputerUseError.message(
            "click_method 'sky_click' supports click_count 1 or 2"
        )
    }
}

struct VisualCursorScreenMapping: Equatable {
    let screenStateFrame: CGRect
    let appKitFrame: CGRect
}

func currentVisualCursorScreenMappings() -> [VisualCursorScreenMapping] {
    NSScreen.screens.compactMap { screen in
        guard let screenNumber = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
            return nil
        }

        return VisualCursorScreenMapping(
            screenStateFrame: CGDisplayBounds(CGDirectDisplayID(screenNumber.uint32Value)),
            appKitFrame: screen.frame
        )
    }
}

func screenStatePointToAppKitGlobalPoint(
    fromScreenStatePoint point: CGPoint,
    screenMappings: [VisualCursorScreenMapping] = currentVisualCursorScreenMappings()
) -> CGPoint {
    guard let mapping = screenMappings.first(where: { $0.screenStateFrame.contains(point) }) else {
        return point
    }

    let localX = point.x - mapping.screenStateFrame.minX
    let localY = point.y - mapping.screenStateFrame.minY

    return CGPoint(
        x: mapping.appKitFrame.minX + localX,
        y: mapping.appKitFrame.maxY - localY
    )
}

func visualCursorAppKitPoint(
    fromScreenStatePoint point: CGPoint,
    screenMappings: [VisualCursorScreenMapping] = currentVisualCursorScreenMappings()
) -> CGPoint {
    screenStatePointToAppKitGlobalPoint(
        fromScreenStatePoint: point,
        screenMappings: screenMappings
    )
}

func inputEventPoint(
    fromScreenStatePoint point: CGPoint,
    screenMappings: [VisualCursorScreenMapping] = currentVisualCursorScreenMappings()
) -> CGPoint {
    point
}

func makeVisualCursorTarget(
    at point: CGPoint,
    targetWindowID: CGWindowID?,
    targetWindowLayer: Int?,
    screenMappings: [VisualCursorScreenMapping] = currentVisualCursorScreenMappings()
) -> VisualCursorTarget {
    VisualCursorTarget(
        point: screenStatePointToAppKitGlobalPoint(
            fromScreenStatePoint: point,
            screenMappings: screenMappings
        ),
        window: targetWindowID.map { CursorTargetWindow(windowID: $0, layer: targetWindowLayer ?? 0) }
    )
}

func makeVisualCursorTarget(
    localFrame: CGRect?,
    windowBounds: CGRect?,
    targetWindowID: CGWindowID?,
    targetWindowLayer: Int?,
    screenMappings: [VisualCursorScreenMapping] = currentVisualCursorScreenMappings()
) -> VisualCursorTarget? {
    guard let localFrame, let windowBounds else {
        return nil
    }

    let point = CGPoint(
        x: windowBounds.minX + localFrame.midX,
        y: windowBounds.minY + localFrame.midY
    )
    return makeVisualCursorTarget(
        at: point,
        targetWindowID: targetWindowID,
        targetWindowLayer: targetWindowLayer,
        screenMappings: screenMappings
    )
}

func inputFallbackDebugEnabled(environment: [String: String]) -> Bool {
    guard let rawValue = environment["OPEN_COMPUTER_USE_DEBUG_INPUT_FALLBACKS"]?
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()
    else {
        return false
    }

    return ["1", "true", "yes", "on"].contains(rawValue)
}

func globalPointerFallbacksEnabled(environment: [String: String]) -> Bool {
    guard let rawValue = environment["OPEN_COMPUTER_USE_ALLOW_GLOBAL_POINTER_FALLBACKS"]?
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()
    else {
        return false
    }

    return ["1", "true", "yes", "on"].contains(rawValue)
}

func screenshotPixelScale(
    screenshotPixelSize: CGSize?,
    windowBounds: CGRect?
) -> CGSize {
    guard
        let screenshotPixelSize,
        let windowBounds,
        windowBounds.width > 0,
        windowBounds.height > 0,
        screenshotPixelSize.width > 0,
        screenshotPixelSize.height > 0
    else {
        return CGSize(width: 1, height: 1)
    }

    return CGSize(
        width: screenshotPixelSize.width / windowBounds.width,
        height: screenshotPixelSize.height / windowBounds.height
    )
}

func screenshotPixelToWindowPoint(
    _ point: CGPoint,
    screenshotPixelSize: CGSize?,
    windowBounds: CGRect?
) -> CGPoint {
    let scale = screenshotPixelScale(
        screenshotPixelSize: screenshotPixelSize,
        windowBounds: windowBounds
    )
    return CGPoint(
        x: point.x / scale.width,
        y: point.y / scale.height
    )
}

let nonSettableSetValueErrorMessage = "Cannot set a value for an element that is not settable"

func setValueAttributeIsSettable(result: AXError, settable: Bool, attribute: String) throws -> Bool {
    guard result == .success else {
        throw ComputerUseError.message("AXUIElementIsAttributeSettable(\(attribute)) failed with \(result.rawValue)")
    }

    return settable
}

func invalidSecondaryActionErrorMessage(action: String, elementIndex: Int) -> String {
    "\(action) is not a valid secondary action for \(elementIndex)"
}

func localClickActionPoints(frame: CGRect, isSyntheticText: Bool) -> [CGPoint] {
    let center = CGPoint(x: frame.midX, y: frame.midY)
    let leading = CGPoint(
        x: frame.minX + min(max(frame.width * 0.3, 20), max(frame.width - 4, 20)),
        y: frame.midY
    )

    if isSyntheticText {
        return [leading]
    }

    if abs(leading.x - center.x) < 1 {
        return [center]
    }

    return [center, leading]
}

func isLikelySyntheticSideActionCandidate(
    parentFrame: CGRect?,
    candidateFrame: CGRect?,
    hasPrimaryAction: Bool,
    labels: [String]
) -> Bool {
    let hasSideActionLabel = labels.contains { label in
        let normalized = label.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty else {
            return false
        }

        if normalized == "完成" || normalized == "done" || normalized == "complete" || normalized == "archive" {
            return true
        }

        if normalized.count <= 24 {
            if normalized.contains("完成") {
                return true
            }

            if normalized.contains("mark") && (normalized.contains("done") || normalized.contains("complete")) {
                return true
            }
        }

        return false
    }

    guard let parentFrame, let candidateFrame else {
        return false
    }

    let trailingBandWidth = min(max(parentFrame.width * 0.22, 56), 140)
    let isTrailing = candidateFrame.midX >= parentFrame.maxX - trailingBandWidth
    let compactWidth = candidateFrame.width <= max(88, parentFrame.width * 0.18)
    let compactHeight = candidateFrame.height <= max(44, parentFrame.height * 1.2)
    let isCompact = compactWidth && compactHeight

    if hasSideActionLabel && hasPrimaryAction && isCompact {
        return true
    }

    return isTrailing && isCompact && (hasPrimaryAction || hasSideActionLabel)
}

func shouldScanDescendantsOfHitRecord(originalFrame: CGRect?, hitFrame: CGRect?) -> Bool {
    guard let originalFrame, let hitFrame else {
        return true
    }

    let originalArea = max(originalFrame.width * originalFrame.height, 1)
    let hitArea = hitFrame.width * hitFrame.height
    if hitArea > max(originalArea * 12, 20_000) {
        return false
    }

    if hitFrame.height > max(originalFrame.height * 4, 96),
       hitFrame.width > max(originalFrame.width * 2, 240)
    {
        return false
    }

    return true
}

func isLikelyContainingRowActionFrame(
    targetFrame: CGRect,
    candidateFrame: CGRect?,
    hasPrimaryAction: Bool
) -> Bool {
    let targetCenter = CGPoint(x: targetFrame.midX, y: targetFrame.midY)
    guard
        hasPrimaryAction,
        let candidateFrame,
        candidateFrame.insetBy(dx: -2, dy: -2).contains(targetCenter),
        candidateFrame.width >= targetFrame.width,
        candidateFrame.height >= targetFrame.height,
        candidateFrame.height <= max(targetFrame.height + 32, targetFrame.height * 2)
    else {
        return false
    }

    return true
}

func canUseActivationOnlyClickFallback(role: String?) -> Bool {
    guard let role else {
        return false
    }

    return role == kAXWindowRole as String
}

func isElectronScopedWebRowClickOptimizationTarget(appName: String, bundleIdentifier: String?) -> Bool {
    let normalizedBundleIdentifier = bundleIdentifier?
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()
    let normalizedName = appName
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()

    if let normalizedBundleIdentifier,
       normalizedBundleIdentifier.hasPrefix("com.electron.")
            || normalizedBundleIdentifier.contains(".electron.")
            || normalizedBundleIdentifier.contains("lark")
            || normalizedBundleIdentifier.contains("feishu")
    {
        return true
    }

    return normalizedName == "lark" || normalizedName == "feishu" || normalizedName == "飞书"
}

func shouldPreferContainingWebRowAXClickCandidate(
    role: String?,
    isSyntheticText: Bool,
    hasWebAreaAncestor: Bool,
    appName: String,
    bundleIdentifier: String?
) -> Bool {
    guard hasWebAreaAncestor,
          isElectronScopedWebRowClickOptimizationTarget(
            appName: appName,
            bundleIdentifier: bundleIdentifier
          )
    else {
        return false
    }

    guard let role else {
        return isSyntheticText
    }

    return role == kAXStaticTextRole as String || role == kAXGroupRole as String || isSyntheticText
}

public final class ComputerUseService {
    private var snapshotsByApp: [String: AppSnapshot] = [:]
    private var inputTargets: [pid_t: InputTarget] = [:]
    private(set) var diagnostics: [String] = []
    func resetDiagnostics() { diagnostics.removeAll(keepingCapacity: true) }

    public init() {}

    public func listApps() -> ToolCallResult {
        ToolCallResult.text(
            AppDiscovery.listCatalog()
                .map(\.renderedLine)
                .joined(separator: "\n")
        )
    }

    public func getAppState(
        app query: String,
        textLimit: SnapshotTextLimit = .defaults,
        treeLimits: AccessibilityTreeLimits = .defaults
    ) throws -> ToolCallResult {
        snapshotResult(for: try refreshSnapshot(for: query, textLimit: textLimit, treeLimits: treeLimits), style: .fullState)
    }

    public func click(
        app query: String,
        elementIndex: String?,
        x: Double?,
        y: Double?,
        clickCount: Int,
        mouseButton: String,
        clickMethod: ClickMethod = .auto
    ) throws -> ToolCallResult {
        try validateClickMethod(
            clickMethod,
            hasElementIndex: elementIndex != nil,
            environment: ProcessInfo.processInfo.environment
        )
        try validateSkyClickArguments(
            method: clickMethod,
            mouseButton: mouseButton,
            clickCount: clickCount
        )

        let snapshot = try currentSnapshot(for: query)
        debugClickDecision("request observation=\(snapshot.observationID) pid=\(snapshot.app.pid) window=\(String(describing: snapshot.targetWindowID)) bounds=\(String(describing: snapshot.windowBounds)) screenshotPixels=\(String(describing: screenshotPixelSize(snapshot: snapshot))) method=\(clickMethod.rawValue) element=\(elementIndex ?? "nil") screenshotPoint=\(diagnosticPoint(x: x, y: y)) button=\(mouseButton) count=\(clickCount)")
        traceRuntimeContext(stage: "before", snapshot: snapshot)
        defer { traceRuntimeContext(stage: "after", snapshot: snapshot) }
        let button = MouseButtonKind(rawValue: mouseButton.lowercased()) ?? .left
        if snapshot.mode == .fixture {
            guard clickMethod == .auto else {
                throw ComputerUseError.message(
                    "click_method '\(clickMethod.rawValue)' is not supported for fixture apps"
                )
            }

            let cursorTarget: VisualCursorTarget?
            if let elementIndex {
                let record = try lookupElement(snapshot: snapshot, index: elementIndex)
                guard let identifier = record.identifier else {
                    throw ComputerUseError.invalidArguments("fixture click requires an identifier-backed element")
                }
                cursorTarget = visualCursorTarget(for: record, snapshot: snapshot)
                moveVisualCursor(to: cursorTarget)
                try FixtureBridge.post(FixtureCommand(kind: "click", identifier: identifier))
            } else if let x, let y {
                let identifier = try fixtureIdentifier(at: CGPoint(x: x, y: y), snapshot: snapshot)
                cursorTarget = fixtureVisualCursorTarget(identifier: identifier, snapshot: snapshot)
                moveVisualCursor(to: cursorTarget)
                try FixtureBridge.post(FixtureCommand(kind: "click", identifier: identifier, x: x, y: y))
            } else {
                throw ComputerUseError.invalidArguments("click requires either element_index or x/y")
            }

            Thread.sleep(forTimeInterval: 0.15)
            pulseVisualCursor(at: cursorTarget, clickCount: clickCount, mouseButton: button)
            return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
        }

        try validateSnapshotWindow(snapshot)
        if let elementIndex {
            let record = try lookupElement(snapshot: snapshot, index: elementIndex)
            try validateElementIdentity(record.element, snapshot: snapshot, requireWindow: false)
            // A semantic action can target a menu item without a visible frame.
            if clickMethod == .auto || clickMethod == .accessibility {
                let cursor = record.localFrame.flatMap { frame -> VisualCursorTarget? in
                    guard frame.width > 0, frame.height > 0 else { return nil }
                    return visualCursorTarget(for: record, snapshot: snapshot)
                }
                moveVisualCursor(to: cursor)
                if try performPreferredClick(on: record, button: button, clickCount: clickCount) {
                    debugClickDecision("handled by requested target \(clickDebugDescription(record))")
                    pulseVisualCursor(at: cursor, clickCount: clickCount, mouseButton: button)
                    return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
                }
                if clickMethod == .accessibility {
                    throw ComputerUseError.message("[click.unsupported] The requested element does not support this click")
                }
            }
            let windowPoint = try pointerPoint(for: record, snapshot: snapshot)
            let targetPoint = try windowPointToGlobalPoint(snapshot: snapshot, point: windowPoint)
            try dispatchPointerClick(method: clickMethod, point: targetPoint, windowPoint: windowPoint,
                                     button: button, clickCount: clickCount, snapshot: snapshot,
                                     targetDescription: "element_index=\(elementIndex)")
        } else if let x, let y {
            let screenshotPoint = CGPoint(x: x, y: y)
            guard x.isFinite, y.isFinite, let size = screenshotPixelSize(snapshot: snapshot),
                  CGRect(origin: .zero, size: size).contains(screenshotPoint) else {
                throw ComputerUseError.invalidArguments("[click.target_invalid] Coordinates must be inside the observed screenshot")
            }
            let windowPoint = screenshotPixelToWindowPointInSnapshot(snapshot: snapshot, point: screenshotPoint)
            let targetPoint = try windowPointToGlobalPoint(snapshot: snapshot, point: windowPoint)
            let candidates = try clickCandidates(at: windowPoint, in: snapshot)
            debugClickDecision("mapping observation=\(snapshot.observationID) screenshotPoint=\(diagnosticPoint(screenshotPoint)) windowPoint=\(diagnosticPoint(windowPoint)) globalPoint=\(diagnosticPoint(targetPoint)) candidates=\(candidates.map(clickDebugDescription).joined(separator: " || "))")
            var handled = false
            if clickMethod == .auto {
                for record in candidates {
                    if try performPreferredClick(on: record, button: button, clickCount: clickCount) {
                        debugClickDecision("handled by point-containing target \(clickDebugDescription(record))")
                        let cursor = makeVisualCursorTarget(at: targetPoint, targetWindowID: snapshot.targetWindowID, targetWindowLayer: snapshot.targetWindowLayer)
                        moveVisualCursor(to: cursor)
                        pulseVisualCursor(at: cursor, clickCount: clickCount, mouseButton: button)
                        handled = true
                        break
                    }
                }
            }
            if !handled {
                try dispatchPointerClick(method: clickMethod, point: targetPoint, windowPoint: windowPoint,
                                         button: button, clickCount: clickCount, snapshot: snapshot,
                                         targetDescription: "screenshot=(\(x),\(y))")
            }
        } else {
            throw ComputerUseError.invalidArguments("click requires either element_index or x/y")
        }

        let refreshed = try refreshSnapshot(
            for: query,
            recoveryPolicy: clickActionSnapshotRecoveryPolicy(for: clickMethod)
        )
        debugClickDecision("result observation_before=\(snapshot.observationID) observation_after=\(refreshed.observationID) window_after=\(String(describing: refreshed.targetWindowID)) bounds_after=\(String(describing: refreshed.windowBounds))")
        return snapshotResult(for: refreshed, style: .actionResult)
    }

    public func performSecondaryAction(app query: String, elementIndex: String, action: String) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let record = try lookupElement(snapshot: snapshot, index: elementIndex)

        if snapshot.mode == .fixture {
            guard action.caseInsensitiveCompare("Raise") == .orderedSame else {
                throw ComputerUseError.message(invalidSecondaryActionMessage(action: action, record: record))
            }

            return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
        }

        guard let rawAction = matchingAction(requested: action, record: record) else {
            throw ComputerUseError.message(invalidSecondaryActionMessage(action: action, record: record))
        }

        guard let element = record.element else {
            throw ComputerUseError.stateUnavailable("element \(elementIndex) has no backing accessibility object")
        }

        let result = AXUIElementPerformAction(element, rawAction as CFString)
        guard result == .success else {
            throw ComputerUseError.message("AXUIElementPerformAction failed with \(result.rawValue)")
        }

        Thread.sleep(forTimeInterval: 0.15)
        return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
    }

    public func scroll(app query: String, direction: String, elementIndex: String, pages: Double) throws -> ToolCallResult {
        let normalized = direction.lowercased()
        guard ["up", "down", "left", "right"].contains(normalized) else {
            throw ComputerUseError.message("Invalid scroll direction: \(direction)")
        }
        guard pages.isFinite, pages > 0 else {
            throw ComputerUseError.message("pages must be > 0")
        }

        let snapshot = try currentSnapshot(for: query)
        let record = try lookupElement(snapshot: snapshot, index: elementIndex)

        if snapshot.mode == .fixture {
            guard let identifier = record.identifier else {
                throw ComputerUseError.invalidArguments("fixture scroll requires an identifier-backed element")
            }
            try FixtureBridge.post(FixtureCommand(kind: "scroll", identifier: identifier, direction: normalized, pages: pages))
            Thread.sleep(forTimeInterval: 0.15)
            return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
        }

        if let repeatCount = integralScrollPageCount(pages),
           let rawAction = record.rawActions.first(where: { $0.caseInsensitiveCompare("AXScroll\(normalized.capitalized)ByPage") == .orderedSame }),
           let element = record.element {
            for _ in 0..<repeatCount {
                _ = AXUIElementPerformAction(element, rawAction as CFString)
                Thread.sleep(forTimeInterval: 0.05)
            }
        } else if let point = try globalPoint(for: record, snapshot: snapshot) {
            try performScrollEvent(
                at: point,
                direction: normalized,
                pages: pages,
                targetDescription: "element_index=\(elementIndex)",
                snapshot: snapshot
            )
        } else {
            throw ComputerUseError.stateUnavailable("element \(elementIndex) has no scrollable frame")
        }

        return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
    }

    public func drag(app query: String, fromX: Double, fromY: Double, toX: Double, toY: Double) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        if snapshot.mode == .fixture {
            try FixtureBridge.post(FixtureCommand(kind: "drag", identifier: "fixture-drag-pad", x: fromX, y: fromY, toX: toX, toY: toY))
            Thread.sleep(forTimeInterval: 0.15)
            return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
        }

        let start = try screenshotToGlobalPoint(snapshot: snapshot, x: fromX, y: fromY)
        let end = try screenshotToGlobalPoint(snapshot: snapshot, x: toX, y: toY)
        try performDragEvent(
            from: start,
            to: end,
            targetDescription: "from=(\(Int(fromX)), \(Int(fromY))) to=(\(Int(toX)), \(Int(toY)))",
            snapshot: snapshot
        )
        return snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
    }

    public func setInputTarget(app query: String, elementIndex: String, selectionStart: Int? = nil, selectionLength: Int? = nil) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target = try bindInputTarget(snapshot: snapshot, index: elementIndex)
        if selectionStart != nil || selectionLength != nil {
            guard let start = selectionStart, let length = selectionLength,
                  start >= 0, length >= 0, start <= (target.value as NSString).length,
                  length <= (target.value as NSString).length - start else {
                throw ComputerUseError.invalidArguments("Provide a valid UTF-16 selection_start and selection_length together")
            }
            target.selection = CFRange(location: start, length: length)
        }
        inputTargets[snapshot.app.pid] = target
        debugClickDecision("input target bound observation=\(snapshot.observationID) pid=\(snapshot.app.pid) window=\(String(describing: snapshot.targetWindowID)) selection=\(String(describing: target.selection))")
        let result = snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
        return ToolCallResult(content: result.content + [.text("CU input target bound. System focus was not changed. UTF-16 selection: \(String(describing: target.selection)).")])
    }

    private func readInputSelection(_ element: AXUIElement) -> CFRange? {
        var raw: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXSelectedTextRangeAttribute as CFString, &raw) == .success,
              let raw, CFGetTypeID(raw) == AXValueGetTypeID() else { return nil }
        var range = CFRange(location: 0, length: 0)
        guard AXValueGetValue(raw as! AXValue, .cfRange, &range) else { return nil }
        return range
    }

    private func bindInputTarget(snapshot: AppSnapshot, index: String) throws -> InputTarget {
        let element = try inputElement(snapshot: snapshot, index: index)
        guard let window = snapshot.windowElement else {
            throw ComputerUseError.message("[input.target_invalid] The observation has no window identity")
        }
        return InputTarget(element: element, window: window, windowID: snapshot.targetWindowID,
                           value: try inputText(element), selection: readInputSelection(element))
    }

    private func resolveInputTarget(snapshot: AppSnapshot, index: String?) throws -> InputTarget {
        if let index {
            let element = try inputElement(snapshot: snapshot, index: index)
            if let saved = inputTargets[snapshot.app.pid], CFEqual(saved.element, element),
               saved.windowID == snapshot.targetWindowID {
                try validateInputTarget(saved, snapshot: snapshot)
                return saved
            }
            let target = try bindInputTarget(snapshot: snapshot, index: index)
            inputTargets[snapshot.app.pid] = target
            return target
        }
        guard let target = inputTargets[snapshot.app.pid] else {
            throw ComputerUseError.message("[input.target_required] Specify element_index or use set_input_target. CU never adopts the human's focus.")
        }
        try validateInputTarget(target, snapshot: snapshot)
        return target
    }

    private func validateInputTarget(_ target: InputTarget, snapshot: AppSnapshot) throws {
        try validateInputElement(target.element, snapshot: snapshot)
        guard let window = snapshot.windowElement, CFEqual(window, target.window),
              target.windowID == snapshot.targetWindowID else {
            inputTargets.removeValue(forKey: snapshot.app.pid)
            throw ComputerUseError.message("[input.target_invalid] The bound input window changed; bind a target from a fresh observation")
        }
    }

    private func prepareInputSelection(_ target: InputTarget, range: CFRange) throws {
        if let current = readInputSelection(target.element),
           current.location == range.location, current.length == range.length { return }
        guard try isSettableForSetValue(element: target.element, attribute: kAXSelectedTextRangeAttribute) else {
            throw ComputerUseError.message("[input.background_unsupported] This control cannot address the CU selection without relying on its own caret")
        }
        var requested = range
        guard let value = AXValueCreate(.cfRange, &requested),
              AXUIElementSetAttributeValue(target.element, kAXSelectedTextRangeAttribute as CFString, value) == .success,
              let actual = readInputSelection(target.element),
              actual.location == range.location, actual.length == range.length else {
            throw ComputerUseError.message("[input.selection_unconfirmed] The control did not confirm the requested selection; no text was sent")
        }
    }

    public func typeText(app query: String, text: String, elementIndex: String? = nil, inputMethod: String = "accessibility", verificationTimeout: TimeInterval? = nil) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target = try resolveInputTarget(snapshot: snapshot, index: elementIndex)
        guard ["accessibility", "keyboard"].contains(inputMethod) else {
            throw ComputerUseError.invalidArguments("Unknown input_method")
        }
        let before = try inputText(target.element)
        guard before == target.value, let range = target.selection,
              range.location >= 0, range.length >= 0, range.location <= (before as NSString).length,
              range.length <= (before as NSString).length - range.location else {
            target.selection = nil
            throw ComputerUseError.message("[input.target_stale] Text changed or the CU selection is unavailable. Observe and explicitly bind a new selection with set_input_target.")
        }
        let expected = (before as NSString).replacingCharacters(in: NSRange(location: range.location, length: range.length), with: text)
        // Choose a capability before delivery. Never retry a failed write through another path.
        let wholeValue: Bool
        if inputMethod == "accessibility" {
            wholeValue = try isSettableForSetValue(element: target.element, attribute: kAXValueAttribute)
        } else {
            wholeValue = false
        }
        if inputMethod == "keyboard" {
            try validateBackgroundKeyboard(target: target, snapshot: snapshot)
        } else if !wholeValue {
            guard try isSettableForSetValue(element: target.element, attribute: kAXSelectedTextAttribute) else {
                throw ComputerUseError.message("[input.background_unsupported] No writable text value or selection is available")
            }
        }
        if !wholeValue { try prepareInputSelection(target, range: range) }
        debugClickDecision("input request tool=type_text observation=\(snapshot.observationID) pid=\(snapshot.app.pid) target=\(diagnosticElementDescription(target.element)) method=\(inputMethod) whole_value=\(wholeValue) before_length=\((before as NSString).length) selection=\(range) submitted_length=\((text as NSString).length)")
        target.selection = nil
        invalidateSnapshot(snapshot)
        do {
            if inputMethod == "keyboard" {
                try InputSimulation.typeText(text, pid: snapshot.app.pid) {
                    try self.validateBackgroundKeyboard(target: target, snapshot: snapshot)
                }
            } else {
                let attribute = wholeValue ? kAXValueAttribute : kAXSelectedTextAttribute
                let value = wholeValue ? expected : text
                let error = AXUIElementSetAttributeValue(target.element, attribute as CFString, value as CFString)
                debugClickDecision("input delivery attribute=\(attribute) result=\(error.rawValue)")
                guard error == .success else { return inputDeliveryFailure("Text delivery returned \(error.rawValue); observe before further input") }
            }
        } catch { return inputDeliveryFailure("Input delivery may be partial; observe before further input") }
        let result = try verifiedInputResult(element: target.element, expected: expected, query: query, timeout: verificationTimeout)
        if result.inputResult["verification"] == "value_verified" {
            target.value = expected
            target.selection = CFRange(location: range.location + (text as NSString).length, length: 0)
        }
        return result
    }

    public func pressKey(app query: String, key: String, elementIndex: String? = nil) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target = try resolveInputTarget(snapshot: snapshot, index: elementIndex)
        try validateBackgroundKeyboard(target: target, snapshot: snapshot)
        guard try inputText(target.element) == target.value, let range = target.selection else {
            throw ComputerUseError.message("[input.target_stale] Bind a fresh CU selection before keyboard input")
        }
        try prepareInputSelection(target, range: range)
        target.selection = nil  // Arbitrary keys can move the caret or change the document.
        invalidateSnapshot(snapshot)
        try InputSimulation.pressKey(key, pid: snapshot.app.pid)
        let result = snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
        return ToolCallResult(content: result.content + [.text("Key events posted to the target process. Consumption is unconfirmed; observe the application effect. Bind a fresh selection before further text input.")],
                              inputResult: ["delivery": "unknown", "verification": "unconfirmed", "reason": "key_consumption_unobservable"])
    }

    public func setValue(app query: String, elementIndex: String, value: String, verificationTimeout: TimeInterval? = nil) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target = try bindInputTarget(snapshot: snapshot, index: elementIndex)
        inputTargets[snapshot.app.pid] = target
        guard try isSettableForSetValue(element: target.element, attribute: kAXValueAttribute) else {
            throw ComputerUseError.message("[input.not_writable] The target text value is not writable")
        }
        target.selection = nil
        invalidateSnapshot(snapshot)
        let error = AXUIElementSetAttributeValue(target.element, kAXValueAttribute as CFString, value as CFString)
        debugClickDecision("input delivery tool=set_value observation=\(snapshot.observationID) pid=\(snapshot.app.pid) target=\(diagnosticElementDescription(target.element)) submitted_length=\((value as NSString).length) result=\(error.rawValue)")
        guard error == .success else { return inputDeliveryFailure("AXValue returned \(error.rawValue); do not automatically replay") }
        let result = try verifiedInputResult(element: target.element, expected: value, query: query, timeout: verificationTimeout)
        if result.inputResult["verification"] == "value_verified" {
            target.value = value
            target.selection = CFRange(location: (value as NSString).length, length: 0)
        }
        return result
    }

    private func inputElement(snapshot: AppSnapshot, index: String) throws -> AXUIElement {
        let record: ElementRecord
        do { record = try lookupElement(snapshot: snapshot, index: index) }
        catch { throw ComputerUseError.message("[input.target_invalid] The requested index is not in the current observation") }
        guard let element = record.element else {
            throw ComputerUseError.message("[input.target_invalid] The target has no live accessibility element")
        }
        try validateInputElement(element, snapshot: snapshot)
        return element
    }

    private func validateInputElement(_ element: AXUIElement, snapshot: AppSnapshot) throws {
        try validateElementIdentity(element, snapshot: snapshot, requireWindow: true)
        guard let role = stringValue(of: element, attribute: kAXRoleAttribute),
              [kAXTextFieldRole as String, kAXTextAreaRole as String, "AXTextView"].contains(role) else {
            throw ComputerUseError.message("[input.unsupported] The target is not an editable text control")
        }
    }

    private func validateBackgroundKeyboard(target: InputTarget, snapshot: AppSnapshot) throws {
        try validateSnapshotWindow(snapshot)
        try validateInputTarget(target, snapshot: snapshot)
        // PID events address an app, not an AX element. Require evidence of its local receiver.
        let receiver = copyElement(AXUIElementCreateApplication(snapshot.app.pid), attribute: kAXFocusedUIElementAttribute)
        guard let receiver, CFEqual(receiver, target.element) else {
            throw ComputerUseError.message("[input.background_unsupported] The application does not expose the bound control as its keyboard receiver. Use direct text/semantic actions; no activation or key delivery was performed.")
        }
    }

    private func invalidateSnapshot(_ snapshot: AppSnapshot) {
        retireObservation(snapshot.observationID)
    }

    private func inputDeliveryFailure(_ message: String) -> ToolCallResult {
        ToolCallResult(content: [.text("[input.write_failed] " + message)], isError: true,
                       inputResult: ["delivery": "unknown", "verification": "unconfirmed"])
    }

    private func inputText(_ element: AXUIElement) throws -> String {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXValueAttribute as CFString, &value) == .success,
              let text = value as? String else {
            throw ComputerUseError.message("[input.verification_unavailable] Cannot read the target's full text value")
        }
        return text
    }

    private func verifiedInputResult(element: AXUIElement, expected: String, query: String, timeout: TimeInterval?) throws -> ToolCallResult {
        // A configurable read-only deadline allows asynchronous accessibility updates.
        let policy = InputVerificationPolicy(timeout: timeout)
        let deadline = ProcessInfo.processInfo.systemUptime + policy.timeout
        var matched = false
        var lastLength: Int?
        repeat {
            if let actual = try? inputText(element) {
                lastLength = (actual as NSString).length
                matched = actual == expected
                if matched { break }
            } else {
                lastLength = nil
            }
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            if remaining <= 0 { break }
            Thread.sleep(forTimeInterval: min(policy.pollInterval, remaining))
        } while true
        debugClickDecision("input verification expected_length=\((expected as NSString).length) actual_length=\(String(describing: lastLength)) exact_match=\(matched)")
        guard matched else {
            return ToolCallResult(
                content: [.text("[input.verification_unconfirmed] The write returned success, but read-only verification did not confirm the expected text. Effects may have occurred. Run get_app_state; do not automatically replay.")],
                isError: true,
                inputResult: ["delivery": "returned_success", "verification": "unconfirmed",
                              "reason": lastLength == nil ? "unreadable" : "readback_mismatch"]
            )
        }
        do {
            let result = snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
            return ToolCallResult(
                content: result.content + [.text("Input result: value_verified. Text readback matched; application-level effects are not verified.")],
                inputResult: ["delivery": "returned_success", "verification": "value_verified"]
            )
        } catch {
            return ToolCallResult(
                content: [.text("[observation.unavailable] Text readback matched, but the next observation is unavailable. Do not replay the input; obtain a new state.")],
                isError: true,
                inputResult: ["delivery": "returned_success", "verification": "value_verified"]
            )
        }
    }

    func validateObservation(app query: String, observationID: String) throws {
        let snapshot = try currentSnapshot(for: query)
        guard snapshot.observationID == observationID else {
            throw ComputerUseError.message("[observation.stale] The observation has been replaced. Run get_app_state and choose the target again.")
        }
        try validateSnapshotWindow(snapshot)
    }

    func retireObservation(_ observationID: String) {
        snapshotsByApp = snapshotsByApp.filter { $0.value.observationID != observationID }
    }

    private func currentSnapshot(for query: String) throws -> AppSnapshot {
        guard let snapshot = snapshotsByApp[query.lowercased()] else {
            throw ComputerUseError.message("[observation.required] Run get_app_state before acting.")
        }
        return snapshot
    }

    private func validateSnapshotWindow(_ snapshot: AppSnapshot) throws {
        if snapshot.mode == .fixture { return }
        guard let id = snapshot.targetWindowID, let expected = snapshot.windowBounds,
              let entries = CGWindowListCopyWindowInfo(.optionIncludingWindow, id) as? [[String: Any]],
              let info = entries.first,
              let owner = info[kCGWindowOwnerPID as String] as? NSNumber,
              owner.int32Value == snapshot.app.pid,
              let bounds = info[kCGWindowBounds as String] as? NSDictionary,
              let current = CGRect(dictionaryRepresentation: bounds), current == expected,
              (info[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue == true else {
            throw ComputerUseError.message("[observation.stale] The observed window is unavailable or its geometry changed. Run get_app_state again.")
        }
    }

    private func validateElementIdentity(_ element: AXUIElement?, snapshot: AppSnapshot, requireWindow: Bool) throws {
        guard let element else {
            throw ComputerUseError.message("[input.target_invalid] No live accessibility element is available")
        }
        var pid: pid_t = 0
        guard AXUIElementGetPid(element, &pid) == .success, pid == snapshot.app.pid else {
            throw ComputerUseError.message("[input.target_invalid] Target process mismatch (expected pid=\(snapshot.app.pid), actual pid=\(pid))")
        }
        let window = copyElement(element, attribute: kAXWindowAttribute)
            ?? (stringValue(of: element, attribute: kAXRoleAttribute) == kAXWindowRole as String ? element : nil)
        if let window {
            guard let expected = snapshot.windowElement, CFEqual(window, expected) else {
                throw ComputerUseError.message("[input.target_invalid] The target belongs to another window")
            }
        } else if requireWindow {
            var node: AXUIElement? = element
            var visited: [AXUIElement] = []
            while let current = node, !visited.contains(where: { CFEqual($0, current) }) {
                if let expected = snapshot.windowElement, CFEqual(current, expected) { return }
                visited.append(current)
                node = copyParent(of: current)
            }
            throw ComputerUseError.message("[input.target_invalid] The target is not in the observed window")
        }
    }

    private func pointerPoint(for record: ElementRecord, snapshot: AppSnapshot) throws -> CGPoint {
        try validateSnapshotWindow(snapshot)
        try validateElementIdentity(record.element, snapshot: snapshot, requireWindow: true)
        guard let frame = record.localFrame, frame.width > 0, frame.height > 0,
              let bounds = snapshot.windowBounds, let element = record.element,
              localFrame(of: element, windowBounds: bounds) == frame,
              CGRect(origin: .zero, size: bounds.size).contains(CGPoint(x: frame.midX, y: frame.midY)) else {
            throw ComputerUseError.message("[observation.stale] The target has no current visible pointer location. Observe again or use an explicit accessibility action.")
        }
        return CGPoint(x: frame.midX, y: frame.midY)
    }

    private func dispatchPointerClick(method: ClickMethod, point: CGPoint, windowPoint: CGPoint,
                                      button: MouseButtonKind, clickCount: Int, snapshot: AppSnapshot,
                                      targetDescription: String) throws {
        try validateSnapshotWindow(snapshot)
        let cursor = makeVisualCursorTarget(at: point, targetWindowID: snapshot.targetWindowID,
                                            targetWindowLayer: snapshot.targetWindowLayer)
        moveVisualCursor(to: cursor)
        do {
            if method == .auto {
                try performNonAXClickFallback(at: point, button: button, clickCount: clickCount,
                                              targetDescription: targetDescription, snapshot: snapshot)
            } else {
                try performExplicitMouseClick(method: method, at: point, windowPoint: windowPoint,
                                              button: button, clickCount: clickCount,
                                              targetDescription: targetDescription, snapshot: snapshot)
            }
        } catch {
            settleVisualCursor(at: cursor)
            throw error
        }
        pulseVisualCursor(at: cursor, clickCount: clickCount, mouseButton: button)
    }

    @discardableResult
    private func refreshSnapshot(
        for query: String,
        textLimit: SnapshotTextLimit = .defaults,
        treeLimits: AccessibilityTreeLimits = .defaults,
        recoveryPolicy: SnapshotRecoveryPolicy = .readOnly
    ) throws -> AppSnapshot {
        let app = try AppDiscovery.resolve(query)
        let snapshot = try SnapshotBuilder.build(
            for: app,
            textLimit: textLimit,
            treeLimits: treeLimits,
            recoveryPolicy: recoveryPolicy
        )

        let keys = Set([
            query.lowercased(),
            app.name.lowercased(),
            (app.bundleIdentifier ?? "").lowercased(),
        ].filter { !$0.isEmpty })

        for key in keys {
            snapshotsByApp[key] = snapshot
        }

        return snapshot
    }

    private func lookupElement(snapshot: AppSnapshot, index: String) throws -> ElementRecord {
        guard let parsedIndex = Int(index), let record = snapshot.elements[parsedIndex] else {
            throw ComputerUseError.invalidArguments("unknown element_index '\(index)'")
        }

        return record
    }

    private func matchingAction(requested: String, record: ElementRecord) -> String? {
        if let exact = record.rawActions.first(where: { $0.caseInsensitiveCompare(requested) == .orderedSame }) {
            return exact
        }

        if let pretty = zip(record.rawActions, record.prettyActions).first(where: { $0.1.caseInsensitiveCompare(requested) == .orderedSame }) {
            return pretty.0
        }

        return nil
    }

    private func invalidSecondaryActionMessage(action: String, record: ElementRecord) -> String {
        invalidSecondaryActionErrorMessage(action: action, elementIndex: record.index)
    }

    private func performPreferredClick(on record: ElementRecord, button: MouseButtonKind, clickCount: Int) throws -> Bool {
        guard let element = record.element else {
            return false
        }

        switch button {
        case .left:
            if try performAction(named: kAXPressAction as String, on: element, availableActions: record.rawActions, repeatCount: clickCount) {
                debugClickDecision("dispatch action=AXPress source=preferred target={\(diagnosticElementDescription(element))}")
                return true
            }

            if try performAction(named: kAXConfirmAction as String, on: element, availableActions: record.rawActions, repeatCount: clickCount) {
                debugClickDecision("dispatch action=AXConfirm source=preferred target={\(diagnosticElementDescription(element))}")
                return true
            }

            if try performAction(named: "AXOpen", on: element, availableActions: record.rawActions, repeatCount: clickCount) {
                debugClickDecision("dispatch action=AXOpen source=preferred target={\(diagnosticElementDescription(element))}")
                return true
            }
        case .right:
            if try performAction(named: kAXShowMenuAction as String, on: element, availableActions: record.rawActions, repeatCount: clickCount) {
                debugClickDecision("dispatch action=AXShowMenu source=preferred target={\(diagnosticElementDescription(element))}")
                return true
            }
        case .middle:
            break
        }

        return false
    }

    private func clickCandidates(at windowPoint: CGPoint, in snapshot: AppSnapshot) throws -> [ElementRecord] {
        let screenPoint = try windowPointToGlobalPoint(snapshot: snapshot, point: windowPoint)
        let hit = hitTestElement(atScreenPoint: screenPoint, in: snapshot)
        let observed = bestElement(containing: windowPoint, in: snapshot)
        return [hit, observed].compactMap { $0 }.filter { record in
            guard let frame = record.localFrame, frame.width > 0, frame.height > 0,
                  frame.contains(windowPoint),
                  let element = record.element,
                  localFrame(of: element, windowBounds: snapshot.windowBounds) == frame,
                  (try? validateElementIdentity(record.element, snapshot: snapshot, requireWindow: true)) != nil else {
                debugClickDecision("rejected off-target candidate \(clickDebugDescription(record))")
                return false
            }
            return true
        }.reduce(into: []) { candidates, record in
            if !candidates.contains(where: { sameElement($0.element, record.element) }) {
                candidates.append(record)
            }
        }
    }

    private func sameElement(_ lhs: AXUIElement?, _ rhs: AXUIElement?) -> Bool {
        guard let lhs, let rhs else {
            return false
        }

        return CFEqual(lhs, rhs)
    }

    private func performAction(named action: String, on element: AXUIElement, availableActions: [String], repeatCount: Int = 1) throws -> Bool {
        guard availableActions.contains(where: { $0.caseInsensitiveCompare(action) == .orderedSame }) else {
            return false
        }

        let attempts = max(repeatCount, 1)
        for index in 0..<attempts {
            let result = AXUIElementPerformAction(element, action as CFString)
            switch result {
            case .success:
                if index < attempts - 1 {
                    Thread.sleep(forTimeInterval: 0.05)
                }
            case .actionUnsupported, .attributeUnsupported:
                if index > 0 {
                    throw ComputerUseError.message("[click.unconfirmed] An earlier click was delivered; do not automatically replay.")
                }
                return false
            default:
                throw ComputerUseError.message("AXUIElementPerformAction(\(action)) failed with \(result.rawValue)")
            }
        }

        return true
    }

    private func isSettable(element: AXUIElement, attribute: String) -> Bool {
        var settable: DarwinBoolean = false
        let result = AXUIElementIsAttributeSettable(element, attribute as CFString, &settable)
        return result == .success && settable.boolValue
    }

    private func isSettableForSetValue(element: AXUIElement, attribute: String) throws -> Bool {
        var settable = DarwinBoolean(false)
        let result = AXUIElementIsAttributeSettable(element, attribute as CFString, &settable)
        return try setValueAttributeIsSettable(
            result: result,
            settable: settable.boolValue,
            attribute: attribute
        )
    }

    private func bestElement(containing point: CGPoint, in snapshot: AppSnapshot) -> ElementRecord? {
        snapshot.elements.values
            .filter { $0.localFrame?.contains(point) ?? false }
            .sorted { lhs, rhs in
                let lhsPriority = clickPriority(for: lhs)
                let rhsPriority = clickPriority(for: rhs)
                if lhsPriority != rhsPriority {
                    return lhsPriority < rhsPriority
                }

                return frameArea(of: lhs) < frameArea(of: rhs)
            }
            .first
    }

    private func hitTestElement(atScreenPoint globalPoint: CGPoint, in snapshot: AppSnapshot) -> ElementRecord? {
        let appElement = AXUIElementCreateApplication(snapshot.app.pid)
        var hitElement: AXUIElement?
        let result = AXUIElementCopyElementAtPosition(appElement, Float(globalPoint.x), Float(globalPoint.y), &hitElement)
        guard result == .success, let hitElement else {
            return nil
        }

        let rawActions = copyActions(for: hitElement) ?? []
        return ElementRecord(
            index: -1,
            identifier: nil,
            element: hitElement,
            localFrame: localFrame(of: hitElement, windowBounds: snapshot.windowBounds),
            rawActions: rawActions,
            prettyActions: rawActions
        )
    }

    private func clickPriority(for record: ElementRecord) -> Int {
        if record.rawActions.contains(where: {
            $0.caseInsensitiveCompare(kAXPressAction as String) == .orderedSame ||
            $0.caseInsensitiveCompare(kAXConfirmAction as String) == .orderedSame ||
            $0.caseInsensitiveCompare(kAXShowMenuAction as String) == .orderedSame ||
            $0.caseInsensitiveCompare(kAXRaiseAction as String) == .orderedSame
        }) {
            return 0
        }

        if let element = record.element,
           isSettable(element: element, attribute: kAXMainAttribute) ||
           isSettable(element: element, attribute: kAXFocusedAttribute) {
            return 1
        }

        return 2
    }

    private func frameArea(of record: ElementRecord) -> CGFloat {
        guard let frame = record.localFrame else {
            return .greatestFiniteMagnitude
        }

        return frame.width * frame.height
    }

    private func copyActions(for element: AXUIElement) -> [String]? {
        var actions: CFArray?
        let result = AXUIElementCopyActionNames(element, &actions)
        guard result == .success else {
            return nil
        }

        return actions as? [String]
    }

    private func copyParent(of element: AXUIElement) -> AXUIElement? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, kAXParentAttribute as CFString, &value)
        guard result == .success, let value else {
            return nil
        }

        return (value as! AXUIElement)
    }

    private func stringValue(of element: AXUIElement, attribute: String) -> String? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        guard result == .success, let value else {
            return nil
        }

        return value as? String
    }

    private func localFrame(of element: AXUIElement, windowBounds: CGRect?) -> CGRect? {
        var positionValue: CFTypeRef?
        var sizeValue: CFTypeRef?
        let positionResult = AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &positionValue)
        let sizeResult = AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &sizeValue)

        guard
            positionResult == .success,
            sizeResult == .success,
            let positionValue,
            let sizeValue
        else {
            return nil
        }

        let positionAXValue = positionValue as! AXValue
        let sizeAXValue = sizeValue as! AXValue
        var position = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(positionAXValue, .cgPoint, &position), AXValueGetValue(sizeAXValue, .cgSize, &size) else {
            return nil
        }

        let frame = CGRect(origin: position, size: size)
        guard let windowBounds else {
            return frame
        }

        return windowRelativeFrame(elementFrame: frame, windowBounds: windowBounds)
    }

    private func globalPoint(for record: ElementRecord, snapshot: AppSnapshot) throws -> CGPoint? {
        let point = try pointerPoint(for: record, snapshot: snapshot)
        return try windowPointToGlobalPoint(snapshot: snapshot, point: point)
    }

    private func screenshotToGlobalPoint(snapshot: AppSnapshot, x: Double, y: Double) throws -> CGPoint {
        try windowPointToGlobalPoint(
            snapshot: snapshot,
            point: screenshotPixelToWindowPointInSnapshot(
                snapshot: snapshot,
                point: CGPoint(x: x, y: y)
            )
        )
    }

    private func screenshotPixelToWindowPointInSnapshot(snapshot: AppSnapshot, point: CGPoint) -> CGPoint {
        screenshotPixelToWindowPoint(
            point,
            screenshotPixelSize: screenshotPixelSize(snapshot: snapshot),
            windowBounds: snapshot.windowBounds
        )
    }

    private func screenshotPixelSize(snapshot: AppSnapshot) -> CGSize? {
        guard
            let screenshotPNGData = snapshot.screenshotPNGData,
            let imageSource = CGImageSourceCreateWithData(screenshotPNGData as CFData, nil),
            let properties = CGImageSourceCopyPropertiesAtIndex(imageSource, 0, nil) as? [CFString: Any],
            let pixelWidth = properties[kCGImagePropertyPixelWidth] as? CGFloat,
            let pixelHeight = properties[kCGImagePropertyPixelHeight] as? CGFloat,
            pixelWidth > 0,
            pixelHeight > 0
        else {
            return nil
        }

        return CGSize(width: pixelWidth, height: pixelHeight)
    }

    private func windowPointToGlobalPoint(snapshot: AppSnapshot, point: CGPoint) throws -> CGPoint {
        guard let windowBounds = snapshot.windowBounds else {
            let appReference = snapshot.app.bundleIdentifier ?? snapshot.app.name
            throw ComputerUseError.stateUnavailable("No window bounds are available for \(appReference). Run get_app_state after bringing the app on screen.")
        }

        return CGPoint(x: windowBounds.minX + point.x, y: windowBounds.minY + point.y)
    }

    private func fixtureIdentifier(at point: CGPoint, snapshot: AppSnapshot) throws -> String {
        let candidates = snapshot.elements.values
            .filter { $0.identifier != nil && ($0.localFrame?.contains(point) ?? false) }
            .sorted { lhs, rhs in
                let lhsArea = (lhs.localFrame?.width ?? 0) * (lhs.localFrame?.height ?? 0)
                let rhsArea = (rhs.localFrame?.width ?? 0) * (rhs.localFrame?.height ?? 0)
                return lhsArea < rhsArea
            }

        guard let identifier = candidates.first?.identifier else {
            throw ComputerUseError.invalidArguments("No fixture element contains coordinate (\(Int(point.x)), \(Int(point.y)))")
        }

        return identifier
    }

    private func visualCursorTarget(for record: ElementRecord, snapshot: AppSnapshot) -> VisualCursorTarget? {
        makeVisualCursorTarget(
            localFrame: record.localFrame,
            windowBounds: snapshot.windowBounds,
            targetWindowID: snapshot.targetWindowID,
            targetWindowLayer: snapshot.targetWindowLayer
        )
    }

    private func fixtureVisualCursorTarget(identifier: String, snapshot: AppSnapshot) -> VisualCursorTarget? {
        let record = snapshot.elements.values.first { $0.identifier == identifier }
        return record.flatMap { visualCursorTarget(for: $0, snapshot: snapshot) }
    }

    private func moveVisualCursor(to target: VisualCursorTarget?) {
        guard let target else {
            return
        }

        VisualCursorSupport.performOnMain {
            SoftwareCursorOverlay.moveCursor(to: target.point, in: target.window)
        }
    }

    private func settleVisualCursor(at target: VisualCursorTarget?) {
        guard let target else {
            return
        }

        VisualCursorSupport.performOnMain {
            SoftwareCursorOverlay.settle(at: target.point, in: target.window)
        }
    }

    private func pulseVisualCursor(at target: VisualCursorTarget?, clickCount: Int, mouseButton: MouseButtonKind) {
        guard let target else {
            return
        }

        VisualCursorSupport.performOnMain {
            SoftwareCursorOverlay.pulseClick(
                at: target.point,
                clickCount: clickCount,
                mouseButton: mouseButton,
                in: target.window
            )
        }
    }

    private func debugInputFallback(tool: String, targetDescription: String, snapshot: AppSnapshot) {
        guard inputFallbackDebugEnabled(environment: ProcessInfo.processInfo.environment) else {
            return
        }

        let appReference = snapshot.app.bundleIdentifier ?? snapshot.app.name
        fputs(
            "[open-computer-use] global pointer fallback tool=\(tool) app=\(appReference) target=\(targetDescription)\n",
            stderr
        )
    }

    private func debugClickDecision(_ message: String) {
        diagnostics.append(message)
        guard inputFallbackDebugEnabled(environment: ProcessInfo.processInfo.environment) else {
            return
        }

        fputs("[open-computer-use] click decision \(message)\n", stderr)
    }

    private func traceRuntimeContext(stage: String, snapshot: AppSnapshot) {
        let frontmost = NSWorkspace.shared.frontmostApplication
        let frontmostDescription = frontmost.map {
            "pid=\($0.processIdentifier) bundle=\($0.bundleIdentifier ?? "nil") name=\(diagnosticScalar($0.localizedName))"
        } ?? "nil"
        let system = AXUIElementCreateSystemWide()
        let focused = copyElement(system, attribute: kAXFocusedUIElementAttribute)
        debugClickDecision(
            "runtime stage=\(stage) observation=\(snapshot.observationID) expected_pid=\(snapshot.app.pid) snapshot_window=\(String(describing: snapshot.targetWindowID)) frontmost={\(frontmostDescription)} focused={\(diagnosticElementDescription(focused))}"
        )
    }

    private func diagnosticPoint(_ point: CGPoint) -> String {
        "(\(String(format: "%.2f", point.x)),\(String(format: "%.2f", point.y)))"
    }

    private func diagnosticPoint(x: Double?, y: Double?) -> String {
        guard let x, let y else { return "nil" }
        return diagnosticPoint(CGPoint(x: x, y: y))
    }

    private func diagnosticScalar(_ value: String?) -> String {
        guard let value else { return "nil" }
        let singleLine = value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\n", with: "\\n")
            .replacingOccurrences(of: "\r", with: "\\r")
        return String(singleLine.prefix(160))
    }

    private func diagnosticElementDescription(_ element: AXUIElement?) -> String {
        guard let element else { return "nil" }
        var pid: pid_t = 0
        let pidResult = AXUIElementGetPid(element, &pid)
        let role = diagnosticScalar(stringValue(of: element, attribute: kAXRoleAttribute))
        let subrole = diagnosticScalar(stringValue(of: element, attribute: kAXSubroleAttribute))
        let identifier = diagnosticScalar(stringValue(of: element, attribute: kAXIdentifierAttribute))
        let title = diagnosticScalar(stringValue(of: element, attribute: kAXTitleAttribute))
        let ancestry = diagnosticAncestorPath(from: element)
        return "pid=\(pidResult == .success ? String(pid) : "unavailable") role=\(role) subrole=\(subrole) identifier=\(identifier) title=\(title) ancestors=[\(ancestry)]"
    }

    private func diagnosticAncestorPath(from element: AXUIElement) -> String {
        var current = element
        var path: [String] = []
        for _ in 0..<8 {
            guard let parent = copyParent(of: current), !CFEqual(parent, current) else { break }
            let role = diagnosticScalar(stringValue(of: parent, attribute: kAXRoleAttribute))
            let title = diagnosticScalar(stringValue(of: parent, attribute: kAXTitleAttribute))
            path.append("\(role):\(title)")
            current = parent
        }
        return path.joined(separator: ">")
    }

    private func clickDebugDescription(_ record: ElementRecord) -> String {
        let actions = record.rawActions.joined(separator: ",")
        let frame = record.localFrame.map { "x=\(Int($0.minX)) y=\(Int($0.minY)) w=\(Int($0.width)) h=\(Int($0.height))" } ?? "nil"
        return "index=\(record.index) synthetic=\(record.isSyntheticText) actions=[\(actions)] frame=\(frame) element={\(diagnosticElementDescription(record.element))}"
    }

    private func integralScrollPageCount(_ pages: Double) -> Int? {
        let rounded = pages.rounded(.toNearestOrAwayFromZero)
        guard abs(pages - rounded) < 0.000001 else {
            return nil
        }
        return max(Int(rounded), 1)
    }

    private func performScrollEvent(
        at point: CGPoint,
        direction: String,
        pages: Double,
        targetDescription: String,
        snapshot: AppSnapshot
    ) throws {
        let eventPoint = inputEventPoint(fromScreenStatePoint: point)

        if globalPointerFallbacksEnabled(environment: ProcessInfo.processInfo.environment) {
            debugInputFallback(
                tool: "scroll",
                targetDescription: targetDescription,
                snapshot: snapshot
            )
            InputSimulation.prepareAppForGlobalPointerInput(snapshot.app)
            try InputSimulation.scrollGlobally(at: eventPoint, direction: direction, pages: pages)
            return
        }

        try InputSimulation.scrollTargeted(at: eventPoint, direction: direction, pages: pages, pid: snapshot.app.pid)
    }

    private func performDragEvent(
        from start: CGPoint,
        to end: CGPoint,
        targetDescription: String,
        snapshot: AppSnapshot
    ) throws {
        let eventStart = inputEventPoint(fromScreenStatePoint: start)
        let eventEnd = inputEventPoint(fromScreenStatePoint: end)

        if globalPointerFallbacksEnabled(environment: ProcessInfo.processInfo.environment) {
            debugInputFallback(
                tool: "drag",
                targetDescription: targetDescription,
                snapshot: snapshot
            )
            InputSimulation.prepareAppForGlobalPointerInput(snapshot.app)
            try InputSimulation.dragGlobally(from: eventStart, to: eventEnd)
            return
        }

        try InputSimulation.dragTargeted(from: eventStart, to: eventEnd, pid: snapshot.app.pid)
    }

    private func performNonAXClickFallback(
        at point: CGPoint,
        button: MouseButtonKind,
        clickCount: Int,
        targetDescription: String,
        snapshot: AppSnapshot
    ) throws {
        let eventPoint = inputEventPoint(fromScreenStatePoint: point)
        debugClickDecision("mouse_fallback method=pid_post pid=\(snapshot.app.pid) window=\(String(describing: snapshot.targetWindowID)) eventPoint=\(eventPoint)")
        try InputSimulation.clickTargeted(at: eventPoint, button: button, clickCount: clickCount, pid: snapshot.app.pid)
    }

    private func performExplicitMouseClick(
        method: ClickMethod,
        at point: CGPoint,
        windowPoint: CGPoint,
        button: MouseButtonKind,
        clickCount: Int,
        targetDescription: String,
        snapshot: AppSnapshot
    ) throws {
        let eventPoint = inputEventPoint(fromScreenStatePoint: point)
        debugClickDecision("explicit_mouse pid=\(snapshot.app.pid) method=\(method.rawValue) eventPoint=\(eventPoint) windowPoint=\(windowPoint)")

        switch method {
        case .appPost:
            debugClickDecision("requested=app_post executed=pid_post target=\(targetDescription)")
            try InputSimulation.clickTargeted(
                at: eventPoint,
                button: button,
                clickCount: clickCount,
                pid: snapshot.app.pid
            )
        case .skyClick:
            guard let windowBounds = snapshot.windowBounds, let windowID = snapshot.targetWindowID else {
                throw ComputerUseError.stateUnavailable(
                    "click_method 'sky_click' requires a current on-screen target window. Run get_app_state again."
                )
            }
            debugClickDecision("requested=sky_click executed=skylight_pid_post target=\(targetDescription)")
            try InputSimulation.clickWithSkyLight(
                at: eventPoint,
                windowPoint: windowPoint,
                windowBounds: windowBounds,
                windowID: windowID,
                clickCount: clickCount,
                pid: snapshot.app.pid
            )
        case .global:
            guard globalPointerFallbacksEnabled(environment: ProcessInfo.processInfo.environment) else {
                throw ComputerUseError.message(
                    "click_method 'global' requires OPEN_COMPUTER_USE_ALLOW_GLOBAL_POINTER_FALLBACKS=1 because it may move the system pointer and change foreground focus"
                )
            }
            debugClickDecision("requested=global executed=global_hid target=\(targetDescription)")
            InputSimulation.prepareAppForGlobalPointerInput(snapshot.app)
            try InputSimulation.clickGlobally(at: eventPoint, button: button, clickCount: clickCount)
        case .auto, .accessibility:
            throw ComputerUseError.message(
                "click_method '\(method.rawValue)' is not a direct mouse event method"
            )
        }
    }

    private func snapshotResult(for snapshot: AppSnapshot, style: SnapshotTextStyle) -> ToolCallResult {
        var content = [ToolResultContentItem.text(snapshot.renderedText(style: style))]
        if let screenshotPNGData = snapshot.screenshotPNGData {
            content.append(.pngImage(screenshotPNGData))
        }
        return ToolCallResult(content: content)
    }
}
