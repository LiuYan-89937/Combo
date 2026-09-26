import AppKit
import ApplicationServices
import Foundation

struct VisualCursorTarget: Equatable {
    let point: CGPoint
    let window: CursorTargetWindow?
}

private enum ScrollTarget {
    case element(String)
    case screenshotPoint(x: Double, y: Double)

    init(elementIndex: String?, x: Double?, y: Double?) throws {
        switch (elementIndex, x, y) {
        case let (.some(index), nil, nil):
            self = .element(index)
        case let (nil, .some(x), .some(y)):
            self = .screenshotPoint(x: x, y: y)
        default:
            throw ComputerUseError.invalidArguments("scroll requires exactly one target: element_index or both screenshot coordinates x and y")
        }
    }
}

public enum ClickMethod: String, CaseIterable, Sendable {
    case auto
    case accessibility
    case skyClick = "sky_click"
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
    hasElementIndex: Bool
) throws {
    if method == .accessibility, !hasElementIndex {
        throw ComputerUseError.message("click_method 'accessibility' requires element_index")
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
            hasElementIndex: elementIndex != nil
        )
        try validateSkyClickArguments(
            method: clickMethod,
            mouseButton: mouseButton,
            clickCount: clickCount
        )

        let snapshot = try currentSnapshot(for: query)
        debugClickDecision("request observation=\(snapshot.observationID) pid=\(snapshot.app.pid) window=\(String(describing: snapshot.targetWindowID)) bounds=\(String(describing: snapshot.windowBounds)) screenshotPixels=\(String(describing: snapshot.screenshotPixelSize)) method=\(clickMethod.rawValue) element=\(elementIndex ?? "nil") screenshotPoint=\(diagnosticPoint(x: x, y: y)) button=\(mouseButton) count=\(clickCount)")
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
            return postActionResult(for: query)
        }

        try validateSnapshotWindow(snapshot)
        if let elementIndex {
            let record = try lookupElement(snapshot: snapshot, index: elementIndex)
            try validateElementIdentity(record.element, snapshot: snapshot, requireWindow: true)
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
                    return postActionResult(for: query)
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
            try snapshot.validateScreenshotPoint(screenshotPoint)
            let windowPoint = screenshotPixelToWindowPointInSnapshot(snapshot: snapshot, point: screenshotPoint)
            let targetPoint = try windowPointToGlobalPoint(snapshot: snapshot, point: windowPoint)
            let candidates = try clickCandidates(at: windowPoint, in: snapshot)
            debugClickDecision("mapping observation=\(snapshot.observationID) screenshotPoint=\(diagnosticPoint(screenshotPoint)) windowPoint=\(diagnosticPoint(windowPoint)) globalPoint=\(diagnosticPoint(targetPoint)) candidates=\(candidates.map(clickDebugDescription).joined(separator: " || "))")
            var handled = false
            if clickMethod == .auto {
                for record in candidates {
                    try validateElementIdentity(record.element, snapshot: snapshot, requireWindow: true)
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

        return postActionResult(for: query, recoveryPolicy: .readOnly)
    }

    public func performSecondaryAction(app query: String, elementIndex: String, action: String) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let record = try lookupElement(snapshot: snapshot, index: elementIndex)
        try validateElementIdentity(record.element, snapshot: snapshot, requireWindow: true)

        if snapshot.mode == .fixture {
            guard action.caseInsensitiveCompare("Raise") == .orderedSame else {
                throw ComputerUseError.message(invalidSecondaryActionMessage(action: action, record: record))
            }

            return postActionResult(for: query)
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
        return postActionResult(for: query)
    }

    public func scroll(
        app query: String,
        direction: String,
        elementIndex: String?,
        x: Double?,
        y: Double?,
        pages: Double
    ) throws -> ToolCallResult {
        let normalized = direction.lowercased()
        guard ["up", "down", "left", "right"].contains(normalized) else {
            throw ComputerUseError.message("Invalid scroll direction: \(direction)")
        }
        guard pages.isFinite, pages > 0 else {
            throw ComputerUseError.message("pages must be > 0")
        }

        let snapshot = try currentSnapshot(for: query)
        let target = try ScrollTarget(elementIndex: elementIndex, x: x, y: y)

        if snapshot.mode == .fixture {
            switch target {
            case let .element(index):
                let record = try lookupElement(snapshot: snapshot, index: index)
                guard let identifier = record.identifier else {
                    throw ComputerUseError.invalidArguments("fixture scroll requires an identifier-backed element")
                }
                try FixtureBridge.post(FixtureCommand(kind: "scroll", identifier: identifier, direction: normalized, pages: pages))
            case let .screenshotPoint(x, y):
                let identifier = try fixtureIdentifier(at: CGPoint(x: x, y: y), snapshot: snapshot)
                try FixtureBridge.post(FixtureCommand(kind: "scroll", identifier: identifier, x: x, y: y, direction: normalized, pages: pages))
            }
            Thread.sleep(forTimeInterval: 0.15)
            return postActionResult(for: query)
        }

        switch target {
        case let .element(index):
            let record = try lookupElement(snapshot: snapshot, index: index)
            try validateElementIdentity(record.element, snapshot: snapshot, requireWindow: true)
            if let repeatCount = integralScrollPageCount(pages),
               let rawAction = record.rawActions.first(where: { $0.caseInsensitiveCompare("AXScroll\(normalized.capitalized)ByPage") == .orderedSame }),
               let element = record.element {
                for _ in 0..<repeatCount {
                    try validateElementIdentity(element, snapshot: snapshot, requireWindow: true)
                    let result = AXUIElementPerformAction(element, rawAction as CFString)
                    guard result == .success else {
                        throw ComputerUseError.message("[scroll.unsupported] Window scroll action failed with \(result.rawValue)")
                    }
                    Thread.sleep(forTimeInterval: 0.05)
                }
            } else if let point = try globalPoint(for: record, snapshot: snapshot) {
                try performScrollEvent(
                    at: point,
                    direction: normalized,
                    pages: pages,
                    targetDescription: "element_index=\(index)",
                    snapshot: snapshot
                )
            } else {
                throw ComputerUseError.stateUnavailable("element \(index) has no scrollable frame")
            }
        case let .screenshotPoint(x, y):
            let point = try screenshotToGlobalPoint(snapshot: snapshot, x: x, y: y)
            try performScrollEvent(
                at: point,
                direction: normalized,
                pages: pages,
                targetDescription: "screenshot_point=(\(Int(x)), \(Int(y)))",
                snapshot: snapshot
            )
        }

        return postActionResult(for: query)
    }

    public func drag(app query: String, fromX: Double, fromY: Double, toX: Double, toY: Double) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        if snapshot.mode == .fixture {
            try FixtureBridge.post(FixtureCommand(kind: "drag", identifier: "fixture-drag-pad", x: fromX, y: fromY, toX: toX, toY: toY))
            Thread.sleep(forTimeInterval: 0.15)
            return postActionResult(for: query)
        }

        let start = try screenshotToGlobalPoint(snapshot: snapshot, x: fromX, y: fromY)
        let end = try screenshotToGlobalPoint(snapshot: snapshot, x: toX, y: toY)
        try performDragEvent(
            from: start,
            to: end,
            targetDescription: "from=(\(Int(fromX)), \(Int(fromY))) to=(\(Int(toX)), \(Int(toY)))",
            snapshot: snapshot
        )
        return postActionResult(for: query)
    }

    public func setInputTarget(app query: String, elementIndex: String? = nil, x: Double? = nil, y: Double? = nil) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target: InputTarget
        if let elementIndex {
            guard x == nil && y == nil else {
                throw ComputerUseError.invalidArguments("Choose element_index or x/y, not both")
            }
            target = try bindInputTarget(snapshot: snapshot, index: elementIndex)
        } else {
            guard let x, let y, let window = snapshot.windowElement else {
                throw ComputerUseError.invalidArguments("Provide element_index or both screenshot coordinates x and y")
            }
            let point = try screenshotToGlobalPoint(snapshot: snapshot, x: x, y: y)
            target = InputTarget(receiver: .windowPoint(point), window: window,
                                 windowID: snapshot.targetWindowID, windowBounds: snapshot.windowBounds)
        }
        try establishInputTarget(target, snapshot: snapshot)
        let refreshed = try refreshSnapshot(for: query)
        try validateInputTarget(target, snapshot: refreshed)
        inputTargets[snapshot.app.pid] = target
        debugClickDecision("input target bound observation=\(snapshot.observationID) pid=\(snapshot.app.pid) scope=\(target.scope) window=\(String(describing: snapshot.targetWindowID))")
        let note = target.element == nil
            ? "Window input position bound by a directed click. Only window identity is confirmed; inspect the screenshot to confirm the intended input position. No AX editable receiver is claimed. Rebind after focus/window changes or pointer actions."
            : "Editable receiver bound without changing focus. Keyboard actions establish the receiver before dispatch."
        let result = snapshotResult(for: refreshed, style: .actionResult)
        return ToolCallResult(
            content: result.content + [.text(note)],
            inputResult: ["target_scope": target.scope, "verification": "unconfirmed"],
            application: result.application
        )
    }

    func invalidateWindowInputTarget(app query: String) {
        guard let snapshot = snapshotsByApp[query.lowercased()],
              inputTargets[snapshot.app.pid]?.element == nil else { return }
        inputTargets.removeValue(forKey: snapshot.app.pid)
    }

    private func bindInputTarget(snapshot: AppSnapshot, index: String) throws -> InputTarget {
        let element = try inputElement(snapshot: snapshot, index: index)
        guard let window = snapshot.windowElement else {
            throw ComputerUseError.message("[input.target_invalid] The observation has no window identity")
        }
        // Text/selection attributes provide editor evidence; localized role labels do not.
        var attributes: CFArray?
        _ = AXUIElementCopyAttributeNames(element, &attributes)
        let names = attributes as? [String] ?? []
        if names.contains(kAXSelectedTextRangeAttribute as String) || names.contains(kAXSelectedTextAttribute as String) {
            return InputTarget(receiver: .element(element), window: window, windowID: snapshot.targetWindowID,
                               windowBounds: snapshot.windowBounds, anchorElement: element)
        }
        let record = try lookupElement(snapshot: snapshot, index: index)
        let local = try pointerPoint(for: record, snapshot: snapshot)
        let point = try windowPointToGlobalPoint(snapshot: snapshot, point: local)
        debugClickDecision("input locator scope=window anchor={\(diagnosticElementDescription(element))} local=\(local)")
        return InputTarget(receiver: .windowPoint(point), window: window, windowID: snapshot.targetWindowID,
                           windowBounds: snapshot.windowBounds, anchorElement: element, anchorFrame: localFrame(of: element, windowBounds: snapshot.windowBounds))
    }

    private func establishInputTarget(_ target: InputTarget, snapshot: AppSnapshot) throws {
        inputTargets.removeValue(forKey: snapshot.app.pid)
        try validateInputTarget(target, snapshot: snapshot)
        if case .windowPoint(let point) = target.receiver {
            try performNonAXClickFallback(at: point, button: .left, clickCount: 1,
                                         targetDescription: "input_target", snapshot: snapshot)
            try SkyClickDispatcher.withWindowTarget(try windowEventTarget(snapshot)) {
                try prepareKeyboardReceiver(target: target, snapshot: snapshot)
            }
        }
    }

    private func resolveInputTarget(snapshot: AppSnapshot, index: String?) throws -> InputTarget {
        if let index {
            let element = try inputElement(snapshot: snapshot, index: index)
            if let saved = inputTargets[snapshot.app.pid], let savedElement = saved.anchorElement ?? saved.element, CFEqual(savedElement, element),
               saved.windowID == snapshot.targetWindowID {
                try validateInputTarget(saved, snapshot: snapshot)
                return saved
            }
            let target = try bindInputTarget(snapshot: snapshot, index: index)
            try establishInputTarget(target, snapshot: snapshot)
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
        if let element = target.element { try validateInputElement(element, snapshot: snapshot) }
        if let anchor = target.anchorElement {
            try validateInputElement(anchor, snapshot: snapshot)
            if let frame = target.anchorFrame, localFrame(of: anchor, windowBounds: snapshot.windowBounds) != frame {
                inputTargets.removeValue(forKey: snapshot.app.pid)
                throw ComputerUseError.message("[input.target_invalid] The bound input position moved; observe and bind again")
            }
        }
        if target.element == nil, target.windowBounds != snapshot.windowBounds {
            inputTargets.removeValue(forKey: snapshot.app.pid)
            throw ComputerUseError.message("[input.target_invalid] Window geometry changed; bind the input position again")
        }
        guard let window = snapshot.windowElement, CFEqual(window, target.window),
              target.windowID == snapshot.targetWindowID else {
            inputTargets.removeValue(forKey: snapshot.app.pid)
            throw ComputerUseError.message("[input.target_invalid] The bound input window changed; bind a target from a fresh observation")
        }
    }

    public func typeText(app query: String, text: String, elementIndex: String? = nil) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target = try resolveInputTarget(snapshot: snapshot, index: elementIndex)
        return try executeKeyboard(target: target, snapshot: snapshot, query: query, operation: "insert") { requireFrontmost in
            try InputSimulation.typeText(text, target: try self.windowEventTarget(snapshot)) {
                try self.validateKeyboardReceiver(target: target, snapshot: snapshot, requireFrontmost: requireFrontmost)
            }
            return "unconfirmed"
        }
    }

    public func pressKey(app query: String, key: String, elementIndex: String? = nil) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target = try resolveInputTarget(snapshot: snapshot, index: elementIndex)
        return try executeKeyboard(target: target, snapshot: snapshot, query: query, operation: "key") { requireFrontmost in
            try self.validateKeyboardReceiver(target: target, snapshot: snapshot, requireFrontmost: requireFrontmost)
            try InputSimulation.pressKey(key, target: try self.windowEventTarget(snapshot))
            return "unconfirmed"
        }
    }

    public func setValue(app query: String, elementIndex: String? = nil, value: String) throws -> ToolCallResult {
        let snapshot = try currentSnapshot(for: query)
        let target = try resolveInputTarget(snapshot: snapshot, index: elementIndex)
        return try executeKeyboard(target: target, snapshot: snapshot, query: query, operation: "replace") { requireFrontmost in
            let before = try ReplacementSelection.read(target.element)
            guard let element = target.element else { throw ReplacementSelectionError.unavailable }
            let nativeSelection = try before.selectAll(in: element)
            if !nativeSelection {
                try InputSimulation.pressKey("super+a", target: try self.windowEventTarget(snapshot))
            }
            try self.validateKeyboardReceiver(target: target, snapshot: snapshot, requireFrontmost: requireFrontmost)
            let selected = try ReplacementSelection.read(target.element)
            self.debugClickDecision("input replacement selection native=\(nativeSelection) length=\(selected.length) range=\(selected.range) complete=\(selected.coversDocument) original_length=\(before.length)")
            guard selected.length == before.length, selected.coversDocument else {
                throw ReplacementSelectionError.unconfirmed
            }
            if value.isEmpty {
                try InputSimulation.pressKey("BackSpace", target: try self.windowEventTarget(snapshot))
            } else {
                try InputSimulation.typeText(value, target: try self.windowEventTarget(snapshot)) {
                    try self.validateKeyboardReceiver(target: target, snapshot: snapshot, requireFrontmost: requireFrontmost)
                }
            }
            return self.verifyReplacementValue(
                value, element: element, target: target, snapshot: snapshot,
                requireFrontmost: requireFrontmost
            ) ? "value_verified" : "unconfirmed"
        }
    }

    private func executeKeyboard(target: InputTarget, snapshot: AppSnapshot, query: String,
                                 operation: String, dispatch: @escaping (Bool) throws -> String) throws -> ToolCallResult {
        traceRuntimeContext(stage: "keyboard_before", snapshot: snapshot)
        defer { traceRuntimeContext(stage: "keyboard_after", snapshot: snapshot) }
        retireObservation(snapshot.observationID)
        let capability: KeyboardDeliveryCapability = target.element != nil && keyboardReceiverMatches(target: target, snapshot: snapshot)
            ? .directedBackground : .foregroundLease
        var deliveryStarted = false
        var verification = "unconfirmed"
        debugClickDecision("input dispatch operation=\(operation) pid=\(snapshot.app.pid) window=\(String(describing: snapshot.targetWindowID)) mode=\(capability.rawValue)")
        do {
            let transaction = {
                if capability.requiresForegroundLease {
                    try self.reestablishKeyboardTarget(target, snapshot: snapshot)
                }
                try SkyClickDispatcher.withWindowTarget(try self.windowEventTarget(snapshot)) {
                    try self.prepareKeyboardReceiver(target: target, snapshot: snapshot)
                    try self.validateKeyboardReceiver(target: target, snapshot: snapshot, requireFrontmost: capability.requiresForegroundLease)
                    deliveryStarted = true
                    verification = try dispatch(capability.requiresForegroundLease)
                }
            }
            if capability.requiresForegroundLease {
                try ApplicationFocusLease.withTarget(
                    app: snapshot.app, window: target.window,
                    diagnostic: self.debugClickDecision, body: transaction
                )
            } else {
                try ApplicationFocusLease.preservingCurrentApplication(
                    targetPID: snapshot.app.pid,
                    diagnostic: self.debugClickDecision,
                    body: transaction
                )
            }
        } catch let error as ReplacementSelectionError {
            inputTargets.removeValue(forKey: snapshot.app.pid)
            debugClickDecision("input replacement stopped: \(error.message)")
            return ToolCallResult(content: [.text(error.message)], isError: true,
                                  inputResult: ["delivery": "not_sent", "verification": "unconfirmed", "reason": "replacement_precondition_failed", "input_mode": capability.rawValue])
        } catch {
            inputTargets.removeValue(forKey: snapshot.app.pid)
            if !deliveryStarted {
                debugClickDecision("input setup stopped before delivery error=\(error)")
                return ToolCallResult(
                    content: [.text("[input.setup_failed] Input setup failed before any keyboard event was sent. Cause: \(error)")],
                    isError: true,
                    inputResult: ["delivery": "not_sent", "verification": "unconfirmed", "reason": "focus_setup_failed", "input_mode": capability.rawValue])
            }
            debugClickDecision("input dispatch interrupted error=\(error)")
            return ToolCallResult(
                content: [.text("[input.delivery_interrupted] Keyboard delivery may be partial. Observe before any further action; never automatically replay. Cause: \(error)")],
                isError: true,
                inputResult: ["delivery": "unknown", "verification": "unconfirmed", "reason": "dispatch_interrupted", "input_mode": capability.rawValue])
        }
        let evidence = [
            "delivery": "posted",
            "verification": verification,
            "reason": verification == "value_verified" ? "value_readback_matched" : "keyboard_consumption_unobservable",
            "target_scope": target.scope,
            "input_mode": capability.rawValue,
        ]
        do {
            let result = snapshotResult(for: try refreshSnapshot(for: query), style: .actionResult)
            return ToolCallResult(
                content: result.content + [.text("Keyboard events posted to the bound target. Inspect the new observation to verify the effect; AX text and selection may describe an editor proxy. Do not automatically replay.")],
                inputResult: evidence,
                application: result.application
            )
        } catch {
            return ToolCallResult(content: [.text("[observation.unavailable] Keyboard events were posted, but the next observation is unavailable. Obtain a new state without replaying the action.")],
                                  isError: true, inputResult: evidence)
        }
    }

    private func verifyReplacementValue(
        _ expected: String, element: AXUIElement, target: InputTarget,
        snapshot: AppSnapshot, requireFrontmost: Bool
    ) -> Bool {
        let deadline = ProcessInfo.processInfo.systemUptime + KeyboardReceiverPolicy.timeout
        repeat {
            do {
                try validateKeyboardReceiver(
                    target: target, snapshot: snapshot, requireFrontmost: requireFrontmost
                )
            } catch {
                debugClickDecision("input readback stopped receiver_invalid error=\(error)")
                return false
            }
            var value: CFTypeRef?
            if AXUIElementCopyAttributeValue(element, kAXValueAttribute as CFString, &value) == .success,
               let actual = value as? String, actual == expected {
                debugClickDecision("input readback matched length=\(actual.utf16.count)")
                return true
            }
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            if remaining <= 0 { break }
            RunLoop.current.run(until: Date(timeIntervalSinceNow: min(KeyboardReceiverPolicy.pollInterval, remaining)))
        } while true
        debugClickDecision("input readback unavailable_or_mismatch expected_length=\(expected.utf16.count)")
        return false
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
        var enabled: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXEnabledAttribute as CFString, &enabled) == .success,
           enabled as? Bool == false {
            throw ComputerUseError.message("[input.unsupported] The requested input target is disabled")
        }
    }

    private func prepareKeyboardReceiver(target: InputTarget, snapshot: AppSnapshot) throws {
        try validateSnapshotWindow(snapshot)
        try validateInputTarget(target, snapshot: snapshot)
        if let element = target.element {
            let evidence = KeyboardTargetEvidence(pid: snapshot.app.pid, target: element)
            if !evidence.resolves(to: element), isSettable(element: element, attribute: kAXFocusedAttribute) {
                let status = AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
                debugClickDecision("input focus_request pid=\(snapshot.app.pid) status=\(status.rawValue)")
            }
        }
        // Focus requests are asynchronous; wait for evidence rather than trusting their return code.
        let deadline = ProcessInfo.processInfo.systemUptime + KeyboardReceiverPolicy.timeout
        repeat {
            try validateSnapshotWindow(snapshot)
            try validateInputTarget(target, snapshot: snapshot)
            if keyboardReceiverMatches(target: target, snapshot: snapshot) {
                try validateKeyboardReceiver(target: target, snapshot: snapshot)
                return
            }
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            if remaining <= 0 { break }
            // AppKit activation completion and focus notifications need the host main run loop.
            RunLoop.current.run(until: Date(timeIntervalSinceNow: min(KeyboardReceiverPolicy.pollInterval, remaining)))
        } while true
        try validateKeyboardReceiver(target: target, snapshot: snapshot)
    }

    private func reestablishKeyboardTarget(_ target: InputTarget, snapshot: AppSnapshot) throws {
        try ApplicationFocusLease.requireOwnership(of: snapshot.app.pid)
        try validateInputTarget(target, snapshot: snapshot)
        if keyboardReceiverMatches(target: target, snapshot: snapshot) { return }

        if let element = target.element {
            if isSettable(element: element, attribute: kAXFocusedAttribute) {
                let status = AXUIElementSetAttributeValue(
                    element, kAXFocusedAttribute as CFString, kCFBooleanTrue
                )
                debugClickDecision("input lease focus_request pid=\(snapshot.app.pid) status=\(status.rawValue)")
                RunLoop.current.run(until: Date(timeIntervalSinceNow: KeyboardReceiverPolicy.pollInterval))
                if keyboardReceiverMatches(target: target, snapshot: snapshot) { return }
            }
            guard let frame = localFrame(of: element, windowBounds: snapshot.windowBounds),
                  frame.width > 0, frame.height > 0 else {
                throw ComputerUseError.message("[click.position_unavailable] The input receiver has no current clickable position")
            }
            let local = CGPoint(x: frame.midX, y: frame.midY)
            let point = try windowPointToGlobalPoint(snapshot: snapshot, point: local)
            try performNonAXClickFallback(
                at: point, button: .left, clickCount: 1,
                targetDescription: "foreground_input_receiver", snapshot: snapshot
            )
        } else if let point = target.boundPoint {
            try performNonAXClickFallback(
                at: point, button: .left, clickCount: 1,
                targetDescription: "foreground_input_position", snapshot: snapshot
            )
        } else {
            throw ComputerUseError.message("[input.target_invalid] The input target has no receiver or bound point")
        }
    }

    private func keyboardReceiverMatches(target: InputTarget, snapshot: AppSnapshot) -> Bool {
        var window: CFTypeRef?
        guard AXUIElementCopyAttributeValue(AXUIElementCreateApplication(snapshot.app.pid),
                                            kAXFocusedWindowAttribute as CFString, &window) == .success,
              let window, CFEqual(window, target.window) else { return false }
        guard let element = target.element else { return true }
        return KeyboardTargetEvidence(pid: snapshot.app.pid, target: element).resolves(to: element)
    }

    private func validateKeyboardReceiver(
        target: InputTarget, snapshot: AppSnapshot, requireFrontmost: Bool = false
    ) throws {
        if requireFrontmost {
            try ApplicationFocusLease.requireOwnership(of: snapshot.app.pid)
        }
        try validateSnapshotWindow(snapshot)
        try validateInputTarget(target, snapshot: snapshot)
        let matched = keyboardReceiverMatches(target: target, snapshot: snapshot)
        if let element = target.element {
            let evidence = KeyboardTargetEvidence(pid: snapshot.app.pid, target: element)
            debugClickDecision("input receiver pid=\(snapshot.app.pid) scope=element receiver_status=\(evidence.receiverStatus.rawValue) receiver={\(diagnosticElementDescription(evidence.receiver))} matched=\(matched)")
        } else {
            debugClickDecision("input receiver pid=\(snapshot.app.pid) scope=window window=\(String(describing: target.windowID)) matched=\(matched) editable_receiver=unobservable")
        }
        guard matched else {
            throw ComputerUseError.message("[input.receiver_unconfirmed] The target window and keyboard receiver could not be confirmed. Observe and focus the intended editor before retrying.")
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
        guard let id = snapshot.targetWindowID, let expected = snapshot.windowBounds else {
            throw ComputerUseError.message("[observation.window_unavailable] Observation has no window identity or bounds")
        }
        guard let entries = CGWindowListCopyWindowInfo(.optionIncludingWindow, id) as? [[String: Any]],
              let info = entries.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == id }) else {
            throw ComputerUseError.message("[observation.window_unavailable] Window \(id) is no longer listed")
        }
        let owner = (info[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value
        let onscreen = (info[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue
        let current = (info[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation: $0) }
        debugClickDecision("window validation id=\(id) expected_pid=\(snapshot.app.pid) actual_pid=\(String(describing: owner)) expected_bounds=\(expected) actual_bounds=\(String(describing: current)) onscreen=\(String(describing: onscreen))")
        guard owner == snapshot.app.pid else {
            throw ComputerUseError.message("[observation.stale] Window owner changed")
        }
        guard onscreen == true, let current else {
            throw ComputerUseError.message("[observation.window_unavailable] Window is offscreen or its bounds cannot be read")
        }
        guard current == expected else {
            throw ComputerUseError.message("[observation.geometry_changed] Window bounds changed from \(expected) to \(current). Use a fresh screenshot for coordinates.")
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
        let current = record.element.flatMap { localFrame(of: $0, windowBounds: snapshot.windowBounds) }
        debugClickDecision("pointer geometry element=\(record.index) observed=\(String(describing: record.localFrame)) current=\(String(describing: current)) bounds=\(String(describing: snapshot.windowBounds))")
        guard let frame = current, !frame.isNull, !frame.isInfinite, frame.width > 0, frame.height > 0,
              let bounds = snapshot.windowBounds,
              CGRect(origin: .zero, size: bounds.size).contains(CGPoint(x: frame.midX, y: frame.midY)) else {
            throw ComputerUseError.message("[click.position_unavailable] The identified control has no usable current position inside this window. Choose a position from the latest screenshot.")
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
    private func postActionResult(for query: String, recoveryPolicy: SnapshotRecoveryPolicy = .readOnly) -> ToolCallResult {
        do {
            return snapshotResult(for: try refreshSnapshot(for: query, recoveryPolicy: recoveryPolicy), style: .actionResult)
        } catch {
            debugClickDecision("observation after_action unavailable error=\(error)")
            return ToolCallResult.text(
                "[observation.after_action] The action was dispatched, but the updated window could not be read. Its effect is unconfirmed. Check the window state before further action; do not replay automatically. Cause: \(error)",
                isError: true
            )
        }
    }

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
        try snapshot.validateScreenshotPoint(CGPoint(x: x, y: y))
        return try windowPointToGlobalPoint(
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
            screenshotPixelSize: snapshot.screenshotPixelSize,
            windowBounds: snapshot.windowBounds
        )
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

    private func windowEventTarget(_ snapshot: AppSnapshot, at point: CGPoint? = nil) throws -> SkyClickTarget {
        try validateSnapshotWindow(snapshot)
        guard let bounds = snapshot.windowBounds, let id = snapshot.targetWindowID else {
            throw ComputerUseError.message("[observation.required] A target window is required")
        }
        let screenPoint = point ?? CGPoint(x: bounds.midX, y: bounds.midY)
        return SkyClickTarget(screenPoint: inputEventPoint(fromScreenStatePoint: screenPoint),
                              windowPoint: CGPoint(x: screenPoint.x - bounds.minX, y: screenPoint.y - bounds.minY),
                              windowBounds: bounds, windowID: id, pid: snapshot.app.pid)
    }

    private func performScrollEvent(at point: CGPoint, direction: String, pages: Double,
                                    targetDescription: String, snapshot: AppSnapshot) throws {
        let target = try windowEventTarget(snapshot, at: point)
        debugClickDecision("scroll dispatch=window_targeted pid=\(target.pid) window=\(target.windowID)")
        try SkyClickDispatcher.withWindowTarget(target) {
            try InputSimulation.scrollTargeted(at: target.screenPoint, direction: direction, pages: pages, target: target)
        }
    }

    private func performDragEvent(from start: CGPoint, to end: CGPoint,
                                  targetDescription: String, snapshot: AppSnapshot) throws {
        let target = try windowEventTarget(snapshot, at: start)
        guard let bounds = snapshot.windowBounds, bounds.contains(start), bounds.contains(end) else {
            throw ComputerUseError.message("[click.target_invalid] Drag endpoints must be inside the bound window")
        }
        debugClickDecision("drag dispatch=window_targeted pid=\(target.pid) window=\(target.windowID)")
        try SkyClickDispatcher.withWindowTarget(target) {
            try InputSimulation.dragTargeted(from: target.screenPoint, to: inputEventPoint(fromScreenStatePoint: end), target: target)
        }
    }

    private func performNonAXClickFallback(at point: CGPoint, button: MouseButtonKind, clickCount: Int,
                                           targetDescription: String, snapshot: AppSnapshot) throws {
        try validateSkyClickArguments(method: .skyClick, mouseButton: button.rawValue, clickCount: clickCount)
        let target = try windowEventTarget(snapshot, at: point)
        debugClickDecision("click dispatch=window_targeted pid=\(target.pid) window=\(target.windowID) screen=\(target.screenPoint) local=\(target.windowPoint)")
        try SkyClickDispatcher.click(target: target, clickCount: clickCount)
    }

    private func performExplicitMouseClick(method: ClickMethod, at point: CGPoint, windowPoint: CGPoint,
                                           button: MouseButtonKind, clickCount: Int,
                                           targetDescription: String, snapshot: AppSnapshot) throws {
        guard method == .skyClick else {
            throw ComputerUseError.message("[click.unsupported] This method does not dispatch window mouse events")
        }
        try performNonAXClickFallback(at: point, button: button, clickCount: clickCount,
                                      targetDescription: targetDescription, snapshot: snapshot)
    }

    private func snapshotResult(for snapshot: AppSnapshot, style: SnapshotTextStyle) -> ToolCallResult {
        var content = [ToolResultContentItem.text(snapshot.renderedText(style: style))]
        if let screenshotPNGData = snapshot.screenshotPNGData {
            content.append(.pngImage(screenshotPNGData))
        }
        return ToolCallResult(
            content: content,
            application: ToolResultApplication(snapshot: snapshot)
        )
    }
}
