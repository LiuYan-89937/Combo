param(
    [Parameter(Mandatory = $true)]
    [string]$OperationPath
)

$ErrorActionPreference = "Stop"
$DefaultTextLimit = 500
$AccessibilityTreeMaxNodeCount = 1200
$AccessibilityTreeMaxDepth = 64
$InputVerificationDefaultTimeoutMS = 1000
$InputVerificationPollMS = 50
$script:InputResult = @{}
$script:InputTarget = $null
$script:Diagnostics = New-Object System.Collections.Generic.List[string]

# Set output encoding to UTF-8 to properly handle non-ASCII characters
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class OCUWin32 {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct GUITHREADINFO {
        public int cbSize;
        public uint flags;
        public IntPtr hwndActive, hwndFocus, hwndCapture, hwndMenuOwner, hwndMoveSize, hwndCaret;
        public RECT rcCaret;
    }

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);

    [DllImport("user32.dll")]
    public static extern bool GetGUIThreadInfo(uint threadId, ref GUITHREADINFO info);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    public static extern bool ScreenToClient(IntPtr hWnd, ref POINT point);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool PostMessage(IntPtr hWnd, UInt32 msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessage(IntPtr hWnd, UInt32 msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessage(IntPtr hWnd, UInt32 msg, IntPtr wParam, string lParam);

    [DllImport("user32.dll", EntryPoint = "SendMessageW")]
    public static extern IntPtr GetEditSelection(IntPtr hWnd, UInt32 msg, out int start, out int end);
}
"@

$WM_SETTEXT = 0x000C
$WM_MOUSEMOVE = 0x0200
$WM_LBUTTONDOWN = 0x0201
$WM_LBUTTONUP = 0x0202
$WM_RBUTTONDOWN = 0x0204
$WM_RBUTTONUP = 0x0205
$WM_MBUTTONDOWN = 0x0207
$WM_MBUTTONUP = 0x0208
$WM_MOUSEWHEEL = 0x020A
$WM_MOUSEHWHEEL = 0x020E
$WM_KEYDOWN = 0x0100
$WM_KEYUP = 0x0101
$WM_CHAR = 0x0102
$EM_GETSEL = 0x00B0
$EM_SETSEL = 0x00B1

function Test-EnvFlagEnabled([string]$name) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $false
    }
    $normalized = $value.Trim().ToLowerInvariant()
    return @("1", "true", "yes", "on") -contains $normalized
}

function New-Frame($x, $y, $width, $height) {
    if ($width -lt 0 -or $height -lt 0) {
        return $null
    }
    [pscustomobject]@{
        x = [double]$x
        y = [double]$y
        width = [double]$width
        height = [double]$height
    }
}

function ConvertTo-LParam([int]$x, [int]$y) {
    $packed = (($y -band 0xffff) -shl 16) -bor ($x -band 0xffff)
    [IntPtr]$packed
}

function ConvertTo-WheelWParam([int]$delta) {
    $packed = (($delta -band 0xffff) -shl 16)
    [IntPtr]$packed
}

function Get-WindowRectFrame([IntPtr]$hwnd) {
    $rect = New-Object OCUWin32+RECT
    if ([OCUWin32]::GetWindowRect($hwnd, [ref]$rect)) {
        return New-Frame $rect.Left $rect.Top ($rect.Right - $rect.Left) ($rect.Bottom - $rect.Top)
    }
    return $null
}

function Get-ElementFrame($element, $windowBounds) {
    try {
        $rect = $element.Current.BoundingRectangle
        if ($rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0) {
            return $null
        }
        if ($null -ne $windowBounds) {
            return New-Frame ($rect.X - $windowBounds.x) ($rect.Y - $windowBounds.y) $rect.Width $rect.Height
        }
        return New-Frame $rect.X $rect.Y $rect.Width $rect.Height
    } catch {
        return $null
    }
}

function Get-ScreenPoint($localFrame, $windowBounds) {
    if ($null -eq $localFrame -or $null -eq $windowBounds) {
        return $null
    }
    [pscustomobject]@{
        x = [int][math]::Round($windowBounds.x + $localFrame.x + ($localFrame.width / 2))
        y = [int][math]::Round($windowBounds.y + $localFrame.y + ($localFrame.height / 2))
    }
}

function Send-MouseClick([IntPtr]$hwnd, [int]$screenX, [int]$screenY, [string]$button, [int]$count) {
    $point = New-Object OCUWin32+POINT
    $point.X = $screenX
    $point.Y = $screenY
    [void][OCUWin32]::ScreenToClient($hwnd, [ref]$point)
    $lParam = ConvertTo-LParam $point.X $point.Y

    $down = $WM_LBUTTONDOWN
    $up = $WM_LBUTTONUP
    $downFlag = 0x0001
    if ($button -eq "right") {
        $down = $WM_RBUTTONDOWN
        $up = $WM_RBUTTONUP
        $downFlag = 0x0002
    } elseif ($button -eq "middle") {
        $down = $WM_MBUTTONDOWN
        $up = $WM_MBUTTONUP
        $downFlag = 0x0010
    }

    $repeat = [math]::Max(1, $count)
    for ($i = 0; $i -lt $repeat; $i++) {
        [void][OCUWin32]::PostMessage($hwnd, $WM_MOUSEMOVE, [IntPtr]::Zero, $lParam)
        [void][OCUWin32]::PostMessage($hwnd, $down, [IntPtr]$downFlag, $lParam)
        Start-Sleep -Milliseconds 35
        [void][OCUWin32]::PostMessage($hwnd, $up, [IntPtr]::Zero, $lParam)
        Start-Sleep -Milliseconds 50
    }
}

function Send-Drag([IntPtr]$hwnd, [int]$fromX, [int]$fromY, [int]$toX, [int]$toY) {
    $start = New-Object OCUWin32+POINT
    $start.X = $fromX
    $start.Y = $fromY
    [void][OCUWin32]::ScreenToClient($hwnd, [ref]$start)
    $end = New-Object OCUWin32+POINT
    $end.X = $toX
    $end.Y = $toY
    [void][OCUWin32]::ScreenToClient($hwnd, [ref]$end)

    $steps = 12
    $startParam = ConvertTo-LParam $start.X $start.Y
    [void][OCUWin32]::PostMessage($hwnd, $WM_MOUSEMOVE, [IntPtr]::Zero, $startParam)
    [void][OCUWin32]::PostMessage($hwnd, $WM_LBUTTONDOWN, [IntPtr]1, $startParam)
    for ($i = 1; $i -le $steps; $i++) {
        $x = [int][math]::Round($start.X + (($end.X - $start.X) * $i / $steps))
        $y = [int][math]::Round($start.Y + (($end.Y - $start.Y) * $i / $steps))
        [void][OCUWin32]::PostMessage($hwnd, $WM_MOUSEMOVE, [IntPtr]1, (ConvertTo-LParam $x $y))
        Start-Sleep -Milliseconds 20
    }
    [void][OCUWin32]::PostMessage($hwnd, $WM_LBUTTONUP, [IntPtr]::Zero, (ConvertTo-LParam $end.X $end.Y))
}

function Send-Scroll([IntPtr]$hwnd, [int]$screenX, [int]$screenY, [string]$direction, [double]$pages) {
    $point = New-Object OCUWin32+POINT
    $point.X = $screenX
    $point.Y = $screenY
    [void][OCUWin32]::ScreenToClient($hwnd, [ref]$point)
    $lParam = ConvertTo-LParam $point.X $point.Y
    $delta = [int][math]::Round(120 * $pages)
    $message = $WM_MOUSEWHEEL
    if ($direction -eq "down" -or $direction -eq "right") {
        $delta = -1 * $delta
    }
    if ($direction -eq "left" -or $direction -eq "right") {
        $message = $WM_MOUSEHWHEEL
    }
    [void][OCUWin32]::PostMessage($hwnd, $message, (ConvertTo-WheelWParam $delta), $lParam)
}

function Send-Text([IntPtr]$hwnd, [string]$text, [scriptblock]$validateTarget) {
    foreach ($char in $text.ToCharArray()) {
        if ($null -ne $validateTarget) { & $validateTarget }
        if (-not [OCUWin32]::PostMessage($hwnd, $WM_CHAR, [IntPtr][int][char]$char, [IntPtr]::Zero)) { throw "Character delivery failed; earlier characters may have been delivered" }
        Start-Sleep -Milliseconds 8
    }
}

function Get-VirtualKey([string]$key) {
    $normalized = $key.ToLowerInvariant()
    $map = @{
        "return" = 0x0D; "enter" = 0x0D; "tab" = 0x09; "escape" = 0x1B; "esc" = 0x1B
        "backspace" = 0x08; "back_space" = 0x08; "delete" = 0x2E; "space" = 0x20
        "left" = 0x25; "up" = 0x26; "right" = 0x27; "down" = 0x28
        "home" = 0x24; "end" = 0x23; "page_up" = 0x21; "prior" = 0x21; "page_down" = 0x22; "next" = 0x22
    }
    if ($map.ContainsKey($normalized)) {
        return $map[$normalized]
    }
    if ($normalized -match "^f([1-9]|1[0-2])$") {
        return 0x70 + [int]$Matches[1] - 1
    }
    if ($normalized -match "^kp_([0-9])$") {
        return 0x60 + [int]$Matches[1]
    }
    if ($normalized.Length -eq 1) {
        $code = [int][char]$normalized.ToUpperInvariant()[0]
        if (($code -ge 0x30 -and $code -le 0x39) -or ($code -ge 0x41 -and $code -le 0x5A)) {
            return $code
        }
    }
    throw "Unsupported key: $key"
}

function Send-Key([IntPtr]$hwnd, [string]$key) {
    if ($key.Contains("+")) {
        throw "[input.background_unsupported] Independent modifier state is unavailable"
    }
    $vk = Get-VirtualKey $key
    if (-not [OCUWin32]::PostMessage($hwnd, $WM_KEYDOWN, [IntPtr]$vk, [IntPtr]::Zero)) {
        throw "[input.write_failed] Key-down delivery failed; observe before further input"
    }
    if (-not [OCUWin32]::PostMessage($hwnd, $WM_KEYUP, [IntPtr]$vk, [IntPtr]::Zero)) {
        throw "[input.write_failed] Key-up delivery failed; delivery may be partial"
    }
}

function Resolve-App([string]$query) {
    $normalized = $query.Trim()
    $processQuery = $normalized
    if ($processQuery.EndsWith(".exe", [System.StringComparison]::OrdinalIgnoreCase)) {
        $processQuery = $processQuery.Substring(0, $processQuery.Length - 4)
    }
    $processes = @(Get-Process | Where-Object { $_.MainWindowHandle -ne 0 })
    $pidValue = 0
    if ([int]::TryParse($normalized, [ref]$pidValue)) {
        $match = $processes | Where-Object { $_.Id -eq $pidValue } | Select-Object -First 1
        if ($null -ne $match) {
            return $match
        }
    }

    $match = $processes | Where-Object {
        $_.ProcessName -ieq $processQuery -or
        "$($_.ProcessName).exe" -ieq $normalized -or
        $_.MainWindowTitle -ieq $normalized -or
        $_.MainWindowTitle -ilike "*$normalized*"
    } | Select-Object -First 1
    if ($null -ne $match) {
        return $match
    }

    if (Test-EnvFlagEnabled "OPEN_COMPUTER_USE_WINDOWS_ALLOW_APP_LAUNCH") {
        try {
            $started = Start-Process -FilePath $normalized -PassThru
            for ($i = 0; $i -lt 20; $i++) {
                Start-Sleep -Milliseconds 250
                $candidate = Get-Process -Id $started.Id -ErrorAction SilentlyContinue
                if ($null -ne $candidate -and $candidate.MainWindowHandle -ne 0) {
                    return $candidate
                }
            }
        } catch {
        }
    }

    throw "appNotFound(`"$query`")"
}

function Get-MainElement($process) {
    if ($process.MainWindowHandle -ne 0) {
        return [Windows.Automation.AutomationElement]::FromHandle([IntPtr]$process.MainWindowHandle)
    }
    $condition = New-Object Windows.Automation.PropertyCondition ([Windows.Automation.AutomationElement]::ProcessIdProperty), $process.Id
    $children = [Windows.Automation.AutomationElement]::RootElement.FindAll([Windows.Automation.TreeScope]::Children, $condition)
    if ($children.Count -gt 0) {
        return $children.Item(0)
    }
    throw "No top-level UI Automation window is available for $($process.ProcessName). Run the Windows runtime in the signed-in desktop session."
}

function Get-WindowBounds($process, $element) {
    $hwnd = [IntPtr]$process.MainWindowHandle
    if ($hwnd -ne [IntPtr]::Zero) {
        $fromWin32 = Get-WindowRectFrame $hwnd
        if ($null -ne $fromWin32) {
            return $fromWin32
        }
    }
    try {
        $rect = $element.Current.BoundingRectangle
        if (-not $rect.IsEmpty -and $rect.Width -gt 0 -and $rect.Height -gt 0) {
            return New-Frame $rect.X $rect.Y $rect.Width $rect.Height
        }
    } catch {
    }
    return $null
}

function Get-PatternNames($element) {
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($pattern in $element.GetSupportedPatterns()) {
        $programmatic = $pattern.ProgrammaticName
        if ($programmatic -like "InvokePatternIdentifiers.Pattern") { $names.Add("Invoke") }
        elseif ($programmatic -like "TogglePatternIdentifiers.Pattern") { $names.Add("Toggle") }
        elseif ($programmatic -like "SelectionItemPatternIdentifiers.Pattern") { $names.Add("Select") }
        elseif ($programmatic -like "ExpandCollapsePatternIdentifiers.Pattern") {
            try {
                $state = $element.GetCurrentPattern([Windows.Automation.ExpandCollapsePattern]::Pattern).Current.ExpandCollapseState
                if ($state -eq [Windows.Automation.ExpandCollapseState]::Collapsed) { $names.Add("Expand") }
                elseif ($state -eq [Windows.Automation.ExpandCollapseState]::Expanded) { $names.Add("Collapse") }
            } catch {
                $names.Add("Expand")
                $names.Add("Collapse")
            }
        }
        elseif ($programmatic -like "ScrollItemPatternIdentifiers.Pattern") { $names.Add("ScrollIntoView") }
        elseif ($programmatic -like "ScrollPatternIdentifiers.Pattern") { $names.Add("Scroll") }
        elseif ($programmatic -like "ValuePatternIdentifiers.Pattern") { $names.Add("SetValue") }
    }
    if ($names.Count -gt 0) {
        return @($names | Select-Object -Unique)
    }
    return @()
}

function Get-ElementString($element, [string]$propertyName) {
    try {
        $value = $element.Current.$propertyName
        if ($null -eq $value) {
            return ""
        }
        return [string]$value
    } catch {
        return ""
    }
}

function Get-ElementInt64($element, [string]$propertyName) {
    try {
        return [int64]$element.Current.$propertyName
    } catch {
        return 0
    }
}

function Get-ElementControlTypeName($element) {
    try {
        $controlType = $element.Current.ControlType
        if ($null -eq $controlType) {
            return ""
        }
        return [string]$controlType.ProgrammaticName
    } catch {
        return ""
    }
}

function Resolve-TextLimit($Value) {
    if ($null -eq $Value) {
        return $script:DefaultTextLimit
    }
    if ($Value -is [string] -and $Value.Trim().ToLowerInvariant() -eq "max") {
        return $null
    }
    if ($Value -is [bool]) {
        return $script:DefaultTextLimit
    }
    try {
        $integer = [int]$Value
        if ($integer -gt 0) {
            return $integer
        }
    } catch {
    }
    return $script:DefaultTextLimit
}

function Limit-Text([string]$Text, $TextLimit = $script:DefaultTextLimit) {
    if ($null -eq $Text) {
        return ""
    }
    if ($null -eq $TextLimit) {
        return $Text
    }
    $effectiveTextLimit = [int]$TextLimit
    if ($Text.Length -gt $effectiveTextLimit) {
        return $Text.Substring(0, $effectiveTextLimit) + "..."
    }
    return $Text
}

function Get-ElementValue($element, $TextLimit = $script:DefaultTextLimit) {
    try {
        $valuePattern = $element.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern)
        $value = $valuePattern.Current.Value
        if ($null -eq $value) {
            return ""
        }
        $text = [string]$value
        return Limit-Text $text $TextLimit
    } catch {
        return ""
    }
}

function Get-ElementRecord($element, [int]$index, $windowBounds, $TextLimit = $script:DefaultTextLimit) {
    $frame = Get-ElementFrame $element $windowBounds
    $runtimeId = @()
    try { $runtimeId = @($element.GetRuntimeId()) } catch {}
    [pscustomobject]@{
        index = $index
        runtimeId = $runtimeId
        automationId = Get-ElementString $element "AutomationId"
        name = Limit-Text (Get-ElementString $element "Name") $TextLimit
        controlType = Get-ElementControlTypeName $element
        localizedControlType = Get-ElementString $element "LocalizedControlType"
        className = Get-ElementString $element "ClassName"
        value = Get-ElementValue $element $TextLimit
        nativeWindowHandle = Get-ElementInt64 $element "NativeWindowHandle"
        frame = $frame
        actions = @(Get-PatternNames $element)
    }
}

function Get-ElementTitle($record) {
    if (-not [string]::IsNullOrWhiteSpace($record.name)) {
        return $record.name
    }
    if (-not [string]::IsNullOrWhiteSpace($record.automationId)) {
        return "ID: $($record.automationId)"
    }
    return ""
}

function Render-Tree($element, $windowBounds, $TextLimit = $script:DefaultTextLimit, [int]$MaxTreeNodes = $script:AccessibilityTreeMaxNodeCount, [int]$MaxTreeDepth = $script:AccessibilityTreeMaxDepth) {
    $records = New-Object System.Collections.Generic.List[object]
    $lines = New-Object System.Collections.Generic.List[string]
    $visited = New-Object System.Collections.Generic.HashSet[string]
    $nextIndex = 0
    $effectiveMaxTreeNodes = if ($MaxTreeNodes -gt 0) { $MaxTreeNodes } else { $script:AccessibilityTreeMaxNodeCount }
    $effectiveMaxTreeDepth = if ($MaxTreeDepth -gt 0) { $MaxTreeDepth } else { $script:AccessibilityTreeMaxDepth }

    function Visit($node, [int]$depth) {
        if ($script:nextIndex -ge $script:MaxTreeNodes -or $depth -gt $script:MaxTreeDepth) {
            return
        }
        $runtime = ""
        try { $runtime = (@($node.GetRuntimeId()) -join ".") } catch { $runtime = [guid]::NewGuid().ToString() }
        if (-not $script:visited.Add($runtime)) {
            return
        }

        $index = $script:nextIndex
        $script:nextIndex++
        $record = Get-ElementRecord $node $index $script:windowBounds $TextLimit
        $script:records.Add($record)

        $role = $record.localizedControlType
        if ([string]::IsNullOrWhiteSpace($role)) {
            $role = $record.controlType
        }
        $title = Get-ElementTitle $record
        $actionsSegment = ""
        if ($record.actions.Count -gt 0) {
            $actionsSegment = " Secondary Actions: " + ($record.actions -join ", ")
        }
        $valueSegment = ""
        if (-not [string]::IsNullOrWhiteSpace($record.value) -and $record.value -ne $title) {
            $safeValue = (($record.value -replace "`r", "\\r") -replace "`n", "\\n")
            $valueSegment = " Value: $safeValue"
        }
        $frameSegment = ""
        if ($null -ne $record.frame) {
            $frameSegment = " Frame: {{x: {0}, y: {1}, width: {2}, height: {3}}}" -f [int][math]::Round($record.frame.x), [int][math]::Round($record.frame.y), [int][math]::Round($record.frame.width), [int][math]::Round($record.frame.height)
        }
        $script:lines.Add(("`t" * ($depth + 1)) + "$index $role $title$valueSegment$actionsSegment$frameSegment")

        try {
            $children = $node.FindAll([Windows.Automation.TreeScope]::Children, [Windows.Automation.Condition]::TrueCondition)
            for ($i = 0; $i -lt $children.Count; $i++) {
                Visit $children.Item($i) ($depth + 1)
            }
        } catch {
        }
    }

    $script:records = $records
    $script:lines = $lines
    $script:visited = $visited
    $script:nextIndex = $nextIndex
    $script:windowBounds = $windowBounds
    $script:MaxTreeNodes = $effectiveMaxTreeNodes
    $script:MaxTreeDepth = $effectiveMaxTreeDepth
    Visit $element 0

    [pscustomobject]@{
        records = $records.ToArray()
        lines = $lines.ToArray()
    }
}

function Capture-WindowPngBase64($bounds) {
    if ($null -eq $bounds -or $bounds.width -le 0 -or $bounds.height -le 0) {
        return $null
    }
    try {
        $bitmap = New-Object System.Drawing.Bitmap ([int][math]::Round($bounds.width)), ([int][math]::Round($bounds.height))
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen([int][math]::Round($bounds.x), [int][math]::Round($bounds.y), 0, 0, $bitmap.Size)
        $stream = New-Object System.IO.MemoryStream
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose()
        $bitmap.Dispose()
        $bytes = $stream.ToArray()
        $stream.Dispose()
        return [Convert]::ToBase64String($bytes)
    } catch {
        return $null
    }
}

function Get-FocusedSummary($processId, $TextLimit = $script:DefaultTextLimit) {
    try {
        $focused = [Windows.Automation.AutomationElement]::FocusedElement
        if ($null -ne $focused -and $focused.Current.ProcessId -eq $processId) {
            $role = $focused.Current.LocalizedControlType
            $name = Limit-Text $focused.Current.Name $TextLimit
            if ([string]::IsNullOrWhiteSpace($name)) {
                return $role
            }
            return "$role $name"
        }
    } catch {
    }
    return $null
}

function Get-SelectedText($processId, $TextLimit = $script:DefaultTextLimit) {
    try {
        $focused = [Windows.Automation.AutomationElement]::FocusedElement
        if ($null -eq $focused -or $focused.Current.ProcessId -ne $processId) {
            return $null
        }
        $textPattern = $focused.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern)
        $selection = $textPattern.GetSelection()
        if ($selection.Count -gt 0) {
            $maxLength = if ($null -eq $TextLimit) { -1 } else { [int]$TextLimit + 1 }
            return Limit-Text ($selection.Item(0).GetText($maxLength)) $TextLimit
        }
    } catch {
    }
    return $null
}

function Build-Snapshot([string]$query, $TextLimit = $script:DefaultTextLimit, [int]$MaxTreeNodes = $script:AccessibilityTreeMaxNodeCount, [int]$MaxTreeDepth = $script:AccessibilityTreeMaxDepth) {
    $process = Resolve-App $query
    $element = Get-MainElement $process
    $bounds = Get-WindowBounds $process $element
    $rendered = Render-Tree $element $bounds $TextLimit $MaxTreeNodes $MaxTreeDepth
    [pscustomobject]@{
        observationID = [Guid]::NewGuid().ToString()
        windowHandle = [long]$process.MainWindowHandle
        app = [pscustomobject]@{
            name = $process.ProcessName
            bundleIdentifier = $process.ProcessName
            pid = [int]$process.Id
        }
        windowTitle = Limit-Text $process.MainWindowTitle $TextLimit
        windowBounds = $bounds
        screenshotPngBase64 = Capture-WindowPngBase64 $bounds
        treeLines = @($rendered.lines)
        focusedSummary = Get-FocusedSummary $process.Id $TextLimit
        selectedText = Get-SelectedText $process.Id $TextLimit
        elements = @($rendered.records)
    }
}

function List-Apps {
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($process in (Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | Sort-Object ProcessName, Id)) {
        $title = $process.MainWindowTitle
        if ([string]::IsNullOrWhiteSpace($title)) {
            $title = "untitled"
        }
        $lines.Add(("{0} -- {1} [running, pid={2}, window={3}]" -f $process.ProcessName, $process.ProcessName, $process.Id, $title))
    }
    return ($lines -join "`n")
}

function Same-RuntimeId($left, $right) {
    if ($null -eq $left -or $null -eq $right -or $left.Count -ne $right.Count) {
        return $false
    }
    for ($i = 0; $i -lt $left.Count; $i++) {
        if ([int]$left[$i] -ne [int]$right[$i]) {
            return $false
        }
    }
    return $true
}

function Get-AllElements($root) {
    $items = New-Object System.Collections.Generic.List[object]
    $items.Add($root)
    try {
        $descendants = $root.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition)
        for ($i = 0; $i -lt $descendants.Count; $i++) {
            $items.Add($descendants.Item($i))
        }
    } catch {
    }
    return $items.ToArray()
}

function Find-Element($process, $record) {
    if ($null -eq $record) { return $null }
    $root = Get-MainElement $process
    $matches = @((Get-AllElements $root) | Where-Object {
        try { Same-RuntimeId @($_.GetRuntimeId()) @($record.runtimeId) } catch { $false }
    })
    if ($matches.Count -ne 1) { throw "[input.target_invalid] The original target is no longer uniquely available. Observe again." }
    return $matches[0]
}

function Get-CurrentPatternOrNull($element, $pattern) {
    try {
        return $element.GetCurrentPattern($pattern)
    } catch {
        return $null
    }
}

function Invoke-PreferredClick($element) {
    $invoke = Get-CurrentPatternOrNull $element ([Windows.Automation.InvokePattern]::Pattern)
    if ($null -ne $invoke) {
        $invoke.Invoke()
        return $true
    }
    $selection = Get-CurrentPatternOrNull $element ([Windows.Automation.SelectionItemPattern]::Pattern)
    if ($null -ne $selection) {
        $selection.Select()
        return $true
    }
    $toggle = Get-CurrentPatternOrNull $element ([Windows.Automation.TogglePattern]::Pattern)
    if ($null -ne $toggle) {
        $toggle.Toggle()
        return $true
    }
    return $false
}

function Invoke-SecondaryAction($element, [string]$action) {
    switch ($action.ToLowerInvariant()) {
        "invoke" {
            $pattern = Get-CurrentPatternOrNull $element ([Windows.Automation.InvokePattern]::Pattern)
            if ($null -ne $pattern) { $pattern.Invoke(); return }
        }
        "toggle" {
            $pattern = Get-CurrentPatternOrNull $element ([Windows.Automation.TogglePattern]::Pattern)
            if ($null -ne $pattern) { $pattern.Toggle(); return }
        }
        "select" {
            $pattern = Get-CurrentPatternOrNull $element ([Windows.Automation.SelectionItemPattern]::Pattern)
            if ($null -ne $pattern) { $pattern.Select(); return }
        }
        "expand" {
            $pattern = Get-CurrentPatternOrNull $element ([Windows.Automation.ExpandCollapsePattern]::Pattern)
            if ($null -ne $pattern) { $pattern.Expand(); return }
        }
        "collapse" {
            $pattern = Get-CurrentPatternOrNull $element ([Windows.Automation.ExpandCollapsePattern]::Pattern)
            if ($null -ne $pattern) { $pattern.Collapse(); return }
        }
        "scrollintoview" {
            $pattern = Get-CurrentPatternOrNull $element ([Windows.Automation.ScrollItemPattern]::Pattern)
            if ($null -ne $pattern) { $pattern.ScrollIntoView(); return }
        }
        "setfocus" {
            if (-not (Test-EnvFlagEnabled "OPEN_COMPUTER_USE_WINDOWS_ALLOW_FOCUS_ACTIONS")) {
                throw "SetFocus is disabled by default to avoid stealing user focus; set OPEN_COMPUTER_USE_WINDOWS_ALLOW_FOCUS_ACTIONS=1 to enable it."
            }
            $element.SetFocus()
            return
        }
    }
    throw "$action is not a valid secondary action for $($operation.element.index)"
}

function Invoke-Scroll($element, [string]$direction, [double]$pages) {
    $scroll = Get-CurrentPatternOrNull $element ([Windows.Automation.ScrollPattern]::Pattern)
    if ($null -eq $scroll) {
        return $false
    }
    $horizontal = [Windows.Automation.ScrollAmount]::NoAmount
    $vertical = [Windows.Automation.ScrollAmount]::NoAmount
    if ($direction -eq "up") { $vertical = [Windows.Automation.ScrollAmount]::LargeDecrement }
    elseif ($direction -eq "down") { $vertical = [Windows.Automation.ScrollAmount]::LargeIncrement }
    elseif ($direction -eq "left") { $horizontal = [Windows.Automation.ScrollAmount]::LargeDecrement }
    elseif ($direction -eq "right") { $horizontal = [Windows.Automation.ScrollAmount]::LargeIncrement }
    $repeat = [math]::Max(1, [int][math]::Ceiling($pages))
    for ($i = 0; $i -lt $repeat; $i++) {
        $scroll.Scroll($horizontal, $vertical)
        Start-Sleep -Milliseconds 40
    }
    return $true
}

function Resolve-InputElement($process, $record) {
    return Find-Element $process $record
}

function Assert-ElementWindow($process, $element) {
    if ($null -eq $element -or $element.Current.ProcessId -ne $process.Id) {
        throw "[input.target_invalid] Target process mismatch"
    }
    $rootId = @((Get-MainElement $process).GetRuntimeId())
    $walker = [Windows.Automation.TreeWalker]::RawViewWalker
    $node = $element
    while ($null -ne $node) {
        if (Same-RuntimeId @($node.GetRuntimeId()) $rootId) { return }
        $node = $walker.GetParent($node)
    }
    throw "[input.target_invalid] The target belongs to another window"
}

function Get-BackgroundInputHandle($process, $target) {
    Assert-ElementWindow $process $target
    $handle = [IntPtr]$target.Current.NativeWindowHandle
    if ($handle -eq [IntPtr]::Zero) {
        throw "[input.background_unsupported] The bound target has no addressable native keyboard handle"
    }
    [uint32]$owner = 0
    [void][OCUWin32]::GetWindowThreadProcessId($handle, [ref]$owner)
    $receiver = [Windows.Automation.AutomationElement]::FromHandle($handle)
    if ($owner -ne $process.Id -or $null -eq $receiver -or
        -not (Same-RuntimeId @($receiver.GetRuntimeId()) @($target.GetRuntimeId()))) {
        throw "[input.target_invalid] The native keyboard handle no longer resolves to the bound control"
    }
    return $handle
}

function New-InputTarget($process, $element) {
    $pattern = Get-InputPattern $process $element
    $value = Read-InputText $pattern
    $start = $null
    $length = $null
    if ($operation.tool -eq "set_input_target" -and $null -ne $operation.selection_start -and $null -ne $operation.selection_length) {
        $start = [int]$operation.selection_start
        $length = [int]$operation.selection_length
        if ($start -lt 0 -or $length -lt 0 -or $start -gt $value.Length -or $length -gt ($value.Length - $start)) {
            throw "[input.target_invalid] The requested UTF-16 selection is outside the text"
        }
    } elseif ($element.Current.NativeWindowHandle -ne 0 -and ($element.Current.ClassName -eq "Edit" -or $element.Current.ClassName -like "RichEdit*")) {
        $handle = Get-BackgroundInputHandle $process $element
        [int]$from = 0
        [int]$to = 0
        [void][OCUWin32]::GetEditSelection($handle, $EM_GETSEL, [ref]$from, [ref]$to)
        if ($from -ge 0 -and $to -ge $from -and $to -le $value.Length) {
            $start = $from
            $length = $to - $from
        }
    }
    return [pscustomobject]@{ pid = $process.Id; window_handle = [long]$process.MainWindowHandle;
        element = $operation.element; value = $value; selection_start = $start; selection_length = $length }
}

function Assert-InputSelection($pattern, $target) {
    $before = Read-InputText $pattern
    if ($null -eq $target.selection_start -or $null -eq $target.selection_length -or
        -not [string]::Equals($before, $target.value, [StringComparison]::Ordinal)) {
        throw "[input.target_stale] Text changed or the CU selection is unavailable; observe and use set_input_target"
    }
    $start = [int]$target.selection_start
    $length = [int]$target.selection_length
    if ($start -lt 0 -or $length -lt 0 -or $start -gt $before.Length -or $length -gt ($before.Length - $start)) {
        throw "[input.target_stale] The CU selection is outside the current text"
    }
}

function Set-BackgroundSelection($process, $element, $target) {
    $handle = Get-BackgroundInputHandle $process $element
    if ($element.Current.ClassName -ne "Edit" -and $element.Current.ClassName -notlike "RichEdit*") {
        throw "[input.background_unsupported] Native selection addressing is unavailable; use accessibility input"
    }
    [int]$start = $target.selection_start
    [int]$end = $start + $target.selection_length
    [void][OCUWin32]::SendMessage($handle, $EM_SETSEL, [IntPtr]$start, [IntPtr]$end)
    [int]$actualStart = 0
    [int]$actualEnd = 0
    [void][OCUWin32]::GetEditSelection($handle, $EM_GETSEL, [ref]$actualStart, [ref]$actualEnd)
    if ($actualStart -ne $start -or $actualEnd -ne $end) {
        throw "[input.selection_unconfirmed] The control did not confirm the requested selection; no text or keys were sent"
    }
    return $handle
}

function Assert-ObservedWindow($process, $request) {
    $current = Get-WindowBounds $process (Get-MainElement $process)
    if ($process.Id -ne $request.target_pid -or [long]$process.MainWindowHandle -ne $request.window_handle -or $null -eq $current -or $null -eq $request.windowBounds) {
        throw "[observation.stale] The observed process/window has changed. Run get_app_state again."
    }
    foreach ($field in @("x", "y", "width", "height")) {
        if ($current.$field -ne $request.windowBounds.$field) {
            throw "[observation.stale] The observed window geometry has changed. Run get_app_state again."
        }
    }
}

function Get-ClickPoint($process, $request, $element) {
    Assert-ObservedWindow $process $request
    $bounds = $request.windowBounds
    if ($null -ne $request.element) {
        Assert-ElementWindow $process $element
        $rect = $element.Current.BoundingRectangle
        $saved = $request.element.frame
        if ($null -eq $saved -or $rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0 -or $element.Current.IsOffscreen -or
            ($rect.X - $bounds.x) -ne $saved.x -or ($rect.Y - $bounds.y) -ne $saved.y -or $rect.Width -ne $saved.width -or $rect.Height -ne $saved.height) {
            throw "[observation.stale] The requested element has no unchanged visible pointer location"
        }
        $x = $rect.X + $rect.Width / 2
        $y = $rect.Y + $rect.Height / 2
    } else {
        $x = $bounds.x + [double]$request.x
        $y = $bounds.y + [double]$request.y
    }
    if ([double]::IsNaN($x) -or [double]::IsInfinity($x) -or [double]::IsNaN($y) -or [double]::IsInfinity($y) -or
        $x -lt $bounds.x -or $x -ge ($bounds.x + $bounds.width) -or $y -lt $bounds.y -or $y -ge ($bounds.y + $bounds.height)) {
        throw "[click.target_invalid] The pointer location is outside the observed window"
    }
    return [pscustomobject]@{ x = [int][math]::Round($x); y = [int][math]::Round($y) }
}

function Get-InputPattern($process, $element) {
    Assert-ElementWindow $process $element
    if ($null -eq $element -or $element.Current.ProcessId -ne $process.Id) {
        throw "[input.target_invalid] The target does not belong to the observed process"
    }
    $type = $element.Current.ControlType
    if ($type -ne [Windows.Automation.ControlType]::Edit -and $type -ne [Windows.Automation.ControlType]::Document) {
        throw "[input.unsupported] The target is not an editable text control"
    }
    $pattern = Get-CurrentPatternOrNull $element ([Windows.Automation.ValuePattern]::Pattern)
    if ($null -eq $pattern -or $pattern.Current.IsReadOnly -or -not $element.Current.IsEnabled) {
        throw "[input.not_writable] A writable text ValuePattern is unavailable"
    }
    return $pattern
}

function Read-InputText($pattern) {
    try { return [string]$pattern.Current.Value }
    catch { throw "[input.verification_unavailable] Cannot read the target's full text value" }
}

function Confirm-InputValue($pattern, [string]$expected) {
    $timeout = [int]$operation.verification_timeout_ms
    if ($timeout -le 0) { $timeout = $script:InputVerificationDefaultTimeoutMS }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $matched = $false
    $reason = "unreadable"
    do {
        try {
            $actual = Read-InputText $pattern
            $matched = [string]::Equals($actual, $expected, [StringComparison]::Ordinal)
            $reason = "readback_mismatch"
            if ($matched) { break }
        } catch { $reason = "unreadable" }
        $remaining = $timeout - $clock.ElapsedMilliseconds
        if ($remaining -le 0) { break }
        Start-Sleep -Milliseconds ([int][math]::Min($script:InputVerificationPollMS, $remaining))
    } while ($true)
    $script:InputResult = @{ delivery = "returned_success"; verification = "unconfirmed"; reason = $reason }
    $script:Diagnostics.Add("input verification expected_length=$($expected.Length) exact_match=$matched elapsed_ms=$($clock.ElapsedMilliseconds)")
    if (-not $matched) {
        throw "[input.verification_unconfirmed] The write returned success, but read-only verification did not confirm the expected text. Effects may have occurred. Run get_app_state; do not automatically replay."
    }
    $script:InputResult = @{ delivery = "returned_success"; verification = "value_verified" }
}

function Invoke-TypeText($process, $element, [string]$text) {
    $method = [string]$operation.input_method
    if ([string]::IsNullOrEmpty($method)) { $method = "accessibility" }
    if ($method -notin @("accessibility", "keyboard")) { throw "Unknown input_method" }
    $target = $script:InputTarget
    $pattern = Get-InputPattern $process $element
    Assert-InputSelection $pattern $target
    $before = [string]$target.value
    [int]$start = $target.selection_start
    [int]$end = $start + $target.selection_length
    $expected = $before.Substring(0, $start) + $text + $before.Substring($end)
    if ($method -eq "keyboard") { $handle = Set-BackgroundSelection $process $element $target }
    $script:Diagnostics.Add("input target_pid=$($element.Current.ProcessId) selection_start=$start selection_end=$end before_length=$($before.Length) expected_length=$($expected.Length) method=$method")
    $target.selection_start = $null
    $target.selection_length = $null
    $script:InputResult = @{ delivery = "unknown"; verification = "unconfirmed" }
    try {
        if ($method -eq "keyboard") {
            Send-Text $handle $text { [void](Get-BackgroundInputHandle $process $element) }
        } else {
            $pattern.SetValue($expected)
        }
    } catch { throw "[input.write_failed] Input delivery may be partial; observe before any further write." }
    Confirm-InputValue $pattern $expected
    $target.value = $expected
    $target.selection_start = $start + $text.Length
    $target.selection_length = 0
}

# Read the operation file as UTF-8 explicitly. Windows PowerShell 5.1's
# Get-Content defaults to the system ANSI code page (e.g. GBK on Chinese
# systems) for files without a BOM, which corrupts non-ASCII input such as
# Chinese text passed to set_value/type_text.
$operationJson = [System.IO.File]::ReadAllText($OperationPath, [System.Text.Encoding]::UTF8)
$operation = $operationJson | ConvertFrom-Json

try {
    if ($operation.tool -eq "list_apps") {
        $response = [pscustomobject]@{ ok = $true; text = (List-Apps) }
    } elseif ($operation.tool -eq "get_app_state") {
        $response = [pscustomobject]@{ ok = $true; snapshot = (Build-Snapshot $operation.app (Resolve-TextLimit $operation.text_limit) ([int]$operation.max_tree_nodes) ([int]$operation.max_tree_depth)) }
    } else {
        $process = Resolve-App $operation.app
        Assert-ObservedWindow $process $operation
        $script:Diagnostics.Add("request observation=$($operation.observation_id) tool=$($operation.tool) pid=$($process.Id) hwnd=$($process.MainWindowHandle)")
        $hwnd = [IntPtr]$process.MainWindowHandle
        $windowBounds = $operation.windowBounds
        if ($operation.tool -in @("type_text", "set_value", "set_input_target", "press_key")) {
            if ($process.Id -ne $operation.target_pid) { throw "[input.target_invalid] The observed application process has changed" }
            $element = Resolve-InputElement $process $operation.element
            if ($null -eq $element) { throw "[input.target_required] Bind an observed editable target; system focus is not used" }
            if ($null -ne $operation.input_target) {
                $script:InputTarget = $operation.input_target
                if ($script:InputTarget.pid -ne $process.Id -or $script:InputTarget.window_handle -ne [long]$process.MainWindowHandle -or
                    -not (Same-RuntimeId @($script:InputTarget.element.runtimeId) @($element.GetRuntimeId()))) {
                    $script:InputTarget = $null
                    throw "[input.target_invalid] The bound CU input identity changed"
                }
            } else {
                $script:InputTarget = New-InputTarget $process $element
            }
        } else {
            $element = Find-Element $process $operation.element
        }

        switch ($operation.tool) {
            "click" {
                $clickMethod = [string]$operation.click_method
                if ([string]::IsNullOrWhiteSpace($clickMethod)) { $clickMethod = "auto" }
                if ($clickMethod -notin @("auto", "accessibility", "app_post")) { throw "Unsupported click_method" }
                $handled = $false
                if ($null -ne $element) {
                    Assert-ElementWindow $process $element
                    $script:Diagnostics.Add("click requested_runtime_id=$($operation.element.runtimeId -join ',') actual_runtime_id=$($element.GetRuntimeId() -join ',')")
                    if ($clickMethod -ne "app_post" -and $operation.mouse_button -notin @("right", "middle")) {
                        $handled = Invoke-PreferredClick $element
                    }
                }
                if (-not $handled) {
                    if ($clickMethod -eq "accessibility") { throw "[click.unsupported] The requested element does not support this click" }
                    $point = Get-ClickPoint $process $operation $element
                    $receiver = $hwnd
                    if ($null -ne $element -and $element.Current.NativeWindowHandle -ne 0) { $receiver = [IntPtr]$element.Current.NativeWindowHandle }
                    $script:Diagnostics.Add("click dispatch=window_messages hwnd=$receiver screen_x=$($point.x) screen_y=$($point.y)")
                    Send-MouseClick $receiver $point.x $point.y $operation.mouse_button ([int]$operation.click_count)
                } else {
                    $script:Diagnostics.Add("click dispatch=UIA requested_element_only")
                }
            }
            "perform_secondary_action" {
                if ($null -eq $element) { throw "unknown element_index '$($operation.element.index)'" }
                Invoke-SecondaryAction $element $operation.action
            }
            "scroll" {
                $handled = $false
                if ($null -ne $element) {
                    $handled = Invoke-Scroll $element $operation.direction ([double]$operation.pages)
                }
                if (-not $handled) {
                    $point = Get-ScreenPoint $operation.element.frame $windowBounds
                    Send-Scroll $hwnd $point.x $point.y $operation.direction ([double]$operation.pages)
                }
            }
            "drag" {
                Send-Drag $hwnd ([int][math]::Round($windowBounds.x + [double]$operation.from_x)) ([int][math]::Round($windowBounds.y + [double]$operation.from_y)) ([int][math]::Round($windowBounds.x + [double]$operation.to_x)) ([int][math]::Round($windowBounds.y + [double]$operation.to_y))
            }
            "set_input_target" {
                $script:Diagnostics.Add("input target_bound pid=$($process.Id) hwnd=$($process.MainWindowHandle) selection_start=$($script:InputTarget.selection_start) selection_length=$($script:InputTarget.selection_length)")
            }
            "type_text" {
                Invoke-TypeText $process $element $operation.text
            }
            "press_key" {
                if (([string]$operation.key).Contains("+")) {
                    throw "[input.background_unsupported] Window messages cannot establish independent modifier-key state; use a semantic action"
                }
                $pattern = Get-InputPattern $process $element
                Assert-InputSelection $pattern $script:InputTarget
                $receiver = Set-BackgroundSelection $process $element $script:InputTarget
                $script:InputTarget.selection_start = $null
                $script:InputTarget.selection_length = $null
                $script:InputResult = @{ delivery = "unknown"; verification = "unconfirmed"; reason = "key_consumption_unobservable" }
                Send-Key $receiver $operation.key
            }
            "set_value" {
                $pattern = Get-InputPattern $process $element
                $script:InputTarget.selection_start = $null
                $script:InputTarget.selection_length = $null
                $script:InputResult = @{ delivery = "unknown"; verification = "unconfirmed" }
                try { $pattern.SetValue([string]$operation.value) }
                catch { throw "[input.write_failed] ValuePattern.SetValue failed; do not automatically replay" }
                Confirm-InputValue $pattern ([string]$operation.value)
                $script:InputTarget.value = [string]$operation.value
                $script:InputTarget.selection_start = ([string]$operation.value).Length
                $script:InputTarget.selection_length = 0
            }
            default {
                throw "unsupportedTool(`"$($operation.tool)`")"
            }
        }

        Start-Sleep -Milliseconds 120
        $response = [pscustomobject]@{ ok = $true; snapshot = (Build-Snapshot $operation.app) }
    }
} catch {
    $message = $_.Exception.Message
    if (-not [string]::IsNullOrWhiteSpace($_.ScriptStackTrace)) {
        $message = "$message at $($_.ScriptStackTrace)"
    }
    $response = [pscustomobject]@{ ok = $false; error = $message }
}

$response | Add-Member -NotePropertyName input_target -NotePropertyValue $script:InputTarget
$response | Add-Member -NotePropertyName input_result -NotePropertyValue $script:InputResult
$response | Add-Member -NotePropertyName diagnostics -NotePropertyValue @($script:Diagnostics.ToArray())
$response | ConvertTo-Json -Depth 50 -Compress
