param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("chatterbox", "rost", "omnivoice", "none")]
    [string]$Winner,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 5)]
    [int]$ChatterboxScore,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 5)]
    [int]$RostScore,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 5)]
    [int]$OmniVoiceScore,

    [Parameter(Mandatory = $true)]
    [string]$DecisionNote,

    [string]$ChatterboxNote = "",
    [string]$RostNote = "",
    [string]$OmniVoiceNote = "",

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string[]]$TestText,

    [string]$Output = (Join-Path $PSScriptRoot "engine-decision.json")
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "VoiceRig-miljøet findes ikke. Kør .\setup-windows.ps1 først."
}

$Arguments = @(
    "-m", "voicerig.engine_decision",
    "--winner", $Winner,
    "--chatterbox-score", [string]$ChatterboxScore,
    "--rost-score", [string]$RostScore,
    "--omnivoice-score", [string]$OmniVoiceScore,
    "--decision-note", $DecisionNote,
    "--chatterbox-note", $ChatterboxNote,
    "--rost-note", $RostNote,
    "--omnivoice-note", $OmniVoiceNote,
    "--output", $Output
)

foreach ($Text in $TestText) {
    if (-not [string]::IsNullOrWhiteSpace($Text)) {
        $Arguments += @("--test-text", $Text)
    }
}

$PreviousErrorActionPreference = $ErrorActionPreference
try {
    # Windows PowerShell 5.1 may promote native stderr to a terminating error.
    # The Python CLI owns the fail-closed exit code, so capture it explicitly.
    $ErrorActionPreference = "Continue"
    & $Python @Arguments
    $Code = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

exit $Code
