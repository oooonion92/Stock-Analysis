$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$python = Join-Path $root '.pydeps\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }

$app = Join-Path $root 'chanlun_sandbox_app.py'
$log = Join-Path $root 'sandbox.log'

& $python -u $app 8765 *> $log
