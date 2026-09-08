param(
    [Parameter(Mandatory = $true)]
    [string]$OperationPath
)

$ErrorActionPreference = "Stop"
$DefaultTextLimit = 500
$AccessibilityTreeMaxNodeCount = 1200
$AccessibilityTreeMaxDepth = 64
$KeyboardReceiverTimeoutMS = 1000
$KeyboardReceiverPollMS = 50
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
using System.Text;
using System.Runtime.InteropServices;

public static class OCUWin32 {
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT {
        public uint type;
        public INPUTUNION data;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct INPUTUNION {
        [FieldOffset(0)] public MOUSEINPUT mouse;
        [FieldOffset(0)] public KEYBDINPUT keyboard;
        [FieldOffset(0)] public HARDWAREINPUT hardware;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT {
        public int dx, dy;
        public uint mouseData, flags, time;
        public UIntPtr extraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT {
        public ushort virtualKey, scanCode;
        public uint flags, time;
        public UIntPtr extraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct HARDWAREINPUT {
        public uint message;
        public ushort paramLow, paramHigh;
    }

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
    public static extern IntPtr ChildWindowFromPointEx(IntPtr parent, POINT point, uint flags);

    [DllImport("user32.dll")]
    public static extern bool IsChild(IntPtr parent, IntPtr child);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int command);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint count, INPUT[] inputs, int size);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);

    [DllImport("user32.dll")]
    public static extern bool ScreenToClient(IntPtr hWnd, ref POINT point);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool PostMessage(IntPtr hWnd, UInt32 msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessage(IntPtr hWnd, UInt32 msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", EntryPoint = "SendMessageW")]
    public static extern IntPtr ReadEditSelection(IntPtr hWnd, UInt32 msg, out uint start, out uint end);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessage(IntPtr hWnd, UInt32 msg, IntPtr wParam, string lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "SendMessageW")]
    public static extern IntPtr SendMessageText(IntPtr hWnd, UInt32 msg, IntPtr wParam, StringBuilder lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hwnd, StringBuilder name, int capacity);

    [DllImport("user32.dll")]
    public static extern uint MapVirtualKey(uint code, uint mapType);

    public static bool SendUnicodeUnit(ushort codeUnit, bool released) {
        var input = new INPUT {
            type = 1,
            data = new INPUTUNION {
                keyboard = new KEYBDINPUT {
                    virtualKey = 0,
                    scanCode = codeUnit,
                    flags = released ? 0x0006u : 0x0004u
                }
            }
        };
        return SendInput(1, new[] { input }, Marshal.SizeOf(typeof(INPUT))) == 1;
    }

    public static bool SendVirtualKey(ushort virtualKey, bool released) {
        var input = new INPUT {
            type = 1,
            data = new INPUTUNION {
                keyboard = new KEYBDINPUT {
                    virtualKey = virtualKey,
                    flags = released ? 0x0002u : 0u
                }
            }
        };
        return SendInput(1, new[] { input }, Marshal.SizeOf(typeof(INPUT))) == 1;
    }

    public static IntPtr KeyLParam(uint key, bool released) {
        uint scan = MapVirtualKey(key, 4); // MAPVK_VK_TO_VSC_EX
        uint bits = 1 | ((scan & 0xff) << 16);
        if ((scan & 0xff00) == 0xe000) bits |= 1u << 24;
        if (released) bits |= (1u << 30) | (1u << 31);
        return new IntPtr(unchecked((int)bits));
    }
}
"@

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
$EM_SETSEL = 0x00B1
function Assert-ForegroundKeyboardInput([bool]$sent) {
    if (-not $sent) {
        throw "[input.write_failed] Foreground keyboard injection failed or was blocked by UIPI"
    }
}

function Send-ForegroundText([string]$text, [scriptblock]$validateTarget) {
    foreach ($char in $text.Replace("`r`n", "`r").Replace("`n", "`r").ToCharArray()) {
        if ($null -ne $validateTarget) { & $validateTarget }
        Assert-ForegroundKeyboardInput ([OCUWin32]::SendUnicodeUnit([uint16][char]$char, $false))
        Assert-ForegroundKeyboardInput ([OCUWin32]::SendUnicodeUnit([uint16][char]$char, $true))
    }
}

function Send-ForegroundKey([string]$key) {
    $virtualKey = [uint16](Get-VirtualKey $key)
    Assert-ForegroundKeyboardInput ([OCUWin32]::SendVirtualKey($virtualKey, $false))
    Assert-ForegroundKeyboardInput ([OCUWin32]::SendVirtualKey($virtualKey, $true))
}

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

function Get-WindowPointerHandle([IntPtr]$window, [int]$screenX, [int]$screenY) {
    # Search only the target hierarchy; desktop hit-testing would select a covering app.
    $receiver = $window
    while ($true) {
        $point = New-Object OCUWin32+POINT
        $point.X = $screenX
        $point.Y = $screenY
        if (-not [OCUWin32]::ScreenToClient($receiver, [ref]$point)) { throw "[click.target_invalid] Target window disappeared" }
        $child = [OCUWin32]::ChildWindowFromPointEx($receiver, $point, 7)
        if ($child -eq [IntPtr]::Zero -or $child -eq $receiver) { return $receiver }
        $receiver = $child
    }
}

function Send-WindowMessage([IntPtr]$hwnd, [uint32]$message, [IntPtr]$wParam, [IntPtr]$lParam) {
    Assert-ObservedWindow $process $operation
    [uint32]$owner = 0
    [void][OCUWin32]::GetWindowThreadProcessId($hwnd, [ref]$owner)
    $window = [IntPtr]$operation.window_handle
    if ($owner -ne $operation.target_pid -or ($hwnd -ne $window -and -not [OCUWin32]::IsChild($window, $hwnd))) {
        throw "[input.target_invalid] Message receiver is outside the observed window"
    }
    if (-not [OCUWin32]::PostMessage($hwnd, $message, $wParam, $lParam)) {
        throw "[input.write_failed] Window message delivery failed; earlier events may have been delivered"
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
        Send-WindowMessage ($hwnd) ($WM_MOUSEMOVE) ([IntPtr]::Zero) ($lParam)
        Send-WindowMessage ($hwnd) ($down) ([IntPtr]$downFlag) ($lParam)
        Start-Sleep -Milliseconds 35
        Send-WindowMessage ($hwnd) ($up) ([IntPtr]::Zero) ($lParam)
        Start-Sleep -Milliseconds 50
    }
}

function Send-Drag([IntPtr]$hwnd, [int]$fromX, [int]$fromY, [int]$toX, [int]$toY) {
    $bounds = $operation.windowBounds
    foreach ($point in @(@{x=$fromX; y=$fromY}, @{x=$toX; y=$toY})) {
        if ($point.x -lt $bounds.x -or $point.x -ge ($bounds.x + $bounds.width) -or
            $point.y -lt $bounds.y -or $point.y -ge ($bounds.y + $bounds.height)) {
            throw "[click.target_invalid] Drag endpoints must be inside the bound window"
        }
    }
    $hwnd = Get-WindowPointerHandle $hwnd $fromX $fromY
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
    Send-WindowMessage ($hwnd) ($WM_MOUSEMOVE) ([IntPtr]::Zero) ($startParam)
    Send-WindowMessage ($hwnd) ($WM_LBUTTONDOWN) ([IntPtr]1) ($startParam)
    for ($i = 1; $i -le $steps; $i++) {
        $x = [int][math]::Round($start.X + (($end.X - $start.X) * $i / $steps))
        $y = [int][math]::Round($start.Y + (($end.Y - $start.Y) * $i / $steps))
        Send-WindowMessage ($hwnd) ($WM_MOUSEMOVE) ([IntPtr]1) ((ConvertTo-LParam $x $y))
        Start-Sleep -Milliseconds 20
    }
    Send-WindowMessage ($hwnd) ($WM_LBUTTONUP) ([IntPtr]::Zero) ((ConvertTo-LParam $end.X $end.Y))
}

function Send-Scroll([IntPtr]$hwnd, [int]$screenX, [int]$screenY, [string]$direction, [double]$pages) {
    $hwnd = Get-WindowPointerHandle $hwnd $screenX $screenY
    # Wheel messages take screen coordinates, unlike button messages.
    $lParam = ConvertTo-LParam $screenX $screenY
    $delta = [int][math]::Round(120 * $pages)
    $message = $WM_MOUSEWHEEL
    if ($direction -eq "down" -or $direction -eq "left") {
        $delta = -1 * $delta
    }
    if ($direction -eq "left" -or $direction -eq "right") {
        $message = $WM_MOUSEHWHEEL
    }
    $script:Diagnostics.Add("scroll dispatch=window_messages hwnd=$hwnd screen_x=$screenX screen_y=$screenY")
    Send-WindowMessage ($hwnd) ($message) ((ConvertTo-WheelWParam $delta)) ($lParam)
}

function Send-Text([IntPtr]$hwnd, [string]$text, [scriptblock]$validateTarget) {
    # WM_CHAR uses carriage return for Enter, including multiline edit controls.
    foreach ($char in $text.Replace("`r`n", "`r").Replace("`n", "`r").ToCharArray()) {
        if ($null -ne $validateTarget) { & $validateTarget }
        Send-WindowMessage $hwnd $WM_CHAR ([IntPtr][int][char]$char) ([IntPtr]1)
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
    Send-WindowMessage $hwnd $WM_KEYDOWN ([IntPtr]$vk) ([OCUWin32]::KeyLParam($vk, $false))
    Send-WindowMessage $hwnd $WM_KEYUP ([IntPtr]$vk) ([OCUWin32]::KeyLParam($vk, $true))

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

function Capture-WindowPngBase64([IntPtr]$hwnd, $bounds) {
    if ($null -eq $bounds -or $bounds.width -le 0 -or $bounds.height -le 0) {
        return $null
    }
    $bitmap = $null
    $graphics = $null
    $stream = $null
    try {
        if ([OCUWin32]::IsIconic($hwnd)) { throw "Target window is minimized" }
        $bitmap = New-Object System.Drawing.Bitmap ([int][math]::Round($bounds.width)), ([int][math]::Round($bounds.height))
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $hdc = $graphics.GetHdc()
        try {
            # PW_RENDERFULLCONTENT: capture this HWND, never the covering desktop.
            if (-not [OCUWin32]::PrintWindow($hwnd, $hdc, 0x00000002)) {
                throw "PrintWindow failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
            }
        } finally { $graphics.ReleaseHdc($hdc) }
        $current = Get-WindowRectFrame $hwnd
        if ($null -eq $current) { throw "Target window disappeared during capture" }
        foreach ($field in @("x", "y", "width", "height")) {
            if ($current.$field -ne $bounds.$field) { throw "Window geometry changed during capture" }
        }
        $stream = New-Object System.IO.MemoryStream
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        $bytes = $stream.ToArray()
        return [Convert]::ToBase64String($bytes)
    } catch {
        $script:Diagnostics.Add("capture unavailable hwnd=$hwnd reason=$($_.Exception.Message)")
        return $null
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $graphics) { $graphics.Dispose() }
        if ($null -ne $bitmap) { $bitmap.Dispose() }
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
        screenshotPngBase64 = Capture-WindowPngBase64 ([IntPtr]$process.MainWindowHandle) $bounds
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

function Assert-KeyboardControl($process, $element) {
    Assert-ElementWindow $process $element
    if (-not $element.Current.IsEnabled) {
        throw "[input.unsupported] The requested input target is disabled"
    }
    return Get-BackgroundInputHandle $process $element
}

function Assert-ReplacementProtocol([IntPtr]$handle) {
    # EM_SETSEL is an Edit/RichEdit protocol, not a generic HWND operation.
    $name = New-Object System.Text.StringBuilder 256
    if ([OCUWin32]::GetClassName($handle, $name, $name.Capacity) -eq 0) {
        throw "[input.target_invalid] Cannot identify the native input control"
    }
    if ($name.ToString() -ne "Edit" -and $name.ToString() -notlike "RichEdit*") {
        throw "[input.replacement_unsupported] The receiver does not expose native selection; use type_text at an explicitly selected position. No keys were sent."
    }
}

function Get-WindowKeyboardHandle($process) {
    $window = [IntPtr]$process.MainWindowHandle
    [uint32]$owner = 0
    $thread = [OCUWin32]::GetWindowThreadProcessId($window, [ref]$owner)
    $info = New-Object OCUWin32+GUITHREADINFO
    $info.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($info)
    if (-not [OCUWin32]::GetGUIThreadInfo($thread, [ref]$info)) { return [IntPtr]::Zero }
    $handle = $info.hwndFocus
    if ($handle -eq [IntPtr]::Zero -or
        ($handle -ne $window -and -not [OCUWin32]::IsChild($window, $handle))) { return [IntPtr]::Zero }
    [void][OCUWin32]::GetWindowThreadProcessId($handle, [ref]$owner)
    if ($owner -ne $process.Id) { return [IntPtr]::Zero }
    return $handle
}

function Get-InputHandle($process, $element) {
    Assert-ObservedWindow $process $operation
    if ($script:InputTarget.scope -ne "window") { return Assert-KeyboardControl $process $element }
    $target = $script:InputTarget
    if ($null -ne $element) { [void](Resolve-PointerPoint $process $operation $element "input") }
    $current = Get-WindowBounds $process (Get-MainElement $process)
    if ($target.pid -ne $process.Id -or $target.window_handle -ne [long]$process.MainWindowHandle) {
        throw "[input.target_invalid] The bound window identity changed"
    }
    foreach ($field in @("x", "y", "width", "height")) {
        if ($current.$field -ne $target.bounds.$field) { throw "[input.target_invalid] Window geometry changed; bind the position again" }
    }
    $handle = Get-WindowKeyboardHandle $process
    if ($handle -eq [IntPtr]::Zero) {
        throw "[input.receiver_unconfirmed] Window focus changed; bind the input position again"
    }
    if ([long]$target.keyboard_handle -eq 0) {
        $target.keyboard_handle = [long]$handle
    } elseif ([long]$handle -ne $target.keyboard_handle) {
        throw "[input.receiver_unconfirmed] Window focus changed; bind the input position again"
    }
    return $handle
}

function Enter-ForegroundInputLease($process) {
    $target = [IntPtr]$process.MainWindowHandle
    $previous = [OCUWin32]::GetForegroundWindow()
    $wasMinimized = [OCUWin32]::IsIconic($target)
    $lease = [pscustomobject]@{ target = [long]$target; previous = [long]$previous; target_was_minimized = $wasMinimized }
    try {
        if ($wasMinimized) { [void][OCUWin32]::ShowWindowAsync($target, 9) }
        [void][OCUWin32]::SetForegroundWindow($target)
        $clock = [Diagnostics.Stopwatch]::StartNew()
        do {
            Start-Sleep -Milliseconds $KeyboardReceiverPollMS
        } while ([OCUWin32]::GetForegroundWindow() -ne $target -and $clock.ElapsedMilliseconds -lt $KeyboardReceiverTimeoutMS)
        if ([OCUWin32]::GetForegroundWindow() -ne $target) {
            throw "[input.activation_failed] The target application did not become active"
        }
        $script:Diagnostics.Add("focus lease acquire target_hwnd=$target previous_hwnd=$previous")
        return $lease
    } catch {
        Exit-ForegroundInputLease $lease
        throw
    }
}

function Exit-ForegroundInputLease($lease) {
    if ($null -eq $lease) { return }
    $target = [IntPtr][long]$lease.target
    if ([OCUWin32]::GetForegroundWindow() -ne $target) {
        $script:Diagnostics.Add("focus lease restore skipped because foreground ownership changed")
    } else {
        $previous = [IntPtr][long]$lease.previous
        if ($previous -ne [IntPtr]::Zero -and [OCUWin32]::IsWindow($previous)) {
            $restored = [OCUWin32]::SetForegroundWindow($previous)
            $script:Diagnostics.Add("focus lease restore previous_hwnd=$previous requested=$restored")
        }
    }
    if ($lease.target_was_minimized -and [OCUWin32]::IsWindow($target)) {
        [void][OCUWin32]::ShowWindowAsync($target, 6)
    }
}

function Reestablish-LeasedInputTarget($process, $element) {
    if ([OCUWin32]::GetForegroundWindow() -ne [IntPtr]$process.MainWindowHandle) {
        throw "[input.interrupted_by_user] Foreground ownership changed before input"
    }
    if ($script:InputTarget.scope -eq "element") {
        $element.SetFocus()
    } else {
        $point = [pscustomobject]@{ x = [int]$script:InputTarget.point_x; y = [int]$script:InputTarget.point_y }
        $receiver = Get-WindowPointerHandle ([IntPtr]$process.MainWindowHandle) $point.x $point.y
        Send-MouseClick $receiver $point.x $point.y "left" 1
    }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    do {
        Start-Sleep -Milliseconds $KeyboardReceiverPollMS
        try { return Get-InputHandle $process $element } catch { $lastError = $_ }
    } while ($clock.ElapsedMilliseconds -lt $KeyboardReceiverTimeoutMS)
    throw $lastError
}

function Assert-ForegroundInputLease($process) {
    if ([OCUWin32]::GetForegroundWindow() -ne [IntPtr]$process.MainWindowHandle) {
        throw "[input.interrupted_by_user] Foreground ownership changed during input"
    }
}

function Get-InputCapability($process, $element) {
    try {
        return [pscustomobject]@{ handle = (Get-InputHandle $process $element); mode = "directed_background"; lease = $null }
    } catch {
        if ($_.Exception.Message -notmatch '^\[input\.(receiver_unconfirmed|background_unsupported)\]') { throw }
    }
    $script:InputResult.input_mode = "foreground_lease"
    $lease = Enter-ForegroundInputLease $process
    try {
        $handle = Reestablish-LeasedInputTarget $process $element
        return [pscustomobject]@{ handle = $handle; mode = "foreground_lease"; lease = $lease }
    } catch {
        Exit-ForegroundInputLease $lease
        throw
    }
}

function Read-NativeEditText([IntPtr]$handle) {
    $length = [OCUWin32]::SendMessage($handle, 0x000E, [IntPtr]::Zero, [IntPtr]::Zero).ToInt32()
    if ($length -lt 0) { return $null }
    $buffer = New-Object System.Text.StringBuilder ($length + 1)
    [void][OCUWin32]::SendMessageText($handle, 0x000D, [IntPtr]($length + 1), $buffer)
    return $buffer.ToString()
}

function Confirm-NativeEditValue([IntPtr]$handle, [string]$expected, $process, $lease) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    do {
        if ($null -ne $lease) { Assert-ForegroundInputLease $process }
        $actual = Read-NativeEditText $handle
        if ($null -ne $actual -and $actual -ceq $expected) {
            $script:Diagnostics.Add("input readback matched length=$($actual.Length)")
            return $true
        }
        Start-Sleep -Milliseconds $KeyboardReceiverPollMS
    } while ($clock.ElapsedMilliseconds -lt $KeyboardReceiverTimeoutMS)
    $script:Diagnostics.Add("input readback unavailable_or_mismatch expected_length=$($expected.Length)")
    return $false
}

function New-InputTarget($process, $element) {
    if ($null -ne $element) {
        Assert-ElementWindow $process $element
        if (-not $element.Current.IsEnabled) { throw "[input.unsupported] The requested input target is disabled" }
        $textPattern = Get-CurrentPatternOrNull $element ([Windows.Automation.TextPattern]::Pattern)
        $valuePattern = Get-CurrentPatternOrNull $element ([Windows.Automation.ValuePattern]::Pattern)
        if ($element.Current.NativeWindowHandle -ne 0 -and ($null -ne $textPattern -or $null -ne $valuePattern)) {
            [void](Assert-KeyboardControl $process $element)
            return [pscustomobject]@{ pid = $process.Id; window_handle = [long]$process.MainWindowHandle;
                element = $operation.element; scope = "element" }
        }
    }
    if ($null -eq $element -and ($operation.tool -ne "set_input_target" -or $null -eq $operation.x -or $null -eq $operation.y)) {
        throw "[input.target_required] Provide an editable element or bind a screenshot position with set_input_target"
    }
    $point = Resolve-PointerPoint $process $operation $element "input"
    $window = [IntPtr]$process.MainWindowHandle
    $clock = [Diagnostics.Stopwatch]::StartNew()
    Assert-ObservedWindow $process $operation
    $pointerHandle = Get-WindowPointerHandle $window $point.x $point.y
    [uint32]$pointerOwner = 0
    [void][OCUWin32]::GetWindowThreadProcessId($pointerHandle, [ref]$pointerOwner)
    if ($pointerOwner -ne $process.Id -or
        ($pointerHandle -ne $window -and -not [OCUWin32]::IsChild($window, $pointerHandle))) {
        throw "[input.target_invalid] The input position is not in the target window"
    }
    Send-MouseClick $pointerHandle $point.x $point.y "left" 1
    $clock.Restart()
    do {
        Start-Sleep -Milliseconds $KeyboardReceiverPollMS
        $handle = Get-WindowKeyboardHandle $process
    } while ($handle -eq [IntPtr]::Zero -and $clock.ElapsedMilliseconds -lt $KeyboardReceiverTimeoutMS)
    if ($handle -eq [IntPtr]::Zero) { $handle = [IntPtr]::Zero }
    $script:Diagnostics.Add("input scope=window window=$window keyboard_handle=$handle editable_receiver=unobservable")
    return [pscustomobject]@{ pid = $process.Id; window_handle = [long]$window; element = $operation.element;
        scope = "window"; keyboard_handle = [long]$handle; point_x = $point.x; point_y = $point.y; bounds = $operation.windowBounds }
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

function Resolve-PointerPoint($process, $request, $element, [string]$action) {
    Assert-ObservedWindow $process $request
    $bounds = $request.windowBounds
    if ($null -ne $request.element) {
        Assert-ElementWindow $process $element
        $rect = $element.Current.BoundingRectangle
        $saved = $request.element.frame
        $script:Diagnostics.Add("pointer geometry observed=$($saved | ConvertTo-Json -Compress) current=$rect")
        if ($rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0 -or $element.Current.IsOffscreen) {
            throw "[$action.position_unavailable] The identified control has no usable current position inside this window"
        }
        $x = $rect.X + $rect.Width / 2
        $y = $rect.Y + $rect.Height / 2
    } else {
        $x = $bounds.x + [double]$request.x
        $y = $bounds.y + [double]$request.y
    }
    if ([double]::IsNaN($x) -or [double]::IsInfinity($x) -or [double]::IsNaN($y) -or [double]::IsInfinity($y) -or
        $x -lt $bounds.x -or $x -ge ($bounds.x + $bounds.width) -or $y -lt $bounds.y -or $y -ge ($bounds.y + $bounds.height)) {
        throw "[$action.target_invalid] The pointer location is outside the observed window"
    }
    return [pscustomobject]@{ x = [int][math]::Round($x); y = [int][math]::Round($y) }
}

function Invoke-TypeText($process, $element, [string]$text, [bool]$replace = $false) {
    $capability = $null
    $lease = $null
    $script:InputResult = @{ delivery = "not_sent"; verification = "unconfirmed"; reason = "input_setup_failed" }
    $deliveryStarted = $false
    try {
        $capability = Get-InputCapability $process $element
        $handle = $capability.handle
        $lease = $capability.lease
        $script:InputResult.input_mode = $capability.mode
        $script:Diagnostics.Add("input target_pid=$($process.Id) scope=$($script:InputTarget.scope) hwnd=$handle replace=$replace submitted_length=$($text.Length) mode=$($capability.mode)")
        if ($replace) { Assert-ReplacementProtocol $handle }
        if ($replace) {
            # Native edit protocol selects all independently of UIA's document proxy.
            [void][OCUWin32]::SendMessage($handle, $EM_SETSEL, [IntPtr]::Zero, [IntPtr](-1))
            [uint32]$selectionStart = 0
            [uint32]$selectionEnd = 0
            # EM_GETSEL uses pointer outputs to avoid its 16-bit packed return limit.
            [void][OCUWin32]::ReadEditSelection($handle, 0x00B0, [ref]$selectionStart, [ref]$selectionEnd)
            $length = [OCUWin32]::SendMessage($handle, 0x000E, [IntPtr]::Zero, [IntPtr]::Zero).ToInt64()
            $script:Diagnostics.Add("input replacement length=$length selection_start=$selectionStart selection_end=$selectionEnd")
            if ($selectionStart -ne 0 -or $selectionEnd -ne $length) {
                throw "[input.selection_unconfirmed] Native Select All was not confirmed. No replacement text was sent. Do not retry by inserting text."
            }
        }
        [void](Get-InputHandle $process $element)
        if ($null -ne $lease) { Assert-ForegroundInputLease $process }
        $deliveryStarted = $true
        if ($replace -and $text.Length -eq 0) {
            if ($null -ne $lease) { Send-ForegroundKey "BackSpace" } else { Send-Key $handle "BackSpace" }
        } elseif ($text.Length -gt 0) {
            if ($null -ne $lease) {
                Send-ForegroundText $text { Assert-ForegroundInputLease $process; [void](Get-InputHandle $process $element) }
            } else {
                Send-Text $handle $text { [void](Get-InputHandle $process $element) }
            }
        }
        $verification = if ($replace -and (Confirm-NativeEditValue $handle $text $process $lease)) { "value_verified" } else { "unconfirmed" }
    } catch {
        $script:InputTarget = $null
        if (-not $deliveryStarted -or $_.Exception.Message.StartsWith("[input.selection_unconfirmed]")) {
            $inputMode = if ($null -ne $capability) { $capability.mode } else { $script:InputResult.input_mode }
            $reason = if ($replace -and $_.Exception.Message.StartsWith("[input.selection_unconfirmed]")) { "replacement_precondition_failed" } else { "input_setup_failed" }
            $script:InputResult = @{ delivery = "not_sent"; verification = "unconfirmed"; reason = $reason }
            if (-not [string]::IsNullOrWhiteSpace($inputMode)) { $script:InputResult.input_mode = $inputMode }
            throw
        }
        $script:InputResult = @{ delivery = "unknown"; verification = "unconfirmed"; reason = "dispatch_interrupted" }
        if ($null -ne $capability) { $script:InputResult.input_mode = $capability.mode }
        throw "[input.delivery_interrupted] Keyboard delivery may be partial; observe before any further action. Cause: $($_.Exception.Message)"
    } finally {
        Exit-ForegroundInputLease $lease
    }
    $reason = if ($verification -eq "value_verified") { "value_readback_matched" } else { "keyboard_consumption_unobservable" }
    $script:InputResult = @{ delivery = "posted"; verification = $verification; reason = $reason; target_scope = $script:InputTarget.scope; input_mode = $capability.mode }
}

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
            $element = $null
            if ($null -ne $operation.element) { $element = Resolve-InputElement $process $operation.element }
            if ($null -ne $operation.input_target) {
                $script:InputTarget = $operation.input_target
                if ($script:InputTarget.pid -ne $process.Id -or $script:InputTarget.window_handle -ne [long]$process.MainWindowHandle -or
                    ($script:InputTarget.scope -ne "window" -and ($null -eq $element -or -not (Same-RuntimeId @($script:InputTarget.element.runtimeId) @($element.GetRuntimeId()))))) {
                    $script:InputTarget = $null
                    throw "[input.target_invalid] The bound CU input identity changed"
                }
            } else {
                $script:InputTarget = New-InputTarget $process $element
            }
        } else {
            $element = Find-Element $process $operation.element
            if ($null -ne $element) { Assert-ElementWindow $process $element }
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
                    $point = Resolve-PointerPoint $process $operation $element "click"
                    $receiver = Get-WindowPointerHandle $hwnd $point.x $point.y
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
                if ($handled) {
                    $script:Diagnostics.Add("scroll dispatch=UIA requested_element_only")
                } else {
                    $point = Resolve-PointerPoint $process $operation $element "scroll"
                    Send-Scroll $hwnd $point.x $point.y $operation.direction ([double]$operation.pages)
                }
            }
            "drag" {
                Send-Drag $hwnd ([int][math]::Round($windowBounds.x + [double]$operation.from_x)) ([int][math]::Round($windowBounds.y + [double]$operation.from_y)) ([int][math]::Round($windowBounds.x + [double]$operation.to_x)) ([int][math]::Round($windowBounds.y + [double]$operation.to_y))
            }
            "set_input_target" {
                $script:Diagnostics.Add("input target_bound pid=$($process.Id) hwnd=$($process.MainWindowHandle) scope=$($script:InputTarget.scope)")
                $script:InputResult = @{ target_scope = $script:InputTarget.scope; verification = "unconfirmed" }
            }
            "type_text" {
                Invoke-TypeText $process $element $operation.text
            }
            "press_key" {
                if (([string]$operation.key).Contains("+")) {
                    throw "[input.unsupported] Modifier chords are not supported by the Windows input contract"
                }
                $capability = $null
                $script:InputResult = @{ delivery = "not_sent"; verification = "unconfirmed"; reason = "input_setup_failed" }
                try {
                    $capability = Get-InputCapability $process $element
                    $script:InputResult.input_mode = $capability.mode
                    $script:InputResult.delivery = "unknown"
                    $script:InputResult.reason = "dispatch_started"
                    if ($null -ne $capability.lease) {
                        Assert-ForegroundInputLease $process
                        Send-ForegroundKey $operation.key
                    } else {
                        Send-Key $capability.handle $operation.key
                    }
                    $script:InputResult.delivery = "posted"
                    $script:InputResult.reason = "key_consumption_unobservable"
                } catch {
                    if ($script:InputResult.delivery -eq "unknown") {
                        $script:InputResult.reason = "dispatch_interrupted"
                    }
                    throw
                } finally {
                    if ($null -ne $capability) { Exit-ForegroundInputLease $capability.lease }
                }
            }
            "set_value" {
                Invoke-TypeText $process $element ([string]$operation.value) $true
            }
            default {
                throw "unsupportedTool(`"$($operation.tool)`")"
            }
        }

        Start-Sleep -Milliseconds 120
        try {
            $response = [pscustomobject]@{ ok = $true; snapshot = (Build-Snapshot $operation.app) }
        } catch {
            throw "[observation.after_action] The action was dispatched, but the updated window could not be read. Check the window before further action; do not replay automatically. Cause: $($_.Exception.Message)"
        }
    }
} catch {
    if ($operation.tool -in @("set_input_target", "type_text", "set_value", "press_key")) {
        $script:InputTarget = $null
    }
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
