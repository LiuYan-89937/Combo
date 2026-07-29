[CmdletBinding()]
param(
    [string]$RustTarget = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "This script must run on Windows."
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TauriDir = Join-Path $ProjectRoot "src-tauri"
$FrontendDir = Join-Path $ProjectRoot "web_frontend\frontend"
$PythonResourcesDir = Join-Path $TauriDir "resources\python"
$PythonExecutable = Join-Path $PythonResourcesDir "python.exe"
$DownloadDir = Join-Path $ProjectRoot "build\python-downloads"
$BuildLogDir = Join-Path $ProjectRoot "build\logs"
$BuildLogPath = Join-Path $BuildLogDir "windows-package.log"
$DefaultUpdaterKey = Join-Path $env:USERPROFILE ".fastagentfactory\updater\fastagentfactory.key"

$PythonArchiveName = "cpython-3.11.9+20240726-x86_64-pc-windows-msvc-shared-install_only.tar.gz"
$PythonArchiveUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20240726/cpython-3.11.9%2B20240726-x86_64-pc-windows-msvc-shared-install_only.tar.gz"
$PythonArchiveSha256 = "f694be48bdfec1dace6d69a19906b6083f4dd7c7c61f1138ba520e433e5598f8"
$PythonArchivePath = Join-Path $DownloadDir $PythonArchiveName

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Import-VisualStudioBuildEnvironment {
    $VsWhereCandidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"),
        (Join-Path $env:ProgramFiles "Microsoft Visual Studio\Installer\vswhere.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }

    $VsWhere = $VsWhereCandidates | Select-Object -First 1
    if (-not $VsWhere) {
        throw (
            "Visual Studio 2022 Build Tools with the C++ workload is required. " +
            "Install Microsoft.VisualStudio.2022.BuildTools with " +
            "Microsoft.VisualStudio.Workload.VCTools, VC.Tools.x86.x64, VC.Tools.ARM64, " +
            "and the recommended Windows SDK components."
        )
    }

    $InstallationPath = [string](& $VsWhere `
        -latest `
        -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath)
    $InstallationPath = $InstallationPath.Trim()
    if (-not $InstallationPath) {
        throw "Visual Studio Build Tools is installed without the x64 C++ toolchain."
    }

    $VsDevCmd = Join-Path $InstallationPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $VsDevCmd -PathType Leaf)) {
        throw "Visual Studio developer environment script not found: $VsDevCmd"
    }

    $EnvironmentLines = & cmd.exe /s /c "`"$VsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && set"
    if ($LASTEXITCODE -ne 0) {
        throw "Visual Studio x64 build environment initialization failed with exit code $LASTEXITCODE."
    }

    foreach ($Line in $EnvironmentLines) {
        $Separator = $Line.IndexOf("=")
        if ($Separator -le 0) {
            continue
        }
        $Name = $Line.Substring(0, $Separator)
        $Value = $Line.Substring($Separator + 1)
        [System.Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }

    Assert-Command -Name "link.exe"
}

function Test-ArchiveChecksum {
    if (-not (Test-Path -LiteralPath $PythonArchivePath -PathType Leaf)) {
        return $false
    }

    $ActualHash = (Get-FileHash -LiteralPath $PythonArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    return $ActualHash -eq $PythonArchiveSha256
}

function Test-TauriCli {
    & cargo.exe tauri --version *> $null
    return $LASTEXITCODE -eq 0
}

foreach ($CommandName in @("cargo.exe", "rustup.exe", "npm.cmd", "curl.exe", "tar.exe", "cmd.exe")) {
    Assert-Command -Name $CommandName
}

if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
    if (-not (Test-Path -LiteralPath $DefaultUpdaterKey -PathType Leaf)) {
        throw (
            "Updater signing key not found. Copy the shared FastAgentFactory updater key to " +
            "$DefaultUpdaterKey or set TAURI_SIGNING_PRIVATE_KEY for this process."
        )
    }
    $env:TAURI_SIGNING_PRIVATE_KEY = $DefaultUpdaterKey
}

if ($RustTarget -ne "x86_64-pc-windows-msvc") {
    throw "The bundled Python runtime is x64, so the Rust target must be x86_64-pc-windows-msvc."
}

Import-VisualStudioBuildEnvironment

Write-Host "Preparing Rust x64 target..."
& rustup.exe target add $RustTarget
if ($LASTEXITCODE -ne 0) {
    throw "rustup target add failed with exit code $LASTEXITCODE."
}

$FrontendLockfile = Join-Path $FrontendDir "package-lock.json"
if (-not (Test-Path -LiteralPath $FrontendLockfile -PathType Leaf)) {
    throw "Frontend lockfile is required: $FrontendLockfile"
}

if (-not (Test-TauriCli)) {
    Write-Host "Installing Tauri CLI 2 for Windows x64..."
    & cargo.exe install tauri-cli --version "^2.0.0" --locked --target $RustTarget
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri CLI installation failed with exit code $LASTEXITCODE."
    }
}
if (-not (Test-TauriCli)) {
    throw "Tauri CLI is unavailable after installation."
}

Write-Host "Preparing frontend dependencies..."
& npm.cmd --prefix $FrontendDir ci
if ($LASTEXITCODE -ne 0) {
    throw "npm ci failed with exit code $LASTEXITCODE."
}

New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
if (-not (Test-ArchiveChecksum)) {
    if (Test-Path -LiteralPath $PythonArchivePath) {
        Remove-Item -LiteralPath $PythonArchivePath -Force
    }

    Write-Host "Downloading pinned x64 Python runtime..."
    & curl.exe --fail --location --retry 3 --output $PythonArchivePath $PythonArchiveUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Python runtime download failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-ArchiveChecksum)) {
    throw "Python runtime checksum verification failed: $PythonArchivePath"
}

$ExtractionDir = Join-Path $ProjectRoot "build\python-extract-windows-x64"
if (Test-Path -LiteralPath $ExtractionDir) {
    Remove-Item -LiteralPath $ExtractionDir -Recurse -Force
}
New-Item -ItemType Directory -Path $ExtractionDir | Out-Null

try {
    Write-Host "Extracting bundled Python runtime..."
    & tar.exe -xf $PythonArchivePath -C $ExtractionDir
    if ($LASTEXITCODE -ne 0) {
        throw "Python runtime extraction failed with exit code $LASTEXITCODE."
    }

    $ExtractedPythonDir = Join-Path $ExtractionDir "python"
    if (-not (Test-Path -LiteralPath $ExtractedPythonDir -PathType Container)) {
        throw "Python archive does not contain the expected python directory."
    }

    if (Test-Path -LiteralPath $PythonResourcesDir) {
        Remove-Item -LiteralPath $PythonResourcesDir -Recurse -Force
    }
    Move-Item -LiteralPath $ExtractedPythonDir -Destination $PythonResourcesDir
}
finally {
    if (Test-Path -LiteralPath $ExtractionDir) {
        Remove-Item -LiteralPath $ExtractionDir -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Bundled Python executable not found: $PythonExecutable"
}

Write-Host "Installing Python application dependencies..."
& $PythonExecutable -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed with exit code $LASTEXITCODE."
}
& $PythonExecutable -m pip install --no-compile -e "${ProjectRoot}[web]"
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency installation failed with exit code $LASTEXITCODE."
}
& $PythonExecutable (Join-Path $ProjectRoot "scripts\generate_icons.py")
if ($LASTEXITCODE -ne 0) {
    throw "Application icon generation failed with exit code $LASTEXITCODE."
}

Write-Host "Building Windows x64 installers..."
New-Item -ItemType Directory -Force -Path $BuildLogDir | Out-Null
$BundleDir = Join-Path $TauriDir "target\$RustTarget\release\bundle\nsis"
if (Test-Path -LiteralPath $BundleDir) {
    Remove-Item -LiteralPath $BundleDir -Recurse -Force
}
Push-Location $TauriDir
try {
    $BuildCommand = "cargo.exe tauri build --target $RustTarget --bundles nsis 2>&1"
    & cmd.exe /d /s /c $BuildCommand |
        Tee-Object -FilePath $BuildLogPath
    $BuildExitCode = $LASTEXITCODE
    if ($BuildExitCode -ne 0) {
        throw "Tauri build failed with exit code $BuildExitCode. Full log: $BuildLogPath"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $BundleDir -PathType Container)) {
    throw "Tauri NSIS bundle directory not found: $BundleDir"
}

$Installers = Get-ChildItem -Path $BundleDir -File -Filter "*.exe"
if (-not $Installers) {
    throw "No Windows NSIS installer was produced under $BundleDir."
}

Write-Host ""
Write-Host "Packages created:"
foreach ($Installer in $Installers) {
    $SignaturePath = "$($Installer.FullName).sig"
    if (-not (Test-Path -LiteralPath $SignaturePath -PathType Leaf)) {
        throw "Updater signature was not generated: $SignaturePath"
    }
    $Hash = (Get-FileHash -LiteralPath $Installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "  $($Installer.FullName)"
    Write-Host "  $SignaturePath"
    Write-Host "  SHA-256: $Hash"
}
