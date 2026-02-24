# Power BI API Explorer
# Explores whether we can programmatically access the ACR report
#
# Prerequisites:
# 1. Connect to VPN (MSX reports are internal)
# 2. Login: az login
# 3. Run this script

Write-Host "=== Power BI API Explorer ===" -ForegroundColor Cyan
Write-Host ""

# Get token for Power BI API
Write-Host "Getting Power BI API token..." -ForegroundColor Yellow
try {
    $tokenResponse = az account get-access-token --resource "https://analysis.windows.net/powerbi/api" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to get token. Make sure you're logged in with: az login" -ForegroundColor Red
        Write-Host $tokenResponse
        exit 1
    }
    $token = ($tokenResponse | ConvertFrom-Json).accessToken
    Write-Host "Got token (first 50 chars): $($token.Substring(0, 50))..." -ForegroundColor Green
} catch {
    Write-Host "Error getting token: $_" -ForegroundColor Red
    exit 1
}

$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

# Step 1: List all workspaces (groups) we have access to
Write-Host ""
Write-Host "=== Step 1: Listing Workspaces ===" -ForegroundColor Cyan
try {
    $workspaces = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups" -Headers $headers -Method Get
    Write-Host "Found $($workspaces.value.Count) workspaces:" -ForegroundColor Green
    
    # Save to file for review
    $workspaces.value | ForEach-Object {
        Write-Host "  - $($_.name) (ID: $($_.id))" 
    }
    
    # Look for MSX-related workspaces
    $msxWorkspaces = $workspaces.value | Where-Object { $_.name -like "*MSX*" -or $_.name -like "*SME*" -or $_.name -like "*ACR*" }
    if ($msxWorkspaces) {
        Write-Host ""
        Write-Host "Potentially relevant workspaces:" -ForegroundColor Yellow
        $msxWorkspaces | ForEach-Object {
            Write-Host "  * $($_.name)" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "Error listing workspaces: $_" -ForegroundColor Red
    Write-Host "Response: $($_.Exception.Response)" -ForegroundColor Red
}

# Step 2: Search for the specific report
Write-Host ""
Write-Host "=== Step 2: Searching for ACR Report ===" -ForegroundColor Cyan
Write-Host "Looking for 'SME&C ACR Service Level Subscription Details'..."

$foundReport = $null
$foundWorkspace = $null

foreach ($workspace in $workspaces.value) {
    try {
        $reports = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups/$($workspace.id)/reports" -Headers $headers -Method Get
        
        foreach ($report in $reports.value) {
            if ($report.name -like "*ACR*" -or $report.name -like "*SME*C*" -or $report.name -like "*Service Level*") {
                Write-Host "  Found in '$($workspace.name)': $($report.name)" -ForegroundColor Green
                Write-Host "    Report ID: $($report.id)"
                Write-Host "    Web URL: $($report.webUrl)"
                
                if ($report.name -like "*SME*C*ACR*" -or $report.name -like "*Service Level Subscription*") {
                    $foundReport = $report
                    $foundWorkspace = $workspace
                }
            }
        }
    } catch {
        # Some workspaces may not be accessible
        continue
    }
}

# Step 3: Try to get dataset info if we found the report
if ($foundReport) {
    Write-Host ""
    Write-Host "=== Step 3: Exploring Found Report ===" -ForegroundColor Cyan
    Write-Host "Report: $($foundReport.name)"
    
    # Get the dataset
    try {
        $datasetId = $foundReport.datasetId
        Write-Host "Dataset ID: $datasetId"
        
        $dataset = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups/$($foundWorkspace.id)/datasets/$datasetId" -Headers $headers -Method Get
        Write-Host "Dataset Name: $($dataset.name)"
        Write-Host "Configured By: $($dataset.configuredBy)"
        
        # Try to get tables
        Write-Host ""
        Write-Host "Attempting to list tables..." -ForegroundColor Yellow
        try {
            $tables = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups/$($foundWorkspace.id)/datasets/$datasetId/tables" -Headers $headers -Method Get
            Write-Host "Tables found:" -ForegroundColor Green
            $tables.value | ForEach-Object {
                Write-Host "  - $($_.name)"
            }
        } catch {
            Write-Host "Could not list tables (may require different permissions)" -ForegroundColor Yellow
        }
        
        # Check export capabilities
        Write-Host ""
        Write-Host "=== Export Options ===" -ForegroundColor Cyan
        Write-Host "Option 1: Export to File API"
        Write-Host "  POST https://api.powerbi.com/v1.0/myorg/groups/$($foundWorkspace.id)/reports/$($foundReport.id)/ExportTo"
        Write-Host "  Formats: PDF, PNG, PPTX, CSV (for paginated reports)"
        
        Write-Host ""
        Write-Host "Option 2: Execute DAX Query (if dataset allows)"
        Write-Host "  POST https://api.powerbi.com/v1.0/myorg/groups/$($foundWorkspace.id)/datasets/$datasetId/executeQueries"
        
    } catch {
        Write-Host "Error exploring dataset: $_" -ForegroundColor Red
    }
} else {
    Write-Host ""
    Write-Host "Could not find the specific ACR report automatically." -ForegroundColor Yellow
    Write-Host "The report might be in a workspace you don't have API access to."
    Write-Host ""
    Write-Host "Alternative: Try opening MSX Insights, find the report, and get the workspace/report ID from the URL."
}

# Step 4: List all reports we can see (for manual searching)
Write-Host ""
Write-Host "=== All Accessible Reports (for reference) ===" -ForegroundColor Cyan
$allReports = @()
foreach ($workspace in $workspaces.value) {
    try {
        $reports = Invoke-RestMethod -Uri "https://api.powerbi.com/v1.0/myorg/groups/$($workspace.id)/reports" -Headers $headers -Method Get
        foreach ($report in $reports.value) {
            $allReports += [PSCustomObject]@{
                Workspace = $workspace.name
                ReportName = $report.name
                ReportId = $report.id
            }
        }
    } catch {
        continue
    }
}

Write-Host "Total reports accessible: $($allReports.Count)"
if ($allReports.Count -gt 0 -and $allReports.Count -le 50) {
    $allReports | Format-Table -AutoSize
} elseif ($allReports.Count -gt 50) {
    Write-Host "(Too many to display - saving to scripts/powerbi_reports.csv)"
    $allReports | Export-Csv -Path "scripts/powerbi_reports.csv" -NoTypeInformation
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "The Power BI REST API can potentially automate report exports, but:"
Write-Host "1. You need access to the workspace containing the ACR report"
Write-Host "2. Export format depends on report type (paginated vs. interactive)"
Write-Host "3. For data extraction, DAX query execution may work if the dataset allows it"
Write-Host ""
Write-Host "Next step: If you see the report above, we can try exporting data from it."
