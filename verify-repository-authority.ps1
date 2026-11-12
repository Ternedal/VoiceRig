param(
    [switch]$Json
)

# Repository authority for Ternedal/VoiceRig, read live from GitHub.
#
# Same contract as ModelRig's and BodyRig's verifiers (#2109, ModelRig #2390 F3):
# - runs only from a clean checkout of branch main;
# - binds the verdict to that checkout's exact 40-hex HEAD, and refuses if
#   GitHub's main head is not that same revision;
# - with -Json prints exactly one compact JSON object for the cross-repository
#   qualifier (scripts/kaliv_repository_authority_qualifier.py in ModelRig).
# Exit codes: 0 PASS, 2 FAIL, 1 a precondition is not met (nothing verified).
# Authority: repository settings only. It proves nothing about physical
# validation, release or production activation.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = "Ternedal/VoiceRig"
$Branch = "main"
$ExpectedChecks = @(
    @{ context = "unit"; app_id = 15368 }
    @{ context = "packaged-contract"; app_id = 15368 }
    @{ context = "ownership-smoke"; app_id = 15368 }
    @{ context = "windows-service-smoke"; app_id = 15368 }
    @{ context = "Analyze (python)"; app_id = 15368 }
    @{ context = "Analyze (javascript-typescript)"; app_id = 15368 }
)

function Get-Prop {
    param($Object, [Parameter(Mandatory = $true)][string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Need-Revision {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Label)
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not an exact Git revision." }
    return $normalized
}

function Invoke-GhJson {
    param([Parameter(Mandatory = $true)][string]$ApiPath, [switch]$AllowFailure)
    $raw = @(& gh api $ApiPath --method GET 2>&1)
    if ($LASTEXITCODE -ne 0) {
        if ($AllowFailure) { return $null }
        throw "GitHub API read failed for repository-authority endpoint: $ApiPath"
    }
    try { return (($raw -join "`n") | ConvertFrom-Json -Depth 60) }
    catch { throw "GitHub API returned unreadable JSON for repository-authority endpoint: $ApiPath" }
}

if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne $Branch) {
    throw "Repository-authority verification must run from branch main."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Repository-authority verification requires an exact clean main checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve VoiceRig HEAD." }
$head = Need-Revision -Value ([string]$headRaw[0]) -Label "VoiceRig HEAD"

if ($null -eq (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is required for authoritative repository-settings verification."
}
@(& gh auth status -h github.com 2>&1) | Out-Null
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated for github.com." }

$errors = New-Object System.Collections.Generic.List[string]

$branchInfo = Invoke-GhJson -ApiPath "repos/$Repo/branches/$Branch"
$githubHead = [string](Get-Prop (Get-Prop $branchInfo "commit") "sha")
if ($githubHead -notmatch '^[0-9a-fA-F]{40}$') {
    $errors.Add("GitHub main head is not an exact revision")
    $githubHead = $null
} else {
    $githubHead = $githubHead.ToLowerInvariant()
    if ($githubHead -ne $head) { $errors.Add("GitHub main head does not match the expected checkout revision") }
}
$protected = (Get-Prop $branchInfo "protected") -eq $true
if (-not $protected) { $errors.Add("main is not protected") }

$protection = Invoke-GhJson -ApiPath "repos/$Repo/branches/$Branch/protection" -AllowFailure
if ($null -eq $protection) {
    $errors.Add("main protection is unavailable")
} else {
    $statusChecks = Get-Prop $protection "required_status_checks"
    if ($null -eq $statusChecks) {
        $errors.Add("required_status_checks is missing")
    } elseif ((Get-Prop $statusChecks "strict") -ne $true) {
        $errors.Add("required_status_checks.strict is not true")
    }
    $actual = @()
    $checks = Get-Prop $statusChecks "checks"
    if ($null -ne $checks) {
        $actual = @($checks | ForEach-Object { "$(Get-Prop $_ 'context'):$(Get-Prop $_ 'app_id')" })
    }
    foreach ($check in $ExpectedChecks) {
        $key = "$($check.context):$($check.app_id)"
        if ($actual -notcontains $key) { $errors.Add("missing required check/source binding: $key") }
    }
    if ($null -eq (Get-Prop $protection "required_pull_request_reviews")) { $errors.Add("pull requests are not required") }
    if ((Get-Prop (Get-Prop $protection "enforce_admins") "enabled") -ne $true) { $errors.Add("administrator enforcement is not enabled") }
    if ((Get-Prop (Get-Prop $protection "required_conversation_resolution") "enabled") -ne $true) { $errors.Add("conversation resolution is not required") }
    if ((Get-Prop (Get-Prop $protection "allow_force_pushes") "enabled") -eq $true) { $errors.Add("force pushes are allowed") }
    if ((Get-Prop (Get-Prop $protection "allow_deletions") "enabled") -eq $true) { $errors.Add("main deletion is allowed") }
}

$passed = $errors.Count -eq 0
$result = [ordered]@{
    format = "voicerig-repository-authority"
    version = 1
    repository = $Repo
    branch = $Branch
    head = $head
    github_head = $githubHead
    protected = $protected
    authority_mode = "classic_branch_protection"
    required_checks = @($ExpectedChecks | ForEach-Object { "$($_.context):$($_.app_id)" })
    passed = $passed
    errors = @($errors)
    authority = "repository settings only; no physical validation, release or production activation"
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10 -Compress
} else {
    Write-Host "VoiceRig repository authority: $(if ($passed) { 'PASS' } else { 'FAIL' })"
    Write-Host "Repository: $Repo"
    Write-Host "Branch:     $Branch"
    Write-Host "Head:       $head"
    Write-Host "Protected:  $protected"
    if ($errors.Count -gt 0) {
        Write-Host "Errors:"
        foreach ($item in $errors) { Write-Host "  - $item" }
    } else {
        Write-Host "Required checks:"
        $ExpectedChecks | ForEach-Object { Write-Host "  - $($_.context) (app_id=$($_.app_id))" }
    }
    Write-Host "Authority: repository settings only; no physical validation, release or production activation."
}
if ($passed) { exit 0 }
exit 2
