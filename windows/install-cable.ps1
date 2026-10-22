# AI Passport Voice - VB-CABLE download & launch helper (called by install.cmd).
# Downloads the driver pack from the official VB-Audio site, extracts it and
# starts the official installer elevated. VB-CABLE is donationware; this repo
# does not redistribute the installer, it only fetches it from the source.

$ErrorActionPreference = "Stop"
$url = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
$tmp = Join-Path $env:TEMP "VBCABLE_install"
$zip = Join-Path $tmp "VBCABLE_Driver_Pack45.zip"

try {
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    Write-Host "      Downloading driver pack (~1.3 MB)..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Write-Host "      Extracting..."
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $setup = Get-ChildItem $tmp -Recurse -Filter "VBCABLE_Setup_x64.exe" | Select-Object -First 1
    if (-not $setup) { throw "VBCABLE_Setup_x64.exe not found in the downloaded package" }
    Write-Host "      Launching installer - click 'Install Driver' in its window..."
    Start-Process -FilePath $setup.FullName -Verb RunAs -WorkingDirectory $setup.DirectoryName
    exit 0
} catch {
    Write-Host ("      Download/launch failed: " + $_.Exception.Message)
    exit 1
}
