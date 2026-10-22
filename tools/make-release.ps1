# Build the release app package ai-passport-voice-app-<ver>.zip:
# clean git export + inject prebuilt AI-Passport-Voice.exe + write sha256.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools/make-release.ps1 [-Version 0.3.0]
param([string]$Version = "0.3.0")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    $zip = "ai-passport-voice-app-$Version.zip"
    $exe = "windows/AI-Passport-Voice.exe"
    if (-not (Test-Path $exe)) {
        Write-Error "Missing $exe - run windows/build-exe.cmd first"
    }
    git archive --format=zip -o $zip HEAD
    # Inject the exe into the zip as windows/AI-Passport-Voice.exe
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::Open((Join-Path $root $zip), "Update")
    try {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, (Join-Path $root $exe), "windows/AI-Passport-Voice.exe") | Out-Null
    } finally { $archive.Dispose() }
    (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() + "  $zip" |
        Out-File "$zip.sha256" -Encoding ascii
    "{0:N1} MB  {1}" -f ((Get-Item $zip).Length / 1MB), $zip
    Get-Content ("$zip" + ".sha256")
} finally { Pop-Location }
