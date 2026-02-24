# MSX Revenue Exploration Script
# Run this after authenticating with: az login --tenant 72f988bf-86f1-41af-91ab-2d7cd011db47

param(
    [string]$AccountId = "",  # Optional: specific account ID to query
    [string]$TPID = ""        # Optional: TPID to look up account first
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

Write-Host "=== MSX Revenue Exploration ===" -ForegroundColor Cyan
Write-Host ""

# If TPID provided, look up account first
if ($TPID) {
    Write-Host "Looking up account by TPID: $TPID" -ForegroundColor Yellow
    $url = "$baseUrl/accounts?`$filter=msp_mstopparentid eq $TPID&`$select=accountid,name,msp_mstopparentid&`$top=1"
    $result = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
    if ($result.value.Count -gt 0) {
        $AccountId = $result.value[0].accountid
        Write-Host "Found: $($result.value[0].name) (ID: $AccountId)" -ForegroundColor Green
    } else {
        Write-Host "No account found for TPID $TPID" -ForegroundColor Red
        exit 1
    }
    Write-Host ""
}

# Step 1: Search for revenue-related entities
Write-Host "=== Step 1: Searching for revenue-related entities ===" -ForegroundColor Cyan

$revenueKeywords = @("revenue", "consumption", "usage", "billing", "forecast", "acr", "azure")
$entitySearchUrl = "$baseUrl/EntityDefinitions?`$select=LogicalName,DisplayName,Description"

Write-Host "Fetching entity definitions..." -ForegroundColor Gray
$entities = Invoke-RestMethod -Uri $entitySearchUrl -Headers $headers -Method Get

$relevantEntities = @()
foreach ($entity in $entities.value) {
    $logicalName = $entity.LogicalName
    $displayName = $entity.DisplayName.UserLocalizedLabel.Label
    
    foreach ($keyword in $revenueKeywords) {
        if ($logicalName -like "*$keyword*" -or $displayName -like "*$keyword*") {
            $relevantEntities += [PSCustomObject]@{
                LogicalName = $logicalName
                DisplayName = $displayName
            }
            break
        }
    }
}

Write-Host "`nFound $($relevantEntities.Count) potentially revenue-related entities:" -ForegroundColor Green
$relevantEntities | Format-Table -AutoSize

# Step 2: Look at account fields for revenue data
Write-Host "`n=== Step 2: Account revenue-related fields ===" -ForegroundColor Cyan

$accountMetaUrl = "$baseUrl/EntityDefinitions(LogicalName='account')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
$accountAttrs = Invoke-RestMethod -Uri $accountMetaUrl -Headers $headers -Method Get

$revenueFields = @()
foreach ($attr in $accountAttrs.value) {
    $logicalName = $attr.LogicalName
    $displayName = $attr.DisplayName.UserLocalizedLabel.Label
    $attrType = $attr.AttributeType
    
    foreach ($keyword in $revenueKeywords) {
        if ($logicalName -like "*$keyword*" -or ($displayName -and $displayName -like "*$keyword*")) {
            $revenueFields += [PSCustomObject]@{
                Field = $logicalName
                DisplayName = $displayName
                Type = $attrType
            }
            break
        }
    }
}

Write-Host "Account fields with revenue keywords:" -ForegroundColor Green
$revenueFields | Format-Table -AutoSize

# Step 3: If we have an account, query its revenue data
if ($AccountId) {
    Write-Host "`n=== Step 3: Querying account $AccountId ===" -ForegroundColor Cyan
    
    # Get all the revenue fields we found
    $fieldsToSelect = ($revenueFields.Field | Where-Object { $_ }) -join ","
    if ($fieldsToSelect) {
        $url = "$baseUrl/accounts($AccountId)?`$select=name,$fieldsToSelect"
        try {
            $account = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
            Write-Host "Account: $($account.name)" -ForegroundColor Green
            
            foreach ($field in $revenueFields) {
                $value = $account.$($field.Field)
                $formattedValue = $account."$($field.Field)@OData.Community.Display.V1.FormattedValue"
                if ($value -or $formattedValue) {
                    Write-Host "  $($field.DisplayName): $formattedValue ($value)" -ForegroundColor White
                }
            }
        } catch {
            Write-Host "Error querying account: $_" -ForegroundColor Red
        }
    }
}

# Step 4: Look for msp_consumption or similar entities
Write-Host "`n=== Step 4: Checking for consumption/revenue entities ===" -ForegroundColor Cyan

$consumptionEntities = @(
    "msp_consumptions",
    "msp_revenueforecasts", 
    "msp_azureconsumptionrevenues",
    "msp_azureusages",
    "msp_billings",
    "msp_accountrevenues",
    "revenues"
)

foreach ($entityName in $consumptionEntities) {
    Write-Host "Trying $entityName... " -NoNewline
    try {
        $url = "$baseUrl/$entityName`?`$top=1"
        $result = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -ErrorAction SilentlyContinue
        Write-Host "EXISTS! ($($result.value.Count) sample records)" -ForegroundColor Green
        
        # Show fields
        $metaUrl = "$baseUrl/EntityDefinitions(LogicalName='$($entityName.TrimEnd('s'))')/Attributes?`$select=LogicalName,DisplayName,AttributeType&`$top=50"
        try {
            $meta = Invoke-RestMethod -Uri $metaUrl -Headers $headers -Method Get -ErrorAction SilentlyContinue
            Write-Host "  Fields: " -NoNewline
            $fieldNames = ($meta.value.LogicalName | Select-Object -First 10) -join ", "
            Write-Host $fieldNames -ForegroundColor Gray
        } catch {}
        
        # If we have account ID, try filtering
        if ($AccountId -and $result.value.Count -gt 0) {
            # Try to find account-linked records
            $sample = $result.value[0]
            $accountFields = $sample.PSObject.Properties.Name | Where-Object { $_ -like "*account*" }
            if ($accountFields) {
                Write-Host "  Account link fields: $($accountFields -join ', ')" -ForegroundColor Yellow
            }
        }
    } catch {
        Write-Host "not found" -ForegroundColor DarkGray
    }
}

# Step 5: Check opportunities for revenue
Write-Host "`n=== Step 5: Opportunity revenue fields ===" -ForegroundColor Cyan

$oppMetaUrl = "$baseUrl/EntityDefinitions(LogicalName='opportunity')/Attributes?`$select=LogicalName,DisplayName,AttributeType"
$oppAttrs = Invoke-RestMethod -Uri $oppMetaUrl -Headers $headers -Method Get

$oppRevenueFields = @()
foreach ($attr in $oppAttrs.value) {
    $logicalName = $attr.LogicalName
    $displayName = $attr.DisplayName.UserLocalizedLabel.Label
    
    if ($logicalName -like "*revenue*" -or $logicalName -like "*amount*" -or $logicalName -like "*value*" -or 
        ($displayName -and ($displayName -like "*revenue*" -or $displayName -like "*amount*"))) {
        $oppRevenueFields += [PSCustomObject]@{
            Field = $logicalName
            DisplayName = $displayName
            Type = $attr.AttributeType
        }
    }
}

Write-Host "Opportunity revenue fields:" -ForegroundColor Green
$oppRevenueFields | Select-Object -First 20 | Format-Table -AutoSize

# If we have account, show its opportunities
if ($AccountId) {
    Write-Host "`nOpportunities for account $AccountId`:" -ForegroundColor Yellow
    $revenueFieldsStr = "name,estimatedvalue,actualvalue,msp_azureinfluencedrevenue,msp_totalvalue"
    $url = "$baseUrl/opportunities?`$filter=_parentaccountid_value eq $AccountId&`$select=$revenueFieldsStr&`$top=10"
    try {
        $opps = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
        foreach ($opp in $opps.value) {
            Write-Host "  $($opp.name)" -ForegroundColor White
            Write-Host "    Est Value: $($opp.'estimatedvalue@OData.Community.Display.V1.FormattedValue')" -ForegroundColor Gray
            Write-Host "    Actual: $($opp.'actualvalue@OData.Community.Display.V1.FormattedValue')" -ForegroundColor Gray
            Write-Host "    Azure Influenced: $($opp.'msp_azureinfluencedrevenue@OData.Community.Display.V1.FormattedValue')" -ForegroundColor Gray
        }
    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
    }
}

Write-Host "`n=== Exploration Complete ===" -ForegroundColor Cyan
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Run with -TPID parameter to explore a specific customer"
Write-Host "2. Check the entities listed above for your revenue data"
Write-Host "3. Look at your exported report columns and map them to fields"
