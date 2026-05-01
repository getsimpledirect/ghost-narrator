#!/usr/bin/env pwsh
# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# ═══════════════════════════════════════════════════════════════════════════════
# Ghost Narrator — Audio Backfill Script (PowerShell)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Finds all published Ghost posts that do not yet have a working <audio>
# player embedded and triggers the Ghost Narrator n8n pipeline for each
# one. Default mode triggers all jobs, then exits — TTS-side processing
# continues in the background, and you monitor with -Queue or -Watch
# (or check the Ghost site once jobs complete).
#
# Usage:
#   .\backfill-audio.ps1                     # discover + trigger all jobs, exit
#   .\backfill-audio.ps1 -Queue              # job-level status snapshot
#   .\backfill-audio.ps1 -Queue -All         # include non-backfill jobs
#   .\backfill-audio.ps1 -Watch              # loop -Queue until terminal
#   .\backfill-audio.ps1 -Status             # log-level tail + background PID
#   .\backfill-audio.ps1 -Logs               # tail background run log (Ctrl+C to stop)
#   .\backfill-audio.ps1 -Stop               # stop a backgrounded run
#   .\backfill-audio.ps1 -Background         # rarely needed — trigger phase is <10s
#
# Requirements:
#   PowerShell 5.1+ (built into Windows) or PowerShell 7+
# ═══════════════════════════════════════════════════════════════════════════════

param(
    [switch]$Background,
    [switch]$Status,
    [switch]$Logs,
    [switch]$Stop,
    [switch]$Queue,
    [switch]$Watch,
    [switch]$All,
    # Internal: used when re-invoked as a background worker; not user-facing
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"

# ─── Paths for background process management ──────────────────────────────────
$SCRIPT_PATH  = $MyInvocation.MyCommand.Path
$PID_FILE     = Join-Path $env:TEMP "ghost-backfill.pid"
$LOG_FILE_OUT = Join-Path $env:TEMP "ghost-backfill.log"
$LOG_FILE_ERR = Join-Path $env:TEMP "ghost-backfill.err"
$CFG_FILE     = Join-Path $env:TEMP "ghost-backfill-config.json"

# ─── Helpers ──────────────────────────────────────────────────────────────────
function Write-Info    { param($msg) Write-Host $msg -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "v $msg" -ForegroundColor Green }
function Write-Warn    { param($msg) Write-Host "! $msg" -ForegroundColor Yellow }
function Write-Err     { param($msg) Write-Host "x $msg" -ForegroundColor Red }
function Write-Header  { param($msg) Write-Host "`n$msg" -ForegroundColor White }

# ─── .env loader ─────────────────────────────────────────────────────────────
# Loads KEY=VALUE pairs from a .env file into the process environment, but only
# when KEY isn't already set — so a value pre-exported by the caller wins.
# Comments and blank lines are skipped; surrounding quotes are stripped.
function Load-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*(#|$)') { continue }
        $stripped = $line -replace '^\s*export\s+', ''
        if ($stripped -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $name  = $matches[1]
            $value = $matches[2]
            # Trim surrounding single or double quotes.
            if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'`$") {
                $value = $matches[1]
            }
            # Defer to existing env values.
            if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
        }
    }
}

# Locate .env relative to either the script or the current working directory,
# whichever exists first. Repo root sits one level above scripts/.
$DotEnvPath = $null
$_candidates = @(
    (Join-Path (Get-Location) '.env'),
    (Join-Path (Split-Path -Parent (Split-Path -Parent $SCRIPT_PATH)) '.env')
)
foreach ($_c in $_candidates) {
    if (Test-Path $_c) { $DotEnvPath = $_c; break }
}
if ($DotEnvPath) { Load-DotEnv $DotEnvPath }

# ─── URL-to-slug helper ──────────────────────────────────────────────────────
# Convert a Ghost URL to a hostname-with-dashes slug used in JOB_ID and
# storage paths. The n8n callback workflow reverse-resolves this back to
# GHOST_SITE{1,2}_ADMIN_API_KEY by comparing against the dashed hostname of
# GHOST_SITE{1,2}_URL — so this function and the callback agree by construction.
function Get-UrlSlug {
    param([string]$Url)
    if (-not $Url) { return '' }
    $h = $Url -replace '^https?://', '' -replace '/.*$', '' -replace ':\d+$', ''
    return $h.Replace('.', '-')
}

# ─── Subcommand: -Status ──────────────────────────────────────────────────────
if ($Status) {
    if (-not (Test-Path $PID_FILE)) {
        Write-Warn "No background backfill is running (no PID file found at $PID_FILE)"
        exit 0
    }
    $bgPid = (Get-Content $PID_FILE -Raw).Trim()
    $proc  = Get-Process -Id $bgPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Success "Background backfill is RUNNING (PID $bgPid)"
        Write-Host "  Log  : $LOG_FILE_OUT"
        if (Test-Path $LOG_FILE_ERR) {
            $errContent = Get-Content $LOG_FILE_ERR -Raw -ErrorAction SilentlyContinue
            if ($errContent -and $errContent.Trim().Length -gt 0) {
                Write-Warn "  Errors logged to: $LOG_FILE_ERR"
            }
        }
        Write-Host ""
        Write-Host "  Last 10 log lines:" -ForegroundColor White
        if (Test-Path $LOG_FILE_OUT) {
            Get-Content $LOG_FILE_OUT -Tail 10 | ForEach-Object { Write-Host "    $_" }
        } else {
            Write-Host "    (log not yet created)"
        }
    } else {
        Write-Warn "Background process (PID $bgPid) is no longer running"
        Write-Warn "Check the log file for results: $LOG_FILE_OUT"
        Remove-Item $PID_FILE -ErrorAction SilentlyContinue
    }
    exit 0
}

# ─── Subcommand: -Logs ────────────────────────────────────────────────────────
if ($Logs) {
    if (-not (Test-Path $LOG_FILE_OUT)) {
        Write-Warn "No log file found at $LOG_FILE_OUT"
        Write-Warn "Has the backfill been started? Use -Status to check."
        exit 0
    }
    Write-Info "Tailing $LOG_FILE_OUT  (Ctrl+C to stop)"
    Write-Host ""
    Get-Content $LOG_FILE_OUT -Wait
    exit 0
}

# ─── Subcommand: -Stop ────────────────────────────────────────────────────────
if ($Stop) {
    if (-not (Test-Path $PID_FILE)) {
        Write-Warn "No background backfill is running (no PID file found)"
        exit 0
    }
    $bgPid = (Get-Content $PID_FILE -Raw).Trim()
    $proc  = Get-Process -Id $bgPid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $bgPid -Force
        Remove-Item $PID_FILE -ErrorAction SilentlyContinue
        Write-Success "Background backfill (PID $bgPid) stopped"
    } else {
        Write-Warn "Process $bgPid was not running — cleaning up stale PID file"
        Remove-Item $PID_FILE -ErrorAction SilentlyContinue
    }
    exit 0
}

# ─── Queue snapshot helpers (shared by -Queue and -Watch) ────────────────────
# Fetch /tts/jobs as parsed object. Returns $null on transient error so
# the caller can decide between bailing and retrying.
# $Query (optional) is appended as a query string (e.g. "prefix=backfill-").
function Get-TtsJobs {
    param([string]$Query = "")
    $base = if ($env:TTS_SERVICE_URL) { "$($env:TTS_SERVICE_URL)/tts/jobs" } else { "http://localhost:8020/tts/jobs" }
    $url  = if ($Query) { "$base`?$Query" } else { $base }
    $key = $env:TTS_API_KEY
    if (-not $key) {
        Write-Err "TTS_API_KEY is empty; set it in .env or `$env:TTS_API_KEY before running"
        return $null
    }
    try {
        return Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 10 -Headers @{ Authorization = "Bearer $key" }
    } catch {
        return $null
    }
}

# Render a status table from a /tts/jobs response object.
# $Mode = 'backfill' (filter to backfill-* IDs) or 'all' (no filter).
function Format-QueueTable {
    param($Response, [string]$Mode = 'backfill')
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

    if (-not $Response -or -not $Response.jobs) {
        Write-Host "(no jobs)"
        return
    }

    # Convert PSCustomObject "jobs" map (keyed by job_id) into rows
    $rows = @()
    foreach ($prop in $Response.jobs.PSObject.Properties) {
        $id = $prop.Name
        if ($Mode -eq 'backfill' -and -not $id.StartsWith('backfill-')) { continue }
        $j = $prop.Value
        $status = if ($j.status) { [string]$j.status } else { 'unknown' }
        $startedAt   = if ($j.started_at)   { [double]$j.started_at }   else { $null }
        $completedAt = if ($j.completed_at) { [double]$j.completed_at } else { $null }
        $createdAt   = if ($j.created_at)   { [double]$j.created_at }   else { $null }
        $errorStr    = if ($j.error)        { [string]$j.error }        else { '' }

        # Compute age
        $age = '-'
        if ($status -eq 'queued') {
            $age = '-'
        } elseif ($completedAt -and $startedAt) {
            $age = "$([int]($completedAt - $startedAt))s"
        } elseif ($startedAt) {
            $age = "$([int]($now - $startedAt))s"
        } elseif ($createdAt) {
            $age = "$([int]($now - $createdAt))s"
        }

        # Display ID: strip 'backfill-{site}-pid-{post_id}-' prefix and '-{timestamp}' suffix
        $displayId = $id -replace '^backfill-[a-z0-9-]+-pid-[a-f0-9]{24}-', '' -replace '-[0-9]{13}$', ''
        if ($displayId.Length -gt 60) { $displayId = $displayId.Substring(0, 57) + '...' }

        # Sort priority: failed → active → queued → terminal
        $sortKey = switch ($status) {
            'failed'     { 0 }
            'processing' { 1 }
            'paused'     { 1 }
            'queued'     { 2 }
            default      { 3 }
        }

        $rows += [PSCustomObject]@{
            SortKey   = $sortKey
            DisplayId = $displayId
            Status    = $status
            Age       = $age
            Error     = if ($errorStr) { '(' + ($errorStr.Substring(0, [Math]::Min(60, $errorStr.Length))) + ')' } else { '' }
        }
    }

    $label = if ($Mode -eq 'all') { 'All TTS Jobs' } else { 'Backfill Queue' }
    Write-Host ""
    Write-Host "─── $label (snapshot at $((Get-Date).ToString('HH:mm:ss'))) ─────────────────────" -ForegroundColor White
    if ($rows.Count -eq 0) {
        Write-Host "(no jobs)"
        Write-Host ""
        return
    }

    $sorted = $rows | Sort-Object SortKey, DisplayId
    "{0,-60}  {1,-11}  {2,-8}  {3}" -f 'ID (slug part)', 'STATUS', 'AGE', 'ERROR'
    foreach ($r in $sorted) {
        "{0,-60}  {1,-11}  {2,-8}  {3}" -f $r.DisplayId, $r.Status, $r.Age, $r.Error
    }
    Write-Host "──────────────────────────────────────────────────────────────" -ForegroundColor White

    $completed = ($rows | Where-Object { $_.Status -eq 'completed' }).Count
    $failed    = ($rows | Where-Object { $_.Status -eq 'failed'    }).Count
    $active    = ($rows | Where-Object { $_.Status -eq 'processing' -or $_.Status -eq 'paused' }).Count
    $queued    = ($rows | Where-Object { $_.Status -eq 'queued'    }).Count
    $cancelled = ($rows | Where-Object { $_.Status -eq 'cancelled' -or $_.Status -eq 'deleted' }).Count
    "Totals:  {0} done · {1} active · {2} queued · {3} failed · {4} cancelled ({5} total)" -f $completed, $active, $queued, $failed, $cancelled, $rows.Count
    Write-Host ""
}

# Returns $true if every backfill-* job in the response is in a terminal state.
function Test-AllTerminal {
    param($Response)
    if (-not $Response -or -not $Response.jobs) { return $true }
    $terminal = @('completed', 'failed', 'cancelled', 'deleted')
    foreach ($prop in $Response.jobs.PSObject.Properties) {
        if (-not $prop.Name.StartsWith('backfill-')) { continue }
        $st = if ($prop.Value.status) { [string]$prop.Value.status } else { '' }
        if ($terminal -notcontains $st) { return $false }
    }
    return $true
}

function Get-BackfillJobCount {
    param($Response)
    if (-not $Response -or -not $Response.jobs) { return 0 }
    $n = 0
    foreach ($prop in $Response.jobs.PSObject.Properties) {
        if ($prop.Name.StartsWith('backfill-')) { $n++ }
    }
    return $n
}

# ─── Subcommand: -Queue ──────────────────────────────────────────────────────
if ($Queue) {
    $query = if ($All) { '' } else { 'prefix=backfill-' }
    $resp = Get-TtsJobs -Query $query
    if ($null -eq $resp) {
        $url = if ($env:TTS_SERVICE_URL) { "$($env:TTS_SERVICE_URL)/tts/jobs" } else { "http://localhost:8020/tts/jobs" }
        Write-Err "Couldn't reach $url"
        exit 1
    }
    $mode = if ($All) { 'all' } else { 'backfill' }
    Format-QueueTable -Response $resp -Mode $mode
    exit 0
}

# ─── Subcommand: -Watch ──────────────────────────────────────────────────────
if ($Watch) {
    $failStreak = 0
    $firstIter  = $true
    while ($true) {
        $resp = Get-TtsJobs -Query 'prefix=backfill-'
        if ($null -eq $resp) {
            $failStreak++
            if ($failStreak -ge 3) {
                $url = if ($env:TTS_SERVICE_URL) { "$($env:TTS_SERVICE_URL)/tts/jobs" } else { "http://localhost:8020/tts/jobs" }
                Write-Err "Couldn't reach $url after 3 attempts"
                exit 1
            }
            Write-Warn "Transient fetch failure (attempt $failStreak/3); retrying in 15s"
            Start-Sleep -Seconds 15
            continue
        }
        $failStreak = 0
        Clear-Host
        Format-QueueTable -Response $resp -Mode 'backfill'

        if ($firstIter -and (Get-BackfillJobCount $resp) -eq 0) {
            Write-Warn "No backfill-* jobs found in queue. Did the trigger phase run?"
            exit 0
        }
        $firstIter = $false

        if (Test-AllTerminal $resp) {
            Write-Success "All backfill jobs are in a terminal state."
            exit 0
        }
        Start-Sleep -Seconds 15
    }
}

# ─── Subcommand: -Config (background worker mode) ─────────────────────────────
# This parameter is set internally when the script re-invokes itself via
# Start-Process. It loads config from a JSON file and skips all prompts.
$skipInteractive = $false
if ($Config -ne "") {
    if (-not (Test-Path $Config)) {
        Write-Err "Config file not found: $Config"
        exit 1
    }
    $cfg            = Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
    $N8N_WEBHOOK    = $cfg.N8N_WEBHOOK
    $TTS_SERVICE_URL = $cfg.TTS_SERVICE_URL
    $TTS_API_KEY    = $cfg.TTS_API_KEY
    $DRY_RUN        = $cfg.DRY_RUN
    $GhostUrls      = @($cfg.GhostUrls)
    $GhostKeys      = @($cfg.GhostKeys)
    $skipInteractive = $true
}

# ─── Banner + interactive prompts ─────────────────────────────────────────────
if (-not $skipInteractive) {
    Write-Host ""
    Write-Host "=========================================================" -ForegroundColor White
    Write-Host " Ghost Narrator — Audio Backfill" -ForegroundColor White
    Write-Host "=========================================================" -ForegroundColor White
    Write-Host ""
    Write-Host "Scans your Ghost site(s) for published posts that do not yet have"
    Write-Host "a working audio player embedded, then triggers the narration pipeline"
    Write-Host "for each one. Jobs queue in the TTS service and process one at a time"
    Write-Host "on the GPU. Use -Queue or -Watch to monitor progress."
    Write-Host ""

    Write-Host "-- Pipeline -------------------------------------------------" -ForegroundColor White
    Write-Host ""
    if ($DotEnvPath) {
        Write-Info "Loaded defaults from $DotEnvPath"
        Write-Host ""
    }

    $defaultWebhook = if ($env:N8N_WEBHOOK_URL) { $env:N8N_WEBHOOK_URL } else { "http://localhost:5678/webhook/ghost-published" }
    $inputWebhook   = Read-Host "n8n webhook URL [$defaultWebhook]"
    $N8N_WEBHOOK    = if ($inputWebhook) { $inputWebhook } else { $defaultWebhook }

    $defaultTts      = if ($env:TTS_SERVICE_URL) { $env:TTS_SERVICE_URL } else { "http://localhost:8020" }
    $inputTts        = Read-Host "TTS service URL [$defaultTts]"
    $TTS_SERVICE_URL = if ($inputTts) { $inputTts.TrimEnd("/") } else { $defaultTts }

    # TTS API key — required by the service since the auth refactor.
    # Honor $env:TTS_API_KEY so users can pre-export it once per shell session.
    if ($env:TTS_API_KEY) {
        $TTS_API_KEY = $env:TTS_API_KEY
        Write-Info "Using TTS_API_KEY from environment (`$env:TTS_API_KEY)"
    } else {
        $secureKey  = Read-Host "TTS API key (Bearer token, will not echo)" -AsSecureString
        $bstr       = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        $TTS_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
    }
    if (-not $TTS_API_KEY) {
        Write-Err "TTS API key cannot be empty — set `$env:TTS_API_KEY or paste it here"
        exit 1
    }

    Write-Host ""
    Write-Host "-- Ghost Sites ----------------------------------------------" -ForegroundColor White
    Write-Host ""

    # Default count from .env: 2 if SITE2 vars are set, else 1.
    $defaultCount = if ($env:GHOST_SITE2_URL -or $env:GHOST_KEY_SITE2) { 2 } else { 1 }
    $inputCount = Read-Host "Number of Ghost sites to process [$defaultCount]"
    $SITE_COUNT = if ($inputCount) {
        try { [int]$inputCount }
        catch { Write-Err "Invalid number: '$inputCount' — must be a whole number"; exit 1 }
    } else { $defaultCount }

    if ($SITE_COUNT -lt 1) {
        Write-Err "Site count must be at least 1"
        exit 1
    }

    $GhostUrls = @()
    $GhostKeys = @()

    for ($i = 1; $i -le $SITE_COUNT; $i++) {
        Write-Host ""
        Write-Host "  Site $i" -ForegroundColor White

        # Prefill from .env: GHOST_SITE${i}_URL and GHOST_KEY_SITE${i}.
        $defaultUrl = [Environment]::GetEnvironmentVariable("GHOST_SITE${i}_URL", 'Process')
        $defaultKey = [Environment]::GetEnvironmentVariable("GHOST_KEY_SITE${i}", 'Process')

        if ($defaultUrl) {
            $ghostUrl = Read-Host "    Ghost URL [$defaultUrl]"
            if (-not $ghostUrl) { $ghostUrl = $defaultUrl }
        } else {
            $ghostUrl = Read-Host "    Ghost URL (e.g. https://ghost.your-site.com)"
        }
        if (-not $ghostUrl) {
            Write-Err "Ghost URL cannot be empty"
            exit 1
        }

        if ($defaultKey) {
            $ghostKey = Read-Host "    Content API key [from .env]"
            if (-not $ghostKey) { $ghostKey = $defaultKey }
        } else {
            $ghostKey = Read-Host "    Content API key"
        }
        if (-not $ghostKey) {
            Write-Err "Content API key cannot be empty"
            exit 1
        }

        $GhostUrls += $ghostUrl.TrimEnd("/")
        $GhostKeys += $ghostKey
    }

    Write-Host ""
    Write-Host "-- Options --------------------------------------------------" -ForegroundColor White
    Write-Host ""
    $inputDryRun = Read-Host "Dry run? List posts that need audio without triggering anything [y/N]"
    $DRY_RUN     = $inputDryRun -match "^[Yy]$"
}

# ─── Background mode: serialize config and re-launch ─────────────────────────
if ($Background) {
    # Guard against double-launch
    if (Test-Path $PID_FILE) {
        $existingPid  = (Get-Content $PID_FILE -Raw).Trim()
        $existingProc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProc) {
            Write-Err "A background backfill is already running (PID $existingPid)"
            Write-Host "  Use -Status to check its progress"
            Write-Host "  Use -Stop to terminate it first"
            exit 1
        }
        Remove-Item $PID_FILE -ErrorAction SilentlyContinue
    }

    # Serialize gathered config to JSON
    @{
        N8N_WEBHOOK     = $N8N_WEBHOOK
        TTS_SERVICE_URL = $TTS_SERVICE_URL
        TTS_API_KEY     = $TTS_API_KEY
        DRY_RUN         = $DRY_RUN
        GhostUrls       = $GhostUrls
        GhostKeys       = $GhostKeys
    } | ConvertTo-Json -Depth 5 | Set-Content $CFG_FILE -Encoding UTF8

    # Clear previous logs
    if (Test-Path $LOG_FILE_OUT) { Remove-Item $LOG_FILE_OUT -Force }
    if (Test-Path $LOG_FILE_ERR) { Remove-Item $LOG_FILE_ERR -Force }

    # Detect the current PowerShell executable so we re-launch the same version
    $pwshExe = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName

    $proc = Start-Process `
        -FilePath $pwshExe `
        -ArgumentList "-NonInteractive", "-NoProfile", "-File", "`"$SCRIPT_PATH`"", "-Config", "`"$CFG_FILE`"" `
        -RedirectStandardOutput $LOG_FILE_OUT `
        -RedirectStandardError  $LOG_FILE_ERR `
        -WindowStyle Hidden `
        -PassThru

    $proc.Id | Set-Content $PID_FILE -Encoding ASCII

    Write-Host ""
    Write-Success "Backfill launched in background (PID $($proc.Id))"
    Write-Host "  Log file : $LOG_FILE_OUT"
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor White
    Write-Host "  Status : .\backfill-audio.ps1 -Status"
    Write-Host "  Logs   : .\backfill-audio.ps1 -Logs"
    Write-Host "  Stop   : .\backfill-audio.ps1 -Stop"
    Write-Host ""
    exit 0
}

# ─── Helper: fetch all posts from one Ghost site ──────────────────────────────
function Get-AllPosts {
    param([string]$GhostUrl, [string]$GhostKey)

    $allPosts = @()
    $page = 1

    while ($true) {
        $apiUrl  = "$GhostUrl/ghost/api/content/posts/"
        $apiUrl += "?key=$GhostKey"
        $apiUrl += "&fields=id,slug,title,html,url,status"
        $apiUrl += "&limit=15&page=$page&filter=status:published"

        try {
            $response = Invoke-RestMethod -Uri $apiUrl -Method Get -TimeoutSec 20
        } catch {
            throw "Failed to fetch posts (page $page): $_"
        }

        $pagePosts = $response.posts
        if (-not $pagePosts -or $pagePosts.Count -eq 0) { break }

        $allPosts += $pagePosts

        $totalPages = if ($null -ne $response.meta.pagination.pages) { [int]$response.meta.pagination.pages } else { 1 }
        $totalPosts = if ($null -ne $response.meta.pagination.total) { [int]$response.meta.pagination.total } else { $allPosts.Count }
        Write-Host "`r  Fetched $($allPosts.Count) / $totalPosts posts..." -NoNewline

        if ($page -ge $totalPages) { break }
        $page++
    }

    Write-Host ""
    return $allPosts
}

# ─── Counters ─────────────────────────────────────────────────────────────────
$grandTriggered   = 0
$grandAlreadyDone = 0
$grandSkipped     = 0
$grandErrors      = 0

if (-not $skipInteractive) {
    Write-Host ""
    Write-Host "=========================================================" -ForegroundColor White
    Write-Host " Scanning posts..." -ForegroundColor White
    Write-Host "=========================================================" -ForegroundColor White
}

# ─── Per-site processing ──────────────────────────────────────────────────────
for ($siteIdx = 0; $siteIdx -lt $GhostUrls.Count; $siteIdx++) {
    $ghostUrl = $GhostUrls[$siteIdx]
    $ghostKey = $GhostKeys[$siteIdx]
    $siteNum  = $siteIdx + 1

    Write-Host ""
    Write-Host "-- Site $siteNum`: $ghostUrl --" -ForegroundColor White
    Write-Host ""

    Write-Info "Fetching published posts (this may take a moment for large sites)..."

    try {
        $allPosts = Get-AllPosts -GhostUrl $ghostUrl -GhostKey $ghostKey
    } catch {
        Write-Err "Could not fetch posts from $ghostUrl"
        Write-Host "  $_"
        Write-Warn "Skipping this site — verify the URL and Content API key"
        continue
    }

    Write-Success "Found $($allPosts.Count) published posts"

    if ($allPosts.Count -eq 0) { continue }

    # ── Stage 1: posts with no <audio> tag in HTML at all ─────────────────────
    $noTag = @($allPosts | Where-Object {
        $_.html -ne $null -and $_.html -notmatch '<audio[^>]*>'
    })
    $withTag = @($allPosts | Where-Object {
        $_.html -ne $null -and $_.html -match '<audio[^>]*>'
    })

    # ── Stage 2: posts WITH a tag whose gn-audio-embed source 404s ────────────
    # The HTML-tag-presence check is structural; this is a liveness check that
    # catches posts whose embed points at a deleted/missing GCS file. This is
    # the dominant failure mode for sites that have been backfilled before.
    $broken = @()
    if ($withTag.Count -gt 0) {
        Write-Info "Verifying $($withTag.Count) existing audio embed(s)..."
        $idx = 0
        foreach ($post in $withTag) {
            $idx++
            Write-Host "`r  Checking embed: $idx / $($withTag.Count)   " -NoNewline

            # Extract the first <source src="..."> URL from the gn-audio-embed
            # block. The embed has a nested player UI (button + progress bar +
            # speed control) BEFORE <audio>/<source>, so we cannot match
            # `gn-audio-embed` immediately followed by <source>. Two-step:
            #   1. anchor at `id="gn-audio-embed"` and slice forward 20 KB to
            #      bound the search window (prevents picking a later embed's
            #      source URL).
            #   2. extract the first <source src="..."> within that window.
            # If the embed marker is absent, treat as needing narration.
            $html  = ($post.html -as [string]) -replace "`n", ' '
            $anchor = [regex]::Match($html, 'id="gn-audio-embed"', 'IgnoreCase')
            $src = ''
            if ($anchor.Success) {
                $start = $anchor.Index
                $len   = [Math]::Min(20000, $html.Length - $start)
                $block = $html.Substring($start, $len)
                $srcMatch = [regex]::Match(
                    $block,
                    '<source[^>]*src="([^"]+)"',
                    'IgnoreCase'
                )
                if ($srcMatch.Success) { $src = $srcMatch.Groups[1].Value }
            }

            if (-not $src) { $broken += $post; continue }

            try {
                $r = Invoke-WebRequest -Method Head -Uri $src `
                                       -TimeoutSec 5 -UseBasicParsing `
                                       -ErrorAction Stop
                if ([int]$r.StatusCode -ne 200) { $broken += $post }
            } catch {
                $broken += $post
            }
        }
        Write-Host ""
    }

    $needsAudio = @($noTag) + @($broken)
    $hasWorking = $withTag.Count - $broken.Count

    $grandAlreadyDone += $hasWorking

    if ($hasWorking -gt 0)   { Write-Success "$hasWorking posts already have working audio — skipping" }
    if ($broken.Count -gt 0) { Write-Warn    "$($broken.Count) posts have broken/missing audio — re-narrating" }
    if ($noTag.Count -gt 0)  { Write-Warn    "$($noTag.Count) posts have no audio embed — narrating" }

    if ($needsAudio.Count -eq 0) {
        Write-Success "All posts have working audio. Nothing to do for this site."
        continue
    }

    Write-Host ""

    # ── List posts to be processed ────────────────────────────────────────────
    Write-Host "Posts queued for narration:" -ForegroundColor White
    $idx = 1
    foreach ($post in $needsAudio) {
        Write-Host "  $idx. $($post.slug)"
        $idx++
    }
    Write-Host ""

    # ── Dry run ───────────────────────────────────────────────────────────────
    if ($DRY_RUN) {
        Write-Warn "Dry run — no jobs triggered for $ghostUrl"
        $grandSkipped += $needsAudio.Count
        continue
    }

    # ── Confirm (skipped in background worker mode) ───────────────────────────
    if (-not $skipInteractive) {
        $confirm = Read-Host "Trigger all $($needsAudio.Count) jobs for $ghostUrl? [Y/n]"
        if ($confirm -and $confirm -notmatch "^[Yy]$") {
            Write-Warn "Skipped $ghostUrl"
            $grandSkipped += $needsAudio.Count
            continue
        }
    }

    # ── Hostname-derived slug used in JOB_ID and (downstream) the GCS path ────
    # The n8n callback workflow reverse-resolves this to GHOST_SITE{1,2}_*
    # env vars by matching against parseHostname(GHOST_SITE{1,2}_URL).
    $siteSlug = Get-UrlSlug $ghostUrl

    # ── Trigger each post ─────────────────────────────────────────────────────
    $siteTriggered = 0

    foreach ($post in $needsAudio) {
        $siteTriggered++
        $grandTriggered++

        Write-Host ""
        Write-Host "[$siteTriggered/$($needsAudio.Count)] $($post.title)" -ForegroundColor White
        Write-Host "  Slug : $($post.slug)"
        Write-Host "  ID   : $($post.id)"
        Write-Host "  URL  : $($post.url)"

        # Deterministic job ID — same shape n8n's Extract Post Metadata node
        # would generate for a real Ghost webhook, with a 'backfill-' prefix
        # so script-driven runs are visually distinct in the storage tree:
        #   backfill-{hostname-with-dashes}-pid-{postId}-{slug}-{epoch_ms}
        # n8n honours data.backfill_job_id when present and the callback
        # strips the 'backfill-' marker before resolving the admin key.
        $epochMs = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
        $jobId   = "backfill-$siteSlug-pid-$($post.id)-$($post.slug)-$epochMs"

        # Build the webhook payload — same shape Ghost sends, plus backfill_job_id hint
        # so n8n uses our deterministic ID instead of generating a timestamp-based one
        $payload = @{
            post = @{
                current = $post
            }
            backfill_job_id = $jobId
        } | ConvertTo-Json -Depth 10 -Compress

        # Sign the payload when N8N_GHOST_WEBHOOK_SECRET is set so backfill passes
        # the n8n HMAC validator that production webhooks use. Without this,
        # enabling the secret in .env would silently block backfill at the HMAC
        # node (it throws on missing X-Ghost-Signature). Falls back to unsigned
        # when the secret is empty (HMAC node passes through in dev).
        $headers = @{}
        $secret = $env:N8N_GHOST_WEBHOOK_SECRET
        if ($secret) {
            $hmac = $null
            try {
                $hmac = [System.Security.Cryptography.HMACSHA256]::new()
                $hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
                $hashBytes = $hmac.ComputeHash($bytes)
                $hex = -join ($hashBytes | ForEach-Object { '{0:x2}' -f $_ })
                $headers['X-Ghost-Signature'] = "sha256=$hex"
            } catch {
                Write-Warn "HMAC signing failed — sending unsigned (will be rejected if HMAC is enforced)"
                Write-Host "  $($_.Exception.Message)"
            } finally {
                if ($hmac) { $hmac.Dispose() }
            }
        }

        try {
            $wr = Invoke-WebRequest `
                -Uri $N8N_WEBHOOK `
                -Method Post `
                -ContentType "application/json" `
                -Body $payload `
                -Headers $headers `
                -TimeoutSec 15 `
                -UseBasicParsing

            Write-Success "Pipeline triggered (HTTP $($wr.StatusCode))"
            Write-Host "  Job ID : $jobId"
        } catch {
            $statusCode = if ($null -ne $_.Exception.Response) {
                [int]$_.Exception.Response.StatusCode
            } else { 0 }
            Write-Err "Webhook returned HTTP $statusCode — job not queued"
            Write-Host "  $($_.Exception.Message)"
            $grandErrors++
            continue
        }

        # Small spacing between webhook triggers: n8n's default SQLite backend
        # serializes workflow-execution log writes, so a tight burst of 25+
        # triggers can push some responses past the 15s timeout. 50 ms of
        # spacing is enough headroom and adds <2s total for typical batches.
        Start-Sleep -Milliseconds 50
    }
}

# ─── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=========================================================" -ForegroundColor White
Write-Host " Summary" -ForegroundColor White
Write-Host "=========================================================" -ForegroundColor White
Write-Host ""
Write-Success "Already had audio  : $grandAlreadyDone"
Write-Success "Jobs triggered     : $grandTriggered"
if ($grandErrors  -gt 0) { Write-Err  "Trigger errors     : $grandErrors" }
if ($grandSkipped -gt 0) { Write-Warn "Skipped (dry run)  : $grandSkipped" }
Write-Host ""

if ($grandTriggered -gt 0) {
    Write-Host "Jobs are now queued in the TTS service. They will process one at a"
    Write-Host "time on the GPU and complete in the background."
    Write-Host ""
    $n8nBase = $N8N_WEBHOOK -replace '/webhook.*', ''
    Write-Host "Monitor:" -ForegroundColor White
    Write-Host "  Snapshot       : .\scripts\backfill-audio.ps1 -Queue"
    Write-Host "  Live dashboard : .\scripts\backfill-audio.ps1 -Watch"
    Write-Host "  TTS logs       : docker logs -f tts-service"
    Write-Host "  n8n executions : $n8nBase"
    Write-Host ""
    if ($grandErrors -gt 0) {
        Write-Warn "$grandErrors webhook trigger(s) failed."
        Write-Host "  Re-run this script to retry — posts that already have audio are skipped automatically."
        Write-Host ""
    }
}

# ─── Cleanup: remove config + PID files when running as background worker ─────
if ($skipInteractive) {
    if (Test-Path $CFG_FILE) { Remove-Item $CFG_FILE -ErrorAction SilentlyContinue }
    if (Test-Path $PID_FILE) { Remove-Item $PID_FILE -ErrorAction SilentlyContinue }
}
