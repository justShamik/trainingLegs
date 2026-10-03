<#
.SYNOPSIS  Run the browser e2e suite (and optionally the unit suite / manual session).
.EXAMPLE   .\scripts\run_e2e.ps1                 # headless
.EXAMPLE   .\scripts\run_e2e.ps1 -Headed -SlowMo 300
.EXAMPLE   .\scripts\run_e2e.ps1 -Filter "sync"  # pytest -k
.EXAMPLE   .\scripts\run_e2e.ps1 -Manual         # headed Chrome + live browser/server problem stream
.EXAMPLE   .\scripts\run_e2e.ps1 -Install        # (re)install playwright + browsers first
#>
param(
    [switch]$Headed,
    [int]$SlowMo = 0,
    [string]$Filter = "",
    [switch]$Unit,
    [switch]$Manual,
    [switch]$Install,
    [switch]$Real,
    [string]$Channel = ""
)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

if ($Install) {
    & $py -m pip install -r requirements.txt
    & $py -m playwright install chromium
}
if ($Manual) {
    $a = @("scripts\e2e_manual_session.py")
    if ($Real) { $a += "--real" }
    if ($Channel) { $a += @("--channel", $Channel) }
    & $py @a
    exit $LASTEXITCODE
}

$code = 0
if ($Unit) {
    & $py -m pytest -q --deselect test_gemini.py
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }
}
$args = @("-m", "pytest", "tests/e2e", "-q")
if ($Headed) { $args += "--headed" }
if ($SlowMo -gt 0) { $args += @("--slowmo", $SlowMo) }
if ($Filter) { $args += @("-k", $Filter) }
if ($Channel) { $args += @("--browser-channel", $Channel) }
& $py @args
if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }
if (Test-Path tests\e2e\artifacts) { Write-Host "Failure artifacts: tests\e2e\artifacts (screenshots, traces: playwright show-trace <zip>)" }
exit $code
