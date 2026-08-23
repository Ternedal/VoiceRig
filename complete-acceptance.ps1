param(
    [switch]$QualityPass,
    [string]$QualityNote = "",
    [string]$ValidationReport = (Join-Path $PSScriptRoot "validation-report.json"),
    [string]$FallbackReport = (Join-Path $PSScriptRoot "piper-fallback-report.json"),
    [string]$Output = (Join-Path $PSScriptRoot "release-acceptance.json")
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "VoiceRig-miljøet findes ikke. Kør .\setup-windows.ps1 først."
}
if (-not $QualityPass) {
    throw "Lyt først til reference + validation WAV og kør derefter igen med -QualityPass."
}
if ([string]::IsNullOrWhiteSpace($QualityNote)) {
    throw "-QualityPass kræver også -QualityNote, fx 'Tydelig dansk, genkendelig stemme, ingen alvorlige artefakter'."
}

# A failed release gate is a normal verdict, not a PowerShell transport error.
# Windows PowerShell 5.1 can promote native stderr to terminating errors under
# ErrorActionPreference=Stop, so capture the process exit code explicitly.
$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & $Python -m voicerig.release_gate `
        --validation-report $ValidationReport `
        --fallback-report $FallbackReport `
        --quality-pass `
        --quality-note $QualityNote `
        --output $Output
    $Code = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

exit $Code
