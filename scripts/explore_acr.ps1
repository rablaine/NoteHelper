# MSX ACR Feed Exploration Script
# Explore the chr1_msxacrfeed entity for Azure Consumption Revenue data

param(
    [string]$TPID = "",        # Optional: filter by TPID
    [int]$Top = 10             # Number of records to fetch
)

$ErrorActionPreference = "Stop"

# Get token
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

Write-Host "=== MSX ACR Feed Exploration ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Get metadata for chr1_msxacrfeed
Write-Host "=== Step 1: chr1_msxacrfeed fields ===" -ForegroundColor Cyan

try {
    $metaUrl = "$baseUrl/EntityDefinitions(LogicalName='chr1_msxacrfeed')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
    $meta = Invoke-RestMethod -Uri $metaUrl -Headers $headers -Method Get
    
    $fields = @()
    foreach ($attr in $meta.value) {
        $fields += [PSCustomObject]@{
            Field = $attr.LogicalName
            DisplayName = $attr.DisplayName.UserLocalizedLabel.Label
            Type = $attr.AttributeType
        }
    }
    
    Write-Host "Found $($fields.Count) fields:" -ForegroundColor Green
    $fields | Where-Object { $_.Field -notlike "versionnumber" -and $_.Field -notlike "*_base" -and $_.Type -ne "Virtual" } | 
              Sort-Object DisplayName | 
              Format-Table -AutoSize
    
} catch {
    Write-Host "Error getting metadata: $_" -ForegroundColor Red
    Write-Host "Entity might not be accessible or doesn't exist" -ForegroundColor Yellow
}

# Step 2: Try to query sample records
Write-Host "`n=== Step 2: Sample records ===" -ForegroundColor Cyan

try {
    $url = "$baseUrl/chr1_msxacrfeeds?`$top=$Top"
    $result = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
    
    Write-Host "Got $($result.value.Count) records" -ForegroundColor Green
    
    if ($result.value.Count -gt 0) {
        # Show all fields from first record
        Write-Host "`nFirst record fields:" -ForegroundColor Yellow
        $firstRecord = $result.value[0]
        $firstRecord.PSObject.Properties | Where-Object { 
            $_.Value -and 
            $_.Name -notlike "*@*" -and 
            $_.Name -notlike "_*_value" 
        } | ForEach-Object {
            Write-Host "  $($_.Name): $($_.Value)" -ForegroundColor White
        }
        
        # Show lookup fields with formatted values
        Write-Host "`nLookup fields:" -ForegroundColor Yellow
        $firstRecord.PSObject.Properties | Where-Object { 
            $_.Name -like "_*_value" -and $_.Value
        } | ForEach-Object {
            $formattedName = $_.Name + "@OData.Community.Display.V1.FormattedValue"
            $formattedValue = $firstRecord.$formattedName
            Write-Host "  $($_.Name): $($_.Value) ($formattedValue)" -ForegroundColor White
        }
    }
} catch {
    Write-Host "Error querying chr1_msxacrfeeds: $_" -ForegroundColor Red
}

# Step 3: Also check msp_consumptionplan which exists
Write-Host "`n=== Step 3: msp_consumptionplan entity ===" -ForegroundColor Cyan

try {
    $metaUrl = "$baseUrl/EntityDefinitions(LogicalName='msp_consumptionplan')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
    $meta = Invoke-RestMethod -Uri $metaUrl -Headers $headers -Method Get
    
    $cpFields = @()
    foreach ($attr in $meta.value) {
        $cpFields += [PSCustomObject]@{
            Field = $attr.LogicalName
            DisplayName = $attr.DisplayName.UserLocalizedLabel.Label
            Type = $attr.AttributeType
        }
    }
    
    Write-Host "Consumption Plan fields (filtered):" -ForegroundColor Green
    $cpFields | Where-Object { 
        $_.Type -ne "Virtual" -and 
        $_.Field -notlike "*_base" -and
        $_.Field -notlike "versionnumber" -and
        ($_.Field -like "*revenue*" -or $_.Field -like "*amount*" -or $_.Field -like "*acr*" -or 
         $_.Field -like "*consumption*" -or $_.Field -like "*value*" -or $_.Field -like "*account*" -or
         $_.Field -like "*tpid*" -or $_.Field -like "*customer*" -or $_.Field -like "*date*" -or
         $_.DisplayName -like "*revenue*" -or $_.DisplayName -like "*ACR*")
    } | Sort-Object Field | Format-Table -AutoSize
    
    # Try to query
    Write-Host "`nSample consumption plans:" -ForegroundColor Yellow
    $url = "$baseUrl/msp_consumptionplans?`$top=3&`$select=msp_name,createdon,msp_status"
    $cpResult = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
    
    foreach ($cp in $cpResult.value) {
        Write-Host "  $($cp.msp_name) - Status: $($cp.'msp_status@OData.Community.Display.V1.FormattedValue') - Created: $($cp.createdon)" -ForegroundColor White
    }
    
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

# Step 4: Check for any msp_ entities with revenue/acr in name
Write-Host "`n=== Step 4: Other potential revenue entities ===" -ForegroundColor Cyan

$possibleEntities = @(
    "msp_azurecoreengagements",
    "msp_accountmetrics", 
    "msp_accountsnapshots",
    "msp_customerinsights",
    "msp_azureusagemetrics"
)

foreach ($entity in $possibleEntities) {
    Write-Host "Checking $entity... " -NoNewline
    try {
        $url = "$baseUrl/$entity`?`$top=1"
        $result = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -ErrorAction SilentlyContinue
        Write-Host "EXISTS!" -ForegroundColor Green
        
        if ($result.value.Count -gt 0) {
            $sample = $result.value[0]
            $relevantFields = $sample.PSObject.Properties | Where-Object {
                $_.Value -and 
                $_.Name -notlike "*@*" -and 
                ($_.Name -like "*revenue*" -or $_.Name -like "*acr*" -or $_.Name -like "*amount*" -or $_.Name -like "*value*")
            }
            if ($relevantFields) {
                foreach ($f in $relevantFields) {
                    Write-Host "  $($f.Name): $($f.Value)" -ForegroundColor Gray
                }
            }
        }
    } catch {
        Write-Host "not found" -ForegroundColor DarkGray
    }
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "What columns are in your revenue report? I can help map them to these fields."
