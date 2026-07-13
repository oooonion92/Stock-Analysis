param(
    [string]$SourceJson = "D:\OneDrive\Stock\Replies collect\experts-data.json",
    [string]$RepositoryPath = "D:\Projects\Stock-Replay-Dashboard"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$RepositoryUrl = "git@github.com:oooonion92/Stock-Replay-Dashboard.git"
$ExpectedRemote = "oooonion92/Stock-Replay-Dashboard"
$RelativeTarget = "experts/experts-data.json"
$SshCommand = "C:/Windows/System32/OpenSSH/ssh.exe"
$LogRoot = "D:\Projects\Stock Analysis\02_daily_replay\forum_reader\tool_logs"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogRoot "publish_expert_dashboard_$Stamp.log"

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Text) -ForegroundColor Cyan
}

function Find-Git {
    $Candidates = @(
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"),
        "C:\Program Files\Git\cmd\git.exe"
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    $Command = Get-Command git -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    throw "找不到 Git，请确认本机 Git 安装仍然有效。"
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory = $RepositoryPath
    )
    Push-Location $WorkingDirectory
    try {
        & $script:Git @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Git 命令执行失败：git $($Arguments -join ' ')"
        }
    } finally {
        Pop-Location
    }
}

function Read-And-ValidateJson {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "找不到待发布数据：$Path"
    }
    try {
        $Payload = Get-Content -Raw -Encoding utf8 -LiteralPath $Path | ConvertFrom-Json
    } catch {
        throw "JSON 无法解析：$Path"
    }

    $Records = @($Payload.records)
    if ($null -eq $Payload.recordCount -or [int]$Payload.recordCount -ne $Records.Count) {
        throw "recordCount 与 records 数量不一致。"
    }
    if ($Records.Count -eq 0) {
        throw "JSON 中没有记录，停止发布。"
    }

    $UpdatedAt = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$Payload.updatedAt, [ref]$UpdatedAt)) {
        throw "updatedAt 为空或无法解析。"
    }

    $Ids = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $PreviousSortKey = $null
    foreach ($Record in $Records) {
        $Id = [string]$Record.id
        if ([string]::IsNullOrWhiteSpace($Id) -or -not $Ids.Add($Id)) {
            throw "发现空 ID 或重复 ID：$Id"
        }
        if ([string]$Record.date -notmatch '^\d{4}-\d{2}-\d{2}$') {
            throw "记录日期格式无效：$($Record.date)"
        }
        if (
            [string]$Record.time -and
            [string]$Record.time -notmatch '^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$'
        ) {
            throw "记录时间格式无效：$($Record.time)"
        }
        foreach ($Field in @("source", "author", "body")) {
            if ([string]::IsNullOrWhiteSpace([string]$Record.$Field)) {
                throw "记录 $Id 缺少 $Field。"
            }
        }
        if ([string]$Record.url -and [string]$Record.url -notmatch '^https?://') {
            throw "记录 $Id 的 URL 无效。"
        }
        $SortKey = "{0} {1}" -f $Record.date, $Record.time
        if ($null -ne $PreviousSortKey -and [string]::CompareOrdinal($SortKey, $PreviousSortKey) -gt 0) {
            throw "records 未按日期时间倒序排列。"
        }
        $PreviousSortKey = $SortKey
    }

    return [pscustomobject]@{
        Payload = $Payload
        UpdatedAt = $UpdatedAt
        RecordCount = $Records.Count
    }
}

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
Start-Transcript -LiteralPath $LogPath -Force | Out-Null
$ExitCode = 1
try {
    Write-Host "高手看板数据发布工具" -ForegroundColor Yellow
    Write-Host "数据：$SourceJson"
    Write-Host "仓库：$ExpectedRemote"
    Write-Host "日志：$LogPath"

    Write-Step "校验待发布 JSON"
    $Source = Read-And-ValidateJson $SourceJson
    Write-Host "通过：$($Source.RecordCount) 条，更新时间 $($Source.UpdatedAt.ToString('yyyy-MM-dd HH:mm:ss zzz'))"

    $script:Git = Find-Git
    Write-Step "准备看板仓库"
    if (-not (Test-Path -LiteralPath (Join-Path $RepositoryPath ".git"))) {
        if (Test-Path -LiteralPath $RepositoryPath) {
            $ExistingItems = @(Get-ChildItem -Force -LiteralPath $RepositoryPath)
            if ($ExistingItems.Count -gt 0) {
                throw "仓库目录存在但不是 Git 仓库，请人工检查：$RepositoryPath"
            }
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RepositoryPath) | Out-Null
        }
        & $script:Git -c "core.sshCommand=$SshCommand" clone $RepositoryUrl $RepositoryPath
        if ($LASTEXITCODE -ne 0) {
            throw "克隆看板仓库失败。"
        }
    }

    Invoke-Git @("config", "core.sshCommand", $SshCommand)
    $GitUserName = ([string](& $script:Git -C $RepositoryPath config --get user.name)).Trim()
    if (-not $GitUserName) {
        Invoke-Git @("config", "user.name", "oooonion92")
    }
    $GitUserEmail = ([string](& $script:Git -C $RepositoryPath config --get user.email)).Trim()
    if (-not $GitUserEmail) {
        Invoke-Git @("config", "user.email", "xuchong1992@gmail.com")
    }
    $Origin = (& $script:Git -C $RepositoryPath remote get-url origin).Trim()
    if ($Origin -notmatch [regex]::Escape($ExpectedRemote)) {
        throw "仓库地址不符，停止发布：$Origin"
    }
    $Branch = (& $script:Git -C $RepositoryPath branch --show-current).Trim()
    if ($Branch -ne "main") {
        throw "看板仓库当前不在 main 分支：$Branch"
    }
    $Dirty = @(& $script:Git -C $RepositoryPath status --porcelain)
    if ($Dirty.Count -gt 0) {
        throw "看板仓库存在未提交改动，停止发布：$($Dirty -join '; ')"
    }

    Write-Step "同步 GitHub 最新版本"
    Invoke-Git @("pull", "--ff-only", "origin", "main")

    $TargetJson = Join-Path $RepositoryPath ($RelativeTarget -replace '/', '\')
    if (Test-Path -LiteralPath $TargetJson) {
        $Current = Read-And-ValidateJson $TargetJson
        if ($Source.UpdatedAt -lt $Current.UpdatedAt) {
            throw "待发布 JSON 比 GitHub 仓库旧，停止覆盖。"
        }
    }

    Write-Step "更新仓库数据"
    [System.IO.File]::Copy($SourceJson, $TargetJson, $true)
    & $script:Git -C $RepositoryPath diff --quiet -- $RelativeTarget
    if ($LASTEXITCODE -eq 0) {
        Write-Host "GitHub 仓库已经是相同数据，无需提交。" -ForegroundColor Green
        $ExitCode = 0
        return
    }
    if ($LASTEXITCODE -ne 1) {
        throw "无法比较仓库数据文件。"
    }

    Invoke-Git @("add", "--", $RelativeTarget)
    $CommitMessage = "data: publish expert dashboard $($Source.UpdatedAt.ToString('yyyy-MM-dd HH:mm'))"
    Invoke-Git @("commit", "-m", $CommitMessage)

    Write-Step "推送 GitHub main 分支"
    Invoke-Git @("push", "origin", "main")
    $Commit = (& $script:Git -C $RepositoryPath rev-parse --short HEAD).Trim()
    Write-Host "发布成功：$Commit，$($Source.RecordCount) 条记录。" -ForegroundColor Green
    Write-Host "看板：https://oooonion92.github.io/Stock-Replay-Dashboard/experts/"
    $ExitCode = 0
} catch {
    Write-Host ""
    Write-Host "发布失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "GitHub 上一版数据保持不变。"
} finally {
    Stop-Transcript | Out-Null
}

exit $ExitCode
