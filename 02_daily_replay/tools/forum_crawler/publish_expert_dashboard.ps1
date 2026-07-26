$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Publisher = Join-Path $ScriptDir "publish_expert_dashboard.py"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = if (Test-Path -LiteralPath $BundledPython) { $BundledPython } else { (Get-Command python -ErrorAction Stop).Source }
$env:PYTHONPATH = Join-Path $ScriptDir ".pydeps"

Write-Host "Publishing expert posts from the local database..."
& $Python -u $Publisher
exit $LASTEXITCODE
