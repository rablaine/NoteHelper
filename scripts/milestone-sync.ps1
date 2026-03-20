# Sales Buddy - Scheduled Milestone Sync
# Called by the SalesBuddy-MilestoneSync Windows scheduled task.
# Hits the local Flask API to trigger a non-SSE milestone sync.
# Logs output to logs/milestone-sync.log for troubleshooting.
#
# Usage:
#   .\scripts\milestone-sync.ps1          (reads PORT from .env, defaults to 5151)

param()

$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

# Set up logging
$LogDir = Join-Path $RepoRoot 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = Join-Path $LogDir 'milestone-sync.log'

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $entry = "[$ts] [$Level] $Message"
    Add-Content -Path $LogFile -Value $entry
    switch ($Level) {
        'ERROR'   { Write-Host $Message -ForegroundColor Red }
        'WARN'    { Write-Host $Message -ForegroundColor Yellow }
        'SUCCESS' { Write-Host $Message -ForegroundColor Green }
        default   { Write-Host $Message }
    }
}

# Trim log to last 500 lines if it gets large
if (Test-Path $LogFile) {
    $lineCount = (Get-Content $LogFile -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    if ($lineCount -gt 1000) {
        $tail = Get-Content $LogFile -Tail 500
        Set-Content -Path $LogFile -Value $tail
    }
}

Write-Log '--- Milestone sync started ---'

# Read port from .env
$Port = 5151
if (Test-Path "$RepoRoot\.env") {
    $envLines = Get-Content "$RepoRoot\.env" -ErrorAction SilentlyContinue
    foreach ($line in $envLines) {
        if ($line -match '^\s*PORT\s*=\s*(\d+)') {
            $Port = [int]$Matches[1]
        }
    }
}

$Url = "http://localhost:$Port/api/milestone-tracker/sync"

# Check if server is running
try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conn) {
        Write-Log "Sales Buddy is not running on port $Port - skipping sync." 'WARN'
        exit 0
    }
} catch {
    Write-Log "Could not check port $Port - skipping sync." 'WARN'
    exit 0
}

# Trigger sync (fires in background on server, returns 202 immediately)
try {
    Write-Log "Triggering milestone sync at $Url ..."
    $response = Invoke-RestMethod -Uri $Url -Method POST -ContentType 'application/json' -TimeoutSec 30
    if ($response.async) {
        Write-Log 'Sync triggered successfully (running in background on server).' 'SUCCESS'
    } elseif ($response.success) {
        Write-Log "Sync complete: $($response.customers_synced) customers, $($response.milestones_created) new, $($response.milestones_updated) updated." 'SUCCESS'
    } else {
        Write-Log "Sync returned partial results or failed: $($response | ConvertTo-Json -Compress)" 'WARN'
    }
} catch {
    $errDetail = $_.Exception.Message
    if ($_.Exception.Response) {
        try {
            $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
            $body = $reader.ReadToEnd()
            $reader.Close()
            $errDetail += " | Response body: $body"
        } catch { }
    }
    Write-Log "Milestone sync request failed: $errDetail" 'ERROR'
    Write-Log '--- Milestone sync finished with error ---'
    exit 1
}

Write-Log '--- Milestone sync finished ---'
