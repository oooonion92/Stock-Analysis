$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$runtime = Join-Path $root "runtime"
$venv = Join-Path $root ".venv"
$requirements = Join-Path $root "requirements.txt"

New-Item -ItemType Directory -Path $runtime -Force | Out-Null

$existing = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    Start-Process "http://127.0.0.1:8766/"
    Write-Host "Chanlun Sandbox V2 is already running at http://127.0.0.1:8766/"
    exit 0
}

$bootstrapPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $bootstrapPython)) {
    $bootstrapPython = (Get-Command python -ErrorAction Stop).Source
}
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    & $bootstrapPython -m venv $venv
}

$requirementHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
$stamp = Join-Path $venv "requirements.sha256"
$installedHash = if (Test-Path -LiteralPath $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { "" }
if ($installedHash -ne $requirementHash) {
    & $python -m pip install --disable-pip-version-check -r $requirements
    Set-Content -LiteralPath $stamp -Value $requirementHash -Encoding ascii
}

$pnpm = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"
$nodeBin = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
if (Test-Path -LiteralPath $nodeBin) { $env:PATH = "$nodeBin;$env:PATH" }
if (-not (Test-Path -LiteralPath $pnpm)) {
    $pnpm = (Get-Command pnpm -ErrorAction Stop).Source
}
$lockfile = Join-Path $frontend "pnpm-lock.yaml"
if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
    Push-Location $frontend
    try {
        if (Test-Path -LiteralPath $lockfile) { & $pnpm install --frozen-lockfile } else { & $pnpm install }
    } finally { Pop-Location }
}

$distIndex = Join-Path $frontend "dist\index.html"
$sourceFiles = Get-ChildItem -LiteralPath $frontend -Recurse -File | Where-Object { $_.FullName -notlike "*\node_modules\*" -and $_.FullName -notlike "*\dist\*" }
$latestSource = ($sourceFiles | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
$needsBuild = -not (Test-Path -LiteralPath $distIndex)
if (-not $needsBuild) {
    $needsBuild = (Get-Item -LiteralPath $distIndex).LastWriteTimeUtc -lt $latestSource
}
if ($needsBuild) {
    Push-Location $frontend
    try { & $pnpm build } finally { Pop-Location }
}

$stdout = Join-Path $runtime "sandbox_v2.log"
$stderr = Join-Path $runtime "sandbox_v2.error.log"
$process = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8766") -WorkingDirectory $backend -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
Set-Content -LiteralPath (Join-Path $runtime "sandbox_v2.pid") -Value $process.Id -Encoding ascii

for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8766/api/health" -TimeoutSec 1
        if ($health.status) {
            Start-Process "http://127.0.0.1:8766/"
            Write-Host "Chanlun Sandbox V2 running at http://127.0.0.1:8766/"
            exit 0
        }
    } catch { }
}

throw "V2 failed to start. Check $stderr"
