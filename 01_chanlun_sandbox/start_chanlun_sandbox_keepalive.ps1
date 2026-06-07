$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$py = Join-Path $root ".pydeps\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    $py = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
}
if (-not (Test-Path -LiteralPath $py)) { $py = "python" }

$app = Join-Path $root "chanlun_sandbox_app.py"
$log = Join-Path $root "sandbox_keepalive.log"

while ($true) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $log -Value "[$stamp] starting: $py -u $app 8765"
    & $py -u $app 8765 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
    $code = $LASTEXITCODE
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $log -Value "[$stamp] exited: code=$code"
    Start-Sleep -Seconds 2
}
