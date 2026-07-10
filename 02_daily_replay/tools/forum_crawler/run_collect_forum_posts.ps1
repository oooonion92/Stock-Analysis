param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CollectorArgs = @()
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Text
    Write-Host "============================================================"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..\..")
$Collector = Join-Path $ScriptDir "collect_forum_posts.py"
$ReaderServer = Join-Path $ProjectRoot "02_daily_replay\reader_board_app\reader_board_server.py"
$Requirements = Join-Path $ScriptDir "requirements.txt"
$LocalPyDeps = Join-Path $ScriptDir ".pydeps"
$CloudRoot = "D:\OneDrive\Stock\Replies collect"
$LogRoot = Join-Path $CloudRoot "tool_logs"
$ReaderServerPort = 8769

if (-not (Test-Path -LiteralPath $Collector)) {
    throw "Cannot find collector script: $Collector"
}

if (-not (Test-Path -LiteralPath $ReaderServer)) {
    throw "Cannot find reader server script: $ReaderServer"
}

if (-not (Test-Path -LiteralPath $Requirements)) {
    throw "Cannot find requirements file: $Requirements"
}

if (-not (Test-Path -LiteralPath $LogRoot)) {
    New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
}

$PythonCandidates = @(
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
    "python"
)

$Python = $null
foreach ($Candidate in $PythonCandidates) {
    if ($Candidate -eq "python") {
        $Command = Get-Command python -ErrorAction SilentlyContinue
        if ($Command) {
            $Python = $Command.Source
            break
        }
    } elseif (Test-Path -LiteralPath $Candidate) {
        $Python = $Candidate
        break
    }
}

if (-not $Python) {
    throw "Cannot find Python. Expected bundled Codex runtime or system python."
}

if (-not (Test-Path -LiteralPath $LocalPyDeps)) {
    New-Item -ItemType Directory -Force -Path $LocalPyDeps | Out-Null
}

function Test-PythonImport {
    param(
        [string]$PythonExe,
        [string]$ModuleName
    )

    $CheckCode = "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)"
    & $PythonExe -c $CheckCode | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Ensure-ForumCrawlerDependencies {
    param(
        [string]$PythonExe,
        [string]$RequirementsPath,
        [string]$TargetDir
    )

    $env:PYTHONPATH = $TargetDir
    $MissingModules = @("bs4", "lxml", "playwright", "scrapling") | Where-Object {
        -not (Test-PythonImport -PythonExe $PythonExe -ModuleName $_)
    }

    if ($MissingModules.Count -eq 0) {
        return
    }

    Write-Host "Missing Python packages: $($MissingModules -join ', ')"
    Write-Host "Installing forum crawler dependencies to $TargetDir ..."
    & $PythonExe -m pip install --disable-pip-version-check --target $TargetDir -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install forum crawler dependencies."
    }
}

Ensure-ForumCrawlerDependencies -PythonExe $Python -RequirementsPath $Requirements -TargetDir $LocalPyDeps

$DefaultArgs = @("--retries", "20", "--retry-delay", "3", "--export-format", "jsonl")
if ((Get-Date).DayOfWeek -eq "Sunday") {
    $DefaultArgs += @("--min-pages", "3")
}
if ($CollectorArgs.Count -gt 0) {
    $RunArgs = $CollectorArgs
} else {
    $RunArgs = $DefaultArgs
}

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$LogPath = Join-Path $LogRoot "forum_collect_$Stamp.log"
$WatchTargets = Join-Path $CloudRoot "watch_targets.csv"
$TotalTargets = 0
if (Test-Path -LiteralPath $WatchTargets) {
    try {
        $TotalTargets = @(
            Import-Csv -LiteralPath $WatchTargets |
                Where-Object { $_.enabled -eq "1" -or $_.enabled -eq 1 }
        ).Count
    } catch {
        $TotalTargets = 0
    }
}

$State = [ordered]@{
    StartedAt = Get-Date
    Current = "-"
    Completed = 0
    Success = 0
    Failed = 0
    Warnings = 0
    TargetOpen = $false
}

$StartCollectText = -join ([char[]](24320,22987,25910,38598,65306))
$CollectFailedText = -join ([char[]](25910,38598,22833,36133))
$CollectDoneText = -join ([char[]](25910,38598,23436,25104,65306))
$TargetUnitText = -join ([char[]](20010,30446,26631))
$TodaySummaryName = (-join ([char[]](20170,26085,27719,24635))) + ".md"
$RollingSummaryName = (-join ([char[]](26368,36817,51,22825,27719,24635))) + ".md"
$ReaderDashboardName = (-join ([char[]](39640,25163,21457,35328,38405,35835,30475,26495))) + ".html"
$LocalReaderBoard = Join-Path $ProjectRoot "02_daily_replay\高手发言阅读看板.html"
$WeekendSummaryName = (-join ([char[]](21608,26411,19977,26085,27719,24635))) + ".md"
$WeekendDashboardName = (-join ([char[]](21608,26411,39640,25163,21457,35328,38405,35835,30475,26495))) + ".html"

$StartCollectPattern = "^" + [regex]::Escape($StartCollectText) + "(.+)$"
$CollectFailedPattern = [regex]::Escape($CollectFailedText) + "|failed:"
$CollectDonePattern = "^" + [regex]::Escape($CollectDoneText) + "(\d+) " + [regex]::Escape($TargetUnitText)

function Write-Dashboard {
    param([string]$Event = "")

    $elapsed = New-TimeSpan -Start $State.StartedAt -End (Get-Date)
    $percent = 0
    if ($TotalTargets -gt 0) {
        $percent = [Math]::Min(100, [Math]::Round(($State.Completed / $TotalTargets) * 100))
    }

    $status = "Done $($State.Completed)/$TotalTargets | OK $($State.Success) | Failed $($State.Failed) | Warnings $($State.Warnings) | Elapsed $($elapsed.ToString('hh\:mm\:ss'))"
    if ($State.Current -and $State.Current -ne "-") {
        $status = "$status | Current: $($State.Current)"
    }

    Write-Progress -Activity "Forum post collection" -Status $status -PercentComplete $percent
    if ($Event) {
        Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Event)
    }
}

function Close-CurrentTarget {
    param([string]$Result = "success")

    if (-not $State.TargetOpen) {
        return
    }

    $State.Completed++
    if ($Result -eq "failed") {
        $State.Failed++
        Write-Dashboard "Target failed: $($State.Current)"
    } else {
        $State.Success++
        Write-Dashboard "Target finished: $($State.Current)"
    }

    $State.TargetOpen = $false
}

function ConvertTo-CommandArgument {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Append-Utf8Line {
    param(
        [string]$Path,
        [string]$Text
    )

    $Utf8 = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::AppendAllText($Path, $Text + [Environment]::NewLine, $Utf8)
}

function Test-TcpPortOpen {
    param(
        [string]$HostName,
        [int]$Port
    )

    try {
        $Client = [System.Net.Sockets.TcpClient]::new()
        $Async = $Client.BeginConnect($HostName, $Port, $null, $null)
        $Success = $Async.AsyncWaitHandle.WaitOne(500)
        if (-not $Success) {
            $Client.Close()
            return $false
        }
        $Client.EndConnect($Async)
        $Client.Close()
        return $true
    } catch {
        return $false
    }
}

function Get-ReaderServerHealth {
    param(
        [string]$Url
    )

    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        if ($Response.StatusCode -ne 200) {
            return $false
        }
        $Payload = $Response.Content | ConvertFrom-Json
        return [bool]($Payload.sites -and $Payload.db_path)
    } catch {
        return $false
    }
}

function Stop-ProcessOnPort {
    param([int]$Port)

    $Connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $Connection) {
        return $false
    }

    $ProcessId = $Connection.OwningProcess
    if (-not $ProcessId) {
        return $false
    }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 600
        return $true
    } catch {
        Write-Host "Failed to stop process on port ${Port}: $($_.Exception.Message)"
        return $false
    }
}

function Process-CollectorLine {
    param([string]$Line)

    if ($Line -match $StartCollectPattern) {
        Close-CurrentTarget "success"
        $State.Current = $Matches[1]
        $State.TargetOpen = $true
        Write-Dashboard "Started: $($State.Current)"
    } elseif ($Line -match "^\[WARN\]") {
        $State.Warnings++
        Write-Dashboard $Line
    } elseif ($Line -match $CollectFailedPattern) {
        Close-CurrentTarget "failed"
        Write-Dashboard $Line
    } elseif ($Line -match $CollectDonePattern) {
        Close-CurrentTarget "success"
        if ($State.Completed -lt [int]$Matches[1]) {
            $State.Completed = [int]$Matches[1]
        }
        Write-Dashboard $Line
    }

    Write-Host $Line
}

function Read-NewLines {
    param(
        [string]$Path,
        [ref]$Seen
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }

    $Lines = @(Get-Content -LiteralPath $Path -Encoding utf8 -ErrorAction SilentlyContinue)
    if ($Lines.Count -le $Seen.Value) {
        return @()
    }

    $NewLines = $Lines[$Seen.Value..($Lines.Count - 1)]
    $Seen.Value = $Lines.Count
    return $NewLines
}

Write-Section "Forum collector one-click tool"
Write-Host "Project : $ProjectRoot"
Write-Host "Python  : $Python"
Write-Host "Script  : $Collector"
Write-Host "Args    : $($RunArgs -join ' ')"
Write-Host "Log     : $LogPath"
if ($TotalTargets -gt 0) {
    Write-Host "Targets : $TotalTargets enabled targets"
}
Write-Host ""
Write-Host "Note: this tool reuses the existing browser_profile login state."
Write-Host "It will not clear browser processes or cookies."
Write-Host ""

if (Test-TcpPortOpen -HostName "127.0.0.1" -Port $ReaderServerPort) {
    if (Get-ReaderServerHealth -Url "http://127.0.0.1:$ReaderServerPort/api/options") {
        Write-Host "Reader server already running: http://127.0.0.1:$ReaderServerPort"
    } else {
        Write-Host "Reader server on port $ReaderServerPort is outdated or invalid. Restarting it..."
        [void](Stop-ProcessOnPort -Port $ReaderServerPort)
    }
}

if (-not (Test-TcpPortOpen -HostName "127.0.0.1" -Port $ReaderServerPort)) {
    $ReaderStdOut = Join-Path $LogRoot "expert_reader_server.stdout.log"
    $ReaderStdErr = Join-Path $LogRoot "expert_reader_server.stderr.log"
    $ReaderArgs = @("-u", $ReaderServer)
    $ReaderArgumentList = ($ReaderArgs | ForEach-Object { ConvertTo-CommandArgument $_ }) -join " "
    $ReaderProcess = Start-Process `
        -FilePath $Python `
        -ArgumentList $ReaderArgumentList `
        -WorkingDirectory $ScriptDir `
        -RedirectStandardOutput $ReaderStdOut `
        -RedirectStandardError $ReaderStdErr `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Milliseconds 800
    Write-Host "Reader server started: http://127.0.0.1:$ReaderServerPort (PID: $($ReaderProcess.Id))"
}

Push-Location $ScriptDir
try {
    Write-Dashboard "Ready to start."

    $StdOutPath = Join-Path $LogRoot "forum_collect_$Stamp.stdout.tmp"
    $StdErrPath = Join-Path $LogRoot "forum_collect_$Stamp.stderr.tmp"
    $ProcessArgs = @("-u", $Collector) + $RunArgs
    $ArgumentList = ($ProcessArgs | ForEach-Object { ConvertTo-CommandArgument $_ }) -join " "

    $CrawlerProcess = Start-Process `
        -FilePath $Python `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $ScriptDir `
        -RedirectStandardOutput $StdOutPath `
        -RedirectStandardError $StdErrPath `
        -NoNewWindow `
        -PassThru

    Write-Dashboard "Crawler process started. PID: $($CrawlerProcess.Id)"

    $SeenOut = 0
    $SeenErr = 0
    while (-not $CrawlerProcess.HasExited) {
        foreach ($Line in (Read-NewLines -Path $StdOutPath -Seen ([ref]$SeenOut))) {
            Append-Utf8Line -Path $LogPath -Text ([string]$Line)
            Process-CollectorLine $Line
        }
        foreach ($Line in (Read-NewLines -Path $StdErrPath -Seen ([ref]$SeenErr))) {
            Append-Utf8Line -Path $LogPath -Text ("[stderr] " + [string]$Line)
            Write-Dashboard "[stderr] $Line"
            Write-Host "[stderr] $Line"
        }

        Write-Dashboard
        Start-Sleep -Seconds 1
    }

    foreach ($Line in (Read-NewLines -Path $StdOutPath -Seen ([ref]$SeenOut))) {
        Append-Utf8Line -Path $LogPath -Text ([string]$Line)
        Process-CollectorLine $Line
    }
    foreach ($Line in (Read-NewLines -Path $StdErrPath -Seen ([ref]$SeenErr))) {
        Append-Utf8Line -Path $LogPath -Text ("[stderr] " + [string]$Line)
        Write-Dashboard "[stderr] $Line"
        Write-Host "[stderr] $Line"
    }

    $CrawlerProcess.WaitForExit()
    $CrawlerProcess.Refresh()
    $ExitCode = $CrawlerProcess.ExitCode
    if ($null -eq $ExitCode) {
        $ExitCode = 0
    }
    Remove-Item -LiteralPath $StdOutPath, $StdErrPath -Force -ErrorAction SilentlyContinue
} finally {
    Close-CurrentTarget "success"
    Write-Progress -Activity "Forum post collection" -Completed
    Pop-Location
}

Write-Section "Run result"
if ($ExitCode -eq 0) {
    Write-Host "Collection command finished."
} else {
    Write-Host "Collection command returned exit code: $ExitCode"
}

$ReportsRoot = Join-Path $CloudRoot "reports"
if (Test-Path -LiteralPath $ReportsRoot) {
    $LatestReport = Get-ChildItem -LiteralPath $ReportsRoot -Filter "collect_report_*.md" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($LatestReport) {
        Write-Host "Latest report: $($LatestReport.FullName)"
    }
}

$TodaySummary = Join-Path $CloudRoot $TodaySummaryName
if (Test-Path -LiteralPath $TodaySummary) {
    Write-Host "Today summary: $TodaySummary"
}

$RollingSummary = Join-Path $CloudRoot $RollingSummaryName
if (Test-Path -LiteralPath $RollingSummary) {
    Write-Host "Rolling 3-day summary: $RollingSummary"
}

$ReaderDashboard = Join-Path $CloudRoot $ReaderDashboardName
if (Test-Path -LiteralPath $ReaderDashboard) {
    Write-Host "Reader dashboard: $ReaderDashboard"
}

$WeekendSummary = Join-Path $CloudRoot $WeekendSummaryName
if (Test-Path -LiteralPath $WeekendSummary) {
    Write-Host "Weekend 3-day summary: $WeekendSummary"
}

$WeekendDashboard = Join-Path $CloudRoot $WeekendDashboardName
if (Test-Path -LiteralPath $WeekendDashboard) {
    Write-Host "Weekend dashboard: $WeekendDashboard"
}
Write-Host "Reader API: http://127.0.0.1:$ReaderServerPort"
if (Test-Path -LiteralPath $LocalReaderBoard) {
    Write-Host "Local reader board: $LocalReaderBoard"
}

Write-Host "Log file: $LogPath"

exit $ExitCode
