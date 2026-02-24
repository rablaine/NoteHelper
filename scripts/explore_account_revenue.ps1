# Deep dive into account and opportunity revenue data
# Looking for historical revenue/ACR data tied to accounts

param(
    [string]$TPID = "100362167"  # Default TPID - change to one from your data
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

Write-Host "=== Account Revenue Deep Dive ===" -ForegroundColor Cyan
Write-Host "TPID: $TPID" -ForegroundColor Yellow
Write-Host ""

# Step 1: Get account by TPID
Write-Host "=== Step 1: Finding account ===" -ForegroundColor Cyan
$url = "$baseUrl/accounts?`$filter=msp_mstopparentid eq '$TPID'&`$top=1"
$acctResult = Invoke-RestMethod -Uri $url -Headers $headers -Method Get

if ($acctResult.value.Count -eq 0) {
    Write-Host "No account found for TPID $TPID" -ForegroundColor Red
    exit 1
}

$accountId = $acctResult.value[0].accountid
$accountName = $acctResult.value[0].name
Write-Host "Found: $accountName (ID: $accountId)" -ForegroundColor Green

# Step 2: Get ALL account fields to find ACR-related ones
Write-Host "`n=== Step 2: Account fields with revenue/acr/azure/consumption ===" -ForegroundColor Cyan

$metaUrl = "$baseUrl/EntityDefinitions(LogicalName='account')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
$meta = Invoke-RestMethod -Uri $metaUrl -Headers $headers -Method Get

$revenueFields = @()
$keywords = @("revenue", "acr", "azure", "consumption", "billing", "spend", "usage", "arr", "forecast")

foreach ($attr in $meta.value) {
    $logicalName = $attr.LogicalName
    $displayName = $attr.DisplayName.UserLocalizedLabel.Label
    
    foreach ($kw in $keywords) {
        if ($logicalName -like "*$kw*" -or ($displayName -and $displayName -like "*$kw*")) {
            $revenueFields += [PSCustomObject]@{
                Field = $logicalName
                DisplayName = $displayName
                Type = $attr.AttributeType
            }
            break
        }
    }
}

$revenueFields | Sort-Object Field | Format-Table -AutoSize

# Step 3: Query account with these fields
Write-Host "`n=== Step 3: Getting account revenue data ===" -ForegroundColor Cyan

$selectFields = ($revenueFields.Field | Where-Object { $_ -notlike "*_base" -and $_ -notlike "*name" }) -join ","
$url = "$baseUrl/accounts($accountId)?`$select=name,$selectFields"

try {
    $account = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
    
    Write-Host "Account: $($account.name)" -ForegroundColor Green
    Write-Host "`nRevenue fields with values:" -ForegroundColor Yellow
    
    foreach ($field in $revenueFields) {
        $value = $account.$($field.Field)
        $formattedValue = $account."$($field.Field)@OData.Community.Display.V1.FormattedValue"
        if ($value -or $value -eq 0) {
            $displayVal = if ($formattedValue) { $formattedValue } else { $value }
            Write-Host "  $($field.DisplayName) [$($field.Field)]: $displayVal" -ForegroundColor White
        }
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

# Step 4: Look for related entities that might have historical data
Write-Host "`n=== Step 4: Search for historical ACR entities ===" -ForegroundColor Cyan

# Search for entities that might contain ACR history
$entitySearchUrl = "$baseUrl/EntityDefinitions?`$select=LogicalName,DisplayName,Description"
$entities = Invoke-RestMethod -Uri $entitySearchUrl -Headers $headers -Method Get

$acrKeywords = @("acr", "arr", "monthly", "consumption", "usage", "billing", "spend", "fiscal")
$potentialEntities = @()

foreach ($entity in $entities.value) {
    $logicalName = $entity.LogicalName
    $displayName = $entity.DisplayName.UserLocalizedLabel.Label
    $description = $entity.Description.UserLocalizedLabel.Label
    
    foreach ($kw in $acrKeywords) {
        if ($logicalName -like "*$kw*" -or ($displayName -and $displayName -like "*$kw*") -or 
            ($description -and $description -like "*$kw*")) {
            $potentialEntities += [PSCustomObject]@{
                Entity = $logicalName
                DisplayName = $displayName
            }
            break
        }
    }
}

Write-Host "Potential entities with historical data:" -ForegroundColor Green
$potentialEntities | Format-Table -AutoSize

# Step 5: Try some likely entity names
Write-Host "`n=== Step 5: Checking specific entities ===" -ForegroundColor Cyan

$tryEntities = @(
    @{Name="msp_monthlyacrs"; Filter="_msp_accountid_value eq $accountId"},
    @{Name="msp_acrhistories"; Filter="_msp_accountid_value eq $accountId"},
    @{Name="msp_revenuehistories"; Filter="_msp_accountid_value eq $accountId"},
    @{Name="msp_accounthistories"; Filter="_msp_accountid_value eq $accountId"},
    @{Name="msp_consumptionhistories"; Filter="_msp_accountid_value eq $accountId"},
    @{Name="msp_fiscalperiodmetrics"; Filter=""},
    @{Name="msp_accountmetrics"; Filter=""},
    @{Name="msp_workloadconsumptions"; Filter=""},
    @{Name="msp_azureusages"; Filter=""}
)

foreach ($ent in $tryEntities) {
    Write-Host "Checking $($ent.Name)... " -NoNewline
    try {
        $filter = if ($ent.Filter) { "&`$filter=$($ent.Filter)" } else { "" }
        $url = "$baseUrl/$($ent.Name)?`$top=3$filter"
        $result = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -ErrorAction SilentlyContinue
        Write-Host "EXISTS! ($($result.value.Count) records)" -ForegroundColor Green
        
        if ($result.value.Count -gt 0) {
            $sample = $result.value[0]
            Write-Host "  Sample fields:" -ForegroundColor Gray
            $sample.PSObject.Properties | Where-Object { 
                $_.Value -and $_.Name -notlike "*@*" -and $_.Name -notlike "_*"
            } | Select-Object -First 8 | ForEach-Object {
                Write-Host "    $($_.Name): $($_.Value)" -ForegroundColor DarkGray
            }
        }
    } catch {
        Write-Host "not found" -ForegroundColor DarkGray
    }
}

# Step 6: Check milestones for consumption data
Write-Host "`n=== Step 6: Milestone consumption data ===" -ForegroundColor Cyan

$url = "$baseUrl/msp_engagementmilestones?`$filter=_msp_parentaccount_value eq '$accountId'&`$select=msp_name,msp_milestonestatus,msp_monthlyuse,msp_azureinfluencedrevenue,msp_actualrevenueinfluenced&`$top=10"
try {
    $milestones = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
    
    Write-Host "Milestones with consumption data:" -ForegroundColor Green
    foreach ($m in $milestones.value) {
        if ($m.msp_monthlyuse -or $m.msp_azureinfluencedrevenue -or $m.msp_actualrevenueinfluenced) {
            Write-Host "  $($m.msp_name)" -ForegroundColor White
            if ($m.msp_monthlyuse) { Write-Host "    Monthly Use: $($m.'msp_monthlyuse@OData.Community.Display.V1.FormattedValue')" -ForegroundColor Gray }
            if ($m.msp_azureinfluencedrevenue) { Write-Host "    Azure Influenced: $($m.'msp_azureinfluencedrevenue@OData.Community.Display.V1.FormattedValue')" -ForegroundColor Gray }
            if ($m.msp_actualrevenueinfluenced) { Write-Host "    Actual Influenced: $($m.'msp_actualrevenueinfluenced@OData.Community.Display.V1.FormattedValue')" -ForegroundColor Gray }
        }
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

Write-Host "`n=== Complete ===" -ForegroundColor Cyan
Write-Host "What specific fields/columns do you have in your revenue report?"
Write-Host "Share a few column names and I can search for matching MSX fields."
