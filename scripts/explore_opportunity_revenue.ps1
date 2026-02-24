# Explore Azure Consumption Process and Opportunities for ACR data

param(
    [string]$AccountId = "ef6d6f28-15f0-4967-8b39-169ff38618d8"  # Agadia Systems Inc.
)

$ErrorActionPreference = "Stop"

function Get-MsxToken {
    $result = az account get-access-token --resource "https://microsoftsales.crm.dynamics.com" --tenant "72f988bf-86f1-41af-91ab-2d7cd011db47" --output json | ConvertFrom-Json
    return $result.accessToken
}

$token = Get-MsxToken
$headers = @{
    "Authorization" = "Bearer $token"
    "Accept" = "application/json"
    "OData-MaxVersion" = "4.0"
    "OData-Version" = "4.0"
    "Prefer" = 'odata.include-annotations="*"'
}
$baseUrl = "https://microsoftsales.crm.dynamics.com/api/data/v9.2"

Write-Host "=== Azure Consumption & Opportunity Revenue ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Azure Consumption Process metadata
Write-Host "=== Step 1: msp_azureconsumptionprocess fields ===" -ForegroundColor Cyan

try {
    $metaUrl = "$baseUrl/EntityDefinitions(LogicalName='msp_azureconsumptionprocess')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
    $meta = Invoke-RestMethod -Uri $metaUrl -Headers $headers -Method Get
    
    $fields = $meta.value | Where-Object { 
        $_.AttributeType -ne "Virtual" -and 
        $_.LogicalName -notlike "*_base" -and
        $_.LogicalName -notlike "versionnumber"
    } | ForEach-Object {
        [PSCustomObject]@{
            Field = $_.LogicalName
            DisplayName = $_.DisplayName.UserLocalizedLabel.Label
            Type = $_.AttributeType
        }
    }
    
    Write-Host "Consumption Process fields:" -ForegroundColor Green
    $fields | Sort-Object Field | Format-Table -AutoSize
    
    # Query sample
    Write-Host "`nSample consumption processes:" -ForegroundColor Yellow
    $url = "$baseUrl/msp_azureconsumptionprocess1s?`$top=3"
    $result = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -ErrorAction SilentlyContinue
    
    if ($result.value.Count -gt 0) {
        foreach ($cp in $result.value) {
            Write-Host "  Process ID: $($cp.msp_azureconsumptionprocess1id)" -ForegroundColor White
            $cp.PSObject.Properties | Where-Object { 
                $_.Value -and $_.Name -notlike "*@*" -and $_.Name -notlike "_*" -and $_.Name -ne "msp_azureconsumptionprocess1id"
            } | Select-Object -First 5 | ForEach-Object {
                Write-Host "    $($_.Name): $($_.Value)" -ForegroundColor Gray
            }
        }
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

# Step 2: Get ALL opportunity fields with revenue/acr/azure keywords
Write-Host "`n=== Step 2: ALL Opportunity revenue-related fields ===" -ForegroundColor Cyan

$metaUrl = "$baseUrl/EntityDefinitions(LogicalName='opportunity')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
$oppMeta = Invoke-RestMethod -Uri $metaUrl -Headers $headers -Method Get

$keywords = @("revenue", "acr", "azure", "consumption", "billing", "actual", "estimated", "value", "amount", "arr", "monthly", "annual")
$oppFields = @()

foreach ($attr in $oppMeta.value) {
    $logicalName = $attr.LogicalName
    $displayName = $attr.DisplayName.UserLocalizedLabel.Label
    
    foreach ($kw in $keywords) {
        if ($logicalName -like "*$kw*" -or ($displayName -and $displayName -like "*$kw*")) {
            $oppFields += [PSCustomObject]@{
                Field = $logicalName
                DisplayName = $displayName
                Type = $attr.AttributeType
            }
            break
        }
    }
}

Write-Host "Found $($oppFields.Count) revenue-related opportunity fields:" -ForegroundColor Green
$oppFields | Where-Object { $_.Type -ne "Virtual" -and $_.Field -notlike "*name" -and $_.Field -notlike "*_base" } | 
             Sort-Object Field | 
             Format-Table -AutoSize

# Step 3: Query opportunities with revenue fields for this account
Write-Host "`n=== Step 3: Opportunities with revenue data for account ===" -ForegroundColor Cyan

# Build select with key fields
$keyFields = @(
    "name", "statecode", "statuscode",
    "estimatedvalue", "actualvalue", "totalamount",
    "msp_billedrevenue", "msp_azureinterimforecast", "msp_azureestimatedrevenue",
    "msp_totalacr", "msp_totalcontractvalue", "msp_cloudacr",
    "msp_annualsolutionconsumption", "msp_runrate", "msp_azureannualrevenue"
)

$selectStr = $keyFields -join ","
$url = "$baseUrl/opportunities?`$filter=_parentaccountid_value eq $AccountId&`$select=$selectStr&`$top=20"

try {
    $opps = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
    
    Write-Host "Found $($opps.value.Count) opportunities" -ForegroundColor Green
    
    foreach ($opp in $opps.value) {
        $status = $opp."statecode@OData.Community.Display.V1.FormattedValue"
        Write-Host "`n  $($opp.name) [$status]" -ForegroundColor White
        
        foreach ($field in $keyFields) {
            if ($field -ne "name" -and $field -ne "statecode" -and $field -ne "statuscode") {
                $value = $opp.$field
                $formatted = $opp."$field@OData.Community.Display.V1.FormattedValue"
                if ($value -or $value -eq 0) {
                    $displayVal = if ($formatted) { $formatted } else { $value }
                    Write-Host "    $field`: $displayVal" -ForegroundColor Gray
                }
            }
        }
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    # Try with fewer fields
    Write-Host "`nTrying with basic fields only..." -ForegroundColor Yellow
    $url = "$baseUrl/opportunities?`$filter=_parentaccountid_value eq $AccountId&`$select=name,estimatedvalue,actualvalue&`$top=5"
    try {
        $opps = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
        foreach ($opp in $opps.value) {
            Write-Host "  $($opp.name): Est=$($opp.'estimatedvalue@OData.Community.Display.V1.FormattedValue'), Actual=$($opp.'actualvalue@OData.Community.Display.V1.FormattedValue')" -ForegroundColor Gray
        }
    } catch {
        Write-Host "Still failed: $_" -ForegroundColor Red
    }
}

# Step 4: Check for Engagement Milestone fields
Write-Host "`n=== Step 4: Milestone fields with revenue/consumption ===" -ForegroundColor Cyan

$metaUrl = "$baseUrl/EntityDefinitions(LogicalName='msp_engagementmilestone')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
$msMeta = Invoke-RestMethod -Uri $metaUrl -Headers $headers -Method Get

$msRevFields = @()
foreach ($attr in $msMeta.value) {
    $logicalName = $attr.LogicalName
    $displayName = $attr.DisplayName.UserLocalizedLabel.Label
    
    foreach ($kw in $keywords) {
        if ($logicalName -like "*$kw*" -or ($displayName -and $displayName -like "*$kw*")) {
            $msRevFields += [PSCustomObject]@{
                Field = $logicalName
                DisplayName = $displayName
                Type = $attr.AttributeType
            }
            break
        }
    }
}

Write-Host "Milestone revenue fields:" -ForegroundColor Green
$msRevFields | Where-Object { $_.Type -ne "Virtual" -and $_.Field -notlike "*_base" } | 
               Sort-Object Field | 
               Format-Table -AutoSize

Write-Host "`n=== Done ===" -ForegroundColor Cyan
