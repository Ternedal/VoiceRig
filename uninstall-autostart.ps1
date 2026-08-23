$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$startup = [Environment]::GetFolderPath("Startup")
if ([string]::IsNullOrWhiteSpace($startup)) {
    throw "Windows Startup-mappen kunne ikke findes."
}

$vbsPath = Join-Path $startup "VoiceRig.vbs"
if (-not (Test-Path -LiteralPath $vbsPath)) {
    Write-Host "VoiceRig autostart var ikke installeret."
    return
}

$ExpectedRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$ExpectedExe = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".venv\Scripts\voicerig.exe"))
$Content = Get-Content -LiteralPath $vbsPath -Raw
$OwnsAutostart = (
    $Content.IndexOf($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    $Content.IndexOf($ExpectedExe, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
)

if (-not $OwnsAutostart) {
    Write-Warning "VoiceRig.vbs tilhører en anden checkout og bevares: $vbsPath"
    return
}

Remove-Item -LiteralPath $vbsPath -Force
Write-Host "Denne checkouts VoiceRig autostart er fjernet."
