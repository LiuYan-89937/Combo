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

function Test-ArchiveChecksum {
    if (-not (Test-Path -LiteralPath $PythonArchivePath -PathType Leaf)) {
        return $false
    }

    $ActualHash = (Get-FileHash -LiteralPath $PythonArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    return $ActualHash -eq $PythonArchiveSha256
}

foreach ($CommandName in @("cargo.exe", "rustup.exe", "npm.cmd", "curl.exe", "tar.exe")) {
    Assert-Command -Name $CommandName
}

if ($RustTarget -ne "x86_64-pc-windows-msvc") {
    throw "The bundled Python runtime is x64, so the Rust target must be x86_64-pc-windows-msvc."
}

$FrontendLockfile = Join-Path $FrontendDir "package-lock.json"
if (-not (Test-Path -LiteralPath $FrontendLockfile -PathType Leaf)) {
    throw "Frontend lockfile is required: $FrontendLockfile"
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

Write-Host "Preparing Rust x64 target..."
& rustup.exe target add $RustTarget
if ($LASTEXITCODE -ne 0) {
    throw "rustup target add failed with exit code $LASTEXITCODE."
}

Write-Host "Building Windows x64 installers..."
Push-Location $TauriDir
try {
    & cargo.exe tauri build --target x86_64-pc-windows-msvc
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$BundleDir = Join-Path $TauriDir "target\$RustTarget\release\bundle"
if (-not (Test-Path -LiteralPath $BundleDir -PathType Container)) {
    throw "Tauri bundle directory not found: $BundleDir"
}

$Installers = Get-ChildItem -Path $BundleDir -Recurse -File |
    Where-Object { $_.Extension -in @(".msi", ".exe") }
if (-not $Installers) {
    throw "No Windows installer was produced under $BundleDir."
}

Write-Host ""
Write-Host "Packages created:"
foreach ($Installer in $Installers) {
    $Hash = (Get-FileHash -LiteralPath $Installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "  $($Installer.FullName)"
    Write-Host "  SHA-256: $Hash"
}
