# MSX Insights Report Explorer
# Attempts to access the ACR report via MSX Insights API
#
# Report URL: https://msxinsights.microsoft.com/User/report/47b95fcd-1857-47f2-9c4b-8413a508ae00
# Report ID: 47b95fcd-1857-47f2-9c4b-8413a508ae00

param(
    [string]$ReportId = "47b95fcd-1857-47f2-9c4b-8413a508ae00"
)

Write-Host "=== MSX Insights Report Explorer ===" -ForegroundColor Cyan
Write-Host "Target Report: $ReportId"
Write-Host ""

# Try different token resources
$resources = @(
    @{ Name = "Power BI"; Resource = "https://analysis.windows.net/powerbi/api" },
    @{ Name = "MSX Insights"; Resource = "https://msxinsights.microsoft.com" },
    @{ Name = "Graph API"; Resource = "https://graph.microsoft.com" }
)

$tokens = @{}
foreach ($r in $resources) {
    Write-Host "Getting token for $($r.Name)..." -ForegroundColor Yellow
    try {
        $tokenResponse = az account get-access-token --resource $r.Resource 2>&1
        if ($LASTEXITCODE -eq 0) {
            $tokens[$r.Name] = ($tokenResponse | ConvertFrom-Json).accessToken
            Write-Host "  Got token" -ForegroundColor Green
        } else {
            Write-Host "  Failed (resource may not be valid)" -ForegroundColor Red
        }
    } catch {
        Write-Host "  Error: $_" -ForegroundColor Red
    }
}

# Approach 1: Try MSX Insights API directly
Write-Host ""
Write-Host "=== Approach 1: MSX Insights API ===" -ForegroundColor Cyan

$msxiEndpoints = @(
    "https://msxinsights.microsoft.com/api/report/$ReportId",
    "https://msxinsights.microsoft.com/api/reports/$ReportId",
    "https://msxinsights.microsoft.com/api/User/report/$ReportId",
    "https://msxinsights.microsoft.com/api/v1/report/$ReportId"
)

foreach ($endpoint in $msxiEndpoints) {
    Write-Host "Trying: $endpoint" -ForegroundColor Yellow
    try {
        # Try with Power BI token first
        if ($tokens["Power BI"]) {
            $headers = @{ "Authorization" = "Bearer $($tokens['Power BI'])"; "Content-Type" = "application/json" }
            $response = Invoke-RestMethod -Uri $endpoint -Headers $headers -Method Get -TimeoutSec 10
            Write-Host "  Success with Power BI token!" -ForegroundColor Green
            $response | ConvertTo-Json -Depth 3 | Write-Host
            break
        }
    } catch {
        $status = $_.Exception.Response.StatusCode.value__
        Write-Host "  Status: $status" -ForegroundColor Gray
    }
}

# Approach 2: Search Power BI for report by ID
Write-Host ""
Write-Host "=== Approach 2: Search Power BI by Report ID ===" -ForegroundColor Cyan

if ($tokens["Power BI"]) {
    $pbiHeaders = @{ "Authorization" = "Bearer $($tokens['Power BI'])"; "Content-Type" = "application/json" }
    
    # Try direct report access (if we had workspace access)
    Write-Host "Searching all accessible workspaces for report $ReportId..." -ForegroundColor Yellow
    
    try {
        $workspaces = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups" -Headers $pbiHeaders -Method Get
        
        foreach ($ws in $workspaces.value) {
            try {
                $reports = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups/$($ws.id)/reports" -Headers $pbiHeaders -Method Get
                $match = $reports.value | Where-Object { $_.id -eq $ReportId }
                if ($match) {
                    Write-Host "FOUND in workspace: $($ws.name)" -ForegroundColor Green
                    Write-Host "  Report Name: $($match.name)"
                    Write-Host "  Report ID: $($match.id)"
                    Write-Host "  Web URL: $($match.webUrl)"
                    Write-Host "  Dataset ID: $($match.datasetId)"
                    
                    # Try to get more details
                    Write-Host ""
                    Write-Host "Attempting to get dataset info..." -ForegroundColor Yellow
                    try {
                        $dataset = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups/$($ws.id)/datasets/$($match.datasetId)" -Headers $pbiHeaders -Method Get
                        Write-Host "  Dataset Name: $($dataset.name)"
                        Write-Host "  Configured By: $($dataset.configuredBy)"
                        Write-Host "  Is Refreshable: $($dataset.isRefreshable)"
                    } catch {
                        Write-Host "  Could not get dataset details" -ForegroundColor Red
                    }
                    break
                }
            } catch {
                continue
            }
        }
    } catch {
        Write-Host "Error searching workspaces: $_" -ForegroundColor Red
    }
}

# Approach 3: Try admin API (if we have admin rights)
Write-Host ""
Write-Host "=== Approach 3: Admin API (requires tenant admin) ===" -ForegroundColor Cyan

if ($tokens["Power BI"]) {
    $pbiHeaders = @{ "Authorization" = "Bearer $($tokens['Power BI'])"; "Content-Type" = "application/json" }
    
    Write-Host "Trying admin/reports endpoint..." -ForegroundColor Yellow
    try {
        $report = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/admin/reports/$ReportId" -Headers $pbiHeaders -Method Get
        Write-Host "Found via admin API!" -ForegroundColor Green
        $report | ConvertTo-Json -Depth 3 | Write-Host
    } catch {
        $status = $_.Exception.Response.StatusCode.value__
        Write-Host "  Status: $status (expected - admin access required)" -ForegroundColor Gray
    }
}

# Approach 4: Check if it's a paginated report (different API)
Write-Host ""
Write-Host "=== Approach 4: Check Paginated Reports ===" -ForegroundColor Cyan

if ($tokens["Power BI"]) {
    $pbiHeaders = @{ "Authorization" = "Bearer $($tokens['Power BI'])"; "Content-Type" = "application/json" }
    
    Write-Host "Searching for paginated reports..." -ForegroundColor Yellow
    try {
        $workspaces = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups" -Headers $pbiHeaders -Method Get
        
        $foundPaginated = $false
        foreach ($ws in $workspaces.value) {
            try {
                # Paginated reports have a different endpoint
                $paginatedReports = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups/$($ws.id)/reports?`$filter=reportType eq 'PaginatedReport'" -Headers $pbiHeaders -Method Get -ErrorAction SilentlyContinue
                if ($paginatedReports.value) {
                    foreach ($pr in $paginatedReports.value) {
                        if ($pr.id -eq $ReportId) {
                            Write-Host "FOUND as Paginated Report in: $($ws.name)" -ForegroundColor Green
                            $pr | ConvertTo-Json | Write-Host
                            $foundPaginated = $true
                            break
                        }
                    }
                }
            } catch {
                continue
            }
            if ($foundPaginated) { break }
        }
        
        if (-not $foundPaginated) {
            Write-Host "Not found as paginated report in accessible workspaces" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "The report ID $ReportId was not found in workspaces you have API access to."
Write-Host ""
Write-Host "This typically means:"
Write-Host "1. The report is in a workspace where you have View-only access (not Member/Contributor)"
Write-Host "2. MSX Insights uses a different permission model than direct Power BI API"
Write-Host ""
Write-Host "Alternatives:"
Write-Host "1. Power Automate - Create a scheduled flow to export the report"
Write-Host "2. Request Contributor access to the workspace from the report owner"
Write-Host "3. Use the manual export process (your current workflow)"
Write-Host ""
Write-Host "To find the workspace owner, in MSX Insights click the report info/settings icon."
