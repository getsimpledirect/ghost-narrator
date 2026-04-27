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
# Finds all published Ghost posts that do not yet have an <audio> player
# embedded and triggers the Ghost Narrator n8n pipeline for each one,
# polling the TTS service for job completion before proceeding to the next
# article (no fixed delay).
#
# Usage:
#   .\backfill-audio.ps1                     # Interactive foreground run
#   .\backfill-audio.ps1 -Background         # Collect config then run in background
#   .\backfill-audio.ps1 -Status             # Show background run status + last log lines
#   .\backfill-audio.ps1 -Logs               # Tail background run log (Ctrl+C to stop)
#   .\backfill-audio.ps1 -Stop               # Stop the background run
#
# Requirements:
#   PowerShell 5.1+ (built into Windows) or PowerShell 7+
# ═══════════════════════════════════════════════════════════════════════════════

param(
    [switch]$Background,
    [switch]$Status,
    [switch]$Logs,
    [switch]$Stop,
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

# ─── Callback site identifier auto-detection ────────────────────────────────
# Match a Ghost URL against GHOST_SITE{1,2}_URL from env to determine the
# canonical callback site identifier ('site1' / 'site2'). Returns empty
# when neither env URL is set or neither matches. Mirrors the n8n Extract
# Post Metadata node's hostname.includes() semantics so script and n8n
# always pick the same answer.
function Get-CallbackSiteId {
    param([string]$Url)
    if (-not $Url) { return '' }
    $hostIn = $Url -replace '^https?://', '' -replace '/.*$', '' -replace ':\d+$', ''
    $s1 = [Environment]::GetEnvironmentVariable('GHOST_SITE1_URL', 'Process')
    $s2 = [Environment]::GetEnvironmentVariable('GHOST_SITE2_URL', 'Process')
    $s1Host = if ($s1) { $s1 -replace '^https?://', '' -replace '/.*$', '' -replace ':\d+$', '' } else { '' }
    $s2Host = if ($s2) { $s2 -replace '^https?://', '' -replace '/.*$', '' -replace ':\d+$', '' } else { '' }
    if ($s1Host -and $hostIn.Contains($s1Host)) { return 'site1' }
    if ($s2Host -and $hostIn.Contains($s2Host)) { return 'site2' }
    return ''
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
    # SiteCallbackIds carries the n8n-side site identifier (site1 / site2) used
    # to look up admin API keys in the callback workflow. Older config files
    # don't have this — fall back to "site{N}" by index.
    if ($cfg.PSObject.Properties.Name -contains 'SiteCallbackIds') {
        $SiteCallbackIds = @($cfg.SiteCallbackIds)
    } else {
        $SiteCallbackIds = 1..$GhostUrls.Count | ForEach-Object { "site$_" }
    }
    $skipInteractive = $true
}

# ─── Polling constants ────────────────────────────────────────────────────────
$POLL_INTERVAL = 15     # seconds between status checks
$N8N_TIMEOUT   = 600    # seconds before assuming n8n/LLM pipeline stalled
$MAX_WAIT      = 1800   # absolute maximum wait per job (30 min)

# ─── Banner + interactive prompts ─────────────────────────────────────────────
if (-not $skipInteractive) {
    Write-Host ""
    Write-Host "=========================================================" -ForegroundColor White
    Write-Host " Ghost Narrator — Audio Backfill" -ForegroundColor White
    Write-Host "=========================================================" -ForegroundColor White
    Write-Host ""
    Write-Host "Scans your Ghost site(s) for published posts that do not yet have"
    Write-Host "an audio player embedded, then triggers the narration pipeline for"
    Write-Host "each one, polling until each job completes before starting the next."
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

    $GhostUrls       = @()
    $GhostKeys       = @()
    $SiteCallbackIds = @()

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

        # Callback site identifier — must match GHOST_SITE{N}_ADMIN_API_KEY
        # in n8n env. The callback workflow only knows 'site1' or 'site2';
        # anything else fails the admin-API lookup and the embed step never
        # runs. Auto-detect by matching this Ghost URL against
        # GHOST_SITE{1,2}_URL in .env so script and n8n always agree.
        $detectedCb = Get-CallbackSiteId $ghostUrl
        if ($detectedCb) {
            $siteCb = Read-Host "    Callback site identifier (auto-detected from .env) [$detectedCb]"
            $SiteCallbackIds += if ($siteCb) { $siteCb } else { $detectedCb }
        } else {
            $defaultCb = "site$i"
            $siteCb    = Read-Host "    Callback site identifier (site1 or site2) [$defaultCb]"
            $SiteCallbackIds += if ($siteCb) { $siteCb } else { $defaultCb }
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
        SiteCallbackIds = $SiteCallbackIds
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

# ─── Helper: poll TTS service until job completes ─────────────────────────────
# Returns $true on success, $false on failure/timeout.
#
# Phase logic:
#   HTTP 404 → n8n is still running the LLM step; job not yet submitted to TTS
#   status=queued/processing → TTS synthesis is running
#   status=completed → success
#   status=failed    → failure
#   elapsed > N8N_TIMEOUT while still 404 → n8n pipeline stalled
#   elapsed > MAX_WAIT → give up
function Wait-ForJob {
    param(
        [string]$JobId,
        [string]$TtsUrl,
        [string]$TtsApiKey,
        [int]$PollInterval,
        [int]$N8nTimeout,
        [int]$MaxWait
    )

    $elapsed        = 0
    $n8nLogged      = $false
    $ttsLogged      = $false
    $authHeaders    = @{ Authorization = "Bearer $TtsApiKey" }

    while ($elapsed -lt $MaxWait) {
        Start-Sleep -Seconds $PollInterval
        $elapsed += $PollInterval

        $statusUrl = "$TtsUrl/tts/status/$JobId"
        $httpCode  = 0
        $body      = $null

        try {
            $wr   = Invoke-WebRequest -Uri $statusUrl -Method Get -TimeoutSec 10 `
                        -UseBasicParsing -Headers $authHeaders
            $body = $wr.Content | ConvertFrom-Json
            $httpCode = [int]$wr.StatusCode
        } catch {
            # Determine HTTP status code from exception (works on both PS5.1 and PS7)
            if ($null -ne $_.Exception.Response) {
                $httpCode = [int]$_.Exception.Response.StatusCode
            } else {
                $httpCode = 0
            }
        }

        # 401/403 = bad API key. Bail with a clear message instead of polling forever.
        if ($httpCode -eq 401 -or $httpCode -eq 403) {
            Write-Host ""
            Write-Err "  TTS service rejected the API key (HTTP $httpCode). Check TTS_API_KEY matches the running service."
            return $false
        }

        # 404 = n8n LLM phase (job not yet registered in TTS)
        if ($httpCode -eq 404) {
            if (-not $n8nLogged) {
                Write-Host ""
                Write-Info "  n8n pipeline processing (LLM narration phase)..."
                $n8nLogged = $true
            }
            if ($elapsed -ge $N8nTimeout) {
                Write-Host ""
                Write-Err "  n8n did not submit TTS job after ${N8nTimeout}s — pipeline may have stalled"
                Write-Host "  Check n8n execution logs for errors"
                return $false
            }
            Write-Host "`r  LLM phase: ${elapsed}s / ${N8nTimeout}s max  " -NoNewline
            continue
        }

        # Non-404 error or connection failure
        if ($null -eq $body -or $httpCode -eq 0) {
            Write-Host "`r  TTS poll error (HTTP $httpCode, ${elapsed}s elapsed)  " -NoNewline
            continue
        }

        $jobStatus = $body.status

        switch ($jobStatus) {
            "queued" {
                if (-not $ttsLogged) {
                    Write-Host ""
                    Write-Info "  TTS job queued — waiting for synthesis to start..."
                    $ttsLogged = $true
                }
                Write-Host "`r  Status: queued     — ${elapsed}s elapsed  " -NoNewline
            }
            "processing" {
                Write-Host "`r  Status: processing — ${elapsed}s elapsed  " -NoNewline
            }
            "completed" {
                Write-Host ""
                Write-Success "  TTS job completed in ${elapsed}s"
                return $true
            }
            "failed" {
                Write-Host ""
                $errMsg = if ($null -ne $body.error -and $body.error -ne "") { $body.error } else { "unknown error" }
                Write-Err "  TTS job failed: $errMsg"
                return $false
            }
            default {
                Write-Host "`r  Status: $jobStatus — ${elapsed}s elapsed  " -NoNewline
            }
        }
    }

    Write-Host ""
    Write-Err "  Timed out after ${MaxWait}s waiting for job $JobId"
    return $false
}

# ─── Counters ─────────────────────────────────────────────────────────────────
$grandTriggered   = 0
$grandAlreadyDone = 0
$grandSkipped     = 0
$grandCompleted   = 0
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

    # ── Split into has-audio / needs-audio ────────────────────────────────────
    $needsAudio = @($allPosts | Where-Object {
        $_.html -ne $null -and $_.html -notmatch '<audio[^>]*>'
    })
    $hasAudio = @($allPosts | Where-Object {
        $_.html -ne $null -and $_.html -match '<audio[^>]*>'
    })

    $grandAlreadyDone += $hasAudio.Count

    if ($hasAudio.Count -gt 0) {
        Write-Success "$($hasAudio.Count) posts already have audio — skipping"
    }

    if ($needsAudio.Count -eq 0) {
        Write-Success "All posts have audio. Nothing to do for this site."
        continue
    }

    Write-Warn "$($needsAudio.Count) posts need audio narration"
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

    # ── Resolve the site's callback identifier (site1 / site2) for job_id ────
    # The n8n callback workflow indexes admin API keys by this slug and rejects
    # any value other than 'site1' or 'site2'.
    $siteCallbackId = $SiteCallbackIds[$siteIdx]

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
        # would generate for a real Ghost webhook:
        #   {site1|site2}-pid-{postId}-{slug}-{epoch_seconds}
        # n8n honors data.backfill_job_id when present, so we can poll the
        # exact ID we computed here. Including the epoch keeps re-runs unique.
        $epoch  = [DateTimeOffset]::Now.ToUnixTimeSeconds()
        $jobId  = "$siteCallbackId-pid-$($post.id)-$($post.slug)-$epoch"

        # Build the webhook payload — same shape Ghost sends, plus backfill_job_id hint
        # so n8n uses our deterministic ID instead of generating a timestamp-based one
        $payload = @{
            post = @{
                current = $post
            }
            backfill_job_id = $jobId
        } | ConvertTo-Json -Depth 10 -Compress

        try {
            $wr = Invoke-WebRequest `
                -Uri $N8N_WEBHOOK `
                -Method Post `
                -ContentType "application/json" `
                -Body $payload `
                -TimeoutSec 15 `
                -UseBasicParsing

            Write-Success "Pipeline triggered (HTTP $($wr.StatusCode))"
            Write-Host "  Job ID : $jobId"
        } catch {
            $statusCode = if ($null -ne $_.Exception.Response) {
                [int]$_.Exception.Response.StatusCode
            } else { 0 }
            Write-Err "Webhook returned HTTP $statusCode — job may not have been queued"
            Write-Host "  $($_.Exception.Message)"
            $grandErrors++
            continue
        }

        # Poll until this job completes before moving to the next article
        Write-Info "  Polling TTS service for job completion..."
        $ok = Wait-ForJob `
            -JobId       $jobId `
            -TtsUrl      $TTS_SERVICE_URL `
            -TtsApiKey   $TTS_API_KEY `
            -PollInterval $POLL_INTERVAL `
            -N8nTimeout  $N8N_TIMEOUT `
            -MaxWait     $MAX_WAIT

        if ($ok) {
            $grandCompleted++
        } else {
            $grandErrors++
            Write-Warn "  Continuing to next article — check logs for: $jobId"
        }
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
Write-Success "Jobs completed     : $grandCompleted"
if ($grandErrors  -gt 0) { Write-Err  "Errors             : $grandErrors" }
if ($grandSkipped -gt 0) { Write-Warn "Skipped (dry run)  : $grandSkipped" }
Write-Host ""

if ($grandTriggered -gt 0) {
    $n8nBase = $N8N_WEBHOOK -replace '/webhook.*', ''
    Write-Host "Monitor progress:" -ForegroundColor White
    Write-Host "  n8n executions : $n8nBase"
    Write-Host "  TTS jobs       : $TTS_SERVICE_URL/docs"
    Write-Host ""
    if ($grandErrors -gt 0) {
        Write-Warn "$grandErrors job(s) encountered errors."
        Write-Host "  Re-run this script to retry — posts that already have audio are skipped automatically."
        Write-Host ""
    }
}

# ─── Cleanup: remove config + PID files when running as background worker ─────
if ($skipInteractive) {
    if (Test-Path $CFG_FILE) { Remove-Item $CFG_FILE -ErrorAction SilentlyContinue }
    if (Test-Path $PID_FILE) { Remove-Item $PID_FILE -ErrorAction SilentlyContinue }
}
