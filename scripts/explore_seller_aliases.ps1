# Explore Seller/User Details
# Can we get aliases/emails for sellers from MSX?
#
# Prerequisites:
# 1. Connect to VPN
# 2. Flask app running on localhost:5000
# 3. Run: az login

Write-Host "=== Seller/User Detail Explorer ===" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:5000/api/msx/explore"

# Step 1: Get a sample of account team members to see what user fields are available
Write-Host "=== Step 1: Account Team Member Fields ===" -ForegroundColor Cyan
Write-Host "Checking what fields are available on msp_accountteams..."

try {
    $metadata = Invoke-RestMethod -Uri "$baseUrl/entity-metadata/msp_accountteams" -Method GET -TimeoutSec 30
    
    # Look for user-related fields
    $userFields = $metadata.fields | Where-Object { 
        $_.name -like "*user*" -or 
        $_.name -like "*email*" -or 
        $_.name -like "*alias*" -or
        $_.name -like "*contact*" -or
        $_.name -like "*fullname*" -or
        $_.name -like "*systemuser*"
    }
    
    Write-Host "User-related fields on msp_accountteams:" -ForegroundColor Green
    $userFields | Format-Table name, display_name, type -AutoSize
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

# Step 2: Check if there's a systemuser entity we can query
Write-Host ""
Write-Host "=== Step 2: SystemUser Entity ===" -ForegroundColor Cyan
Write-Host "Checking systemuser entity for email/alias fields..."

try {
    $metadata = Invoke-RestMethod -Uri "$baseUrl/entity-metadata/systemuser" -Method GET -TimeoutSec 30
    
    # Look for identifying fields
    $idFields = $metadata.fields | Where-Object { 
        $_.name -like "*email*" -or 
        $_.name -like "*alias*" -or
        $_.name -like "*name*" -or
        $_.name -like "*domain*" -or
        $_.name -like "*upn*" -or
        $_.name -like "*principal*"
    }
    
    Write-Host "Identity-related fields on systemuser:" -ForegroundColor Green
    $idFields | Format-Table name, display_name, type -AutoSize
} catch {
    Write-Host "Error getting systemuser metadata: $_" -ForegroundColor Red
}

# Step 3: Get a sample systemuser record to see actual data
Write-Host ""
Write-Host "=== Step 3: Sample SystemUser Record ===" -ForegroundColor Cyan

try {
    $selectFields = "fullname,domainname,internalemailaddress,personalemailaddress,windowsliveid,azureactivedirectoryobjectid"
    $users = Invoke-RestMethod -Uri "$baseUrl/entity/systemusers?select=$selectFields&top=5" -Method GET -TimeoutSec 30
    
    Write-Host "Sample systemuser records:" -ForegroundColor Green
    foreach ($user in $users.records) {
        Write-Host "  Name: $($user.fullname)"
        Write-Host "    Domain Name (alias): $($user.domainname)"
        Write-Host "    Internal Email: $($user.internalemailaddress)"
        Write-Host "    Personal Email: $($user.personalemailaddress)"
        Write-Host "    Windows Live ID: $($user.windowsliveid)"
        Write-Host "    AAD Object ID: $($user.azureactivedirectoryobjectid)"
        Write-Host ""
    }
} catch {
    Write-Host "Error getting systemuser records: $_" -ForegroundColor Red
}

# Step 4: Check if we can look up a user by name
Write-Host ""
Write-Host "=== Step 4: Look Up User by Name ===" -ForegroundColor Cyan

# First get a seller name from account teams
try {
    $init = Invoke-RestMethod -Uri "$baseUrl/scan-init" -Method GET -TimeoutSec 30
    $accountId = $init.account_ids[0]
    
    $teams = Invoke-RestMethod -Uri "$baseUrl/entity/msp_accountteams?filter=_msp_accountid_value eq $accountId and msp_qualifier1 eq 'Corporate' and startswith(msp_qualifier2,'Cloud ')&select=msp_fullname,_msp_systemuserid_value&top=3" -Method GET -TimeoutSec 30
    
    if ($teams.records.Count -gt 0) {
        $sellerName = $teams.records[0].msp_fullname
        $systemUserId = $teams.records[0]._msp_systemuserid_value
        
        Write-Host "Found seller: $sellerName" -ForegroundColor Yellow
        Write-Host "SystemUser ID: $systemUserId"
        
        if ($systemUserId) {
            Write-Host ""
            Write-Host "Looking up user details by ID..." -ForegroundColor Yellow
            
            try {
                $selectFields = "fullname,domainname,internalemailaddress,title,jobtitle"
                $userDetail = Invoke-RestMethod -Uri "$baseUrl/entity/systemusers($systemUserId)?select=$selectFields" -Method GET -TimeoutSec 30
                
                Write-Host "User Details:" -ForegroundColor Green
                Write-Host "  Full Name: $($userDetail.fullname)"
                Write-Host "  Domain Name (alias): $($userDetail.domainname)"
                Write-Host "  Email: $($userDetail.internalemailaddress)"
                Write-Host "  Job Title: $($userDetail.jobtitle)"
            } catch {
                Write-Host "Error looking up user by ID: $_" -ForegroundColor Red
            }
        } else {
            Write-Host "No systemuserid link on account team record" -ForegroundColor Yellow
            
            # Try searching by name
            Write-Host ""
            Write-Host "Trying to search by name..." -ForegroundColor Yellow
            $escapedName = $sellerName -replace "'", "''"
            
            try {
                $selectFields = "fullname,domainname,internalemailaddress"
                $searchResult = Invoke-RestMethod -Uri "$baseUrl/entity/systemusers?filter=fullname eq '$escapedName'&select=$selectFields" -Method GET -TimeoutSec 30
                
                if ($searchResult.records.Count -gt 0) {
                    Write-Host "Found by name search:" -ForegroundColor Green
                    foreach ($u in $searchResult.records) {
                        Write-Host "  $($u.fullname) - $($u.domainname) - $($u.internalemailaddress)"
                    }
                } else {
                    Write-Host "No match found by name" -ForegroundColor Yellow
                }
            } catch {
                Write-Host "Error searching by name: $_" -ForegroundColor Red
            }
        }
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

# Step 5: Check all sellers from a few accounts
Write-Host ""
Write-Host "=== Step 5: Batch User Lookup ===" -ForegroundColor Cyan
Write-Host "Checking if we can get aliases for multiple sellers..."

try {
    $init = Invoke-RestMethod -Uri "$baseUrl/scan-init" -Method GET -TimeoutSec 30
    
    # Get unique seller names from first 3 accounts
    $sellerNames = @{}
    foreach ($accountId in $init.account_ids[0..2]) {
        $teams = Invoke-RestMethod -Uri "$baseUrl/entity/msp_accountteams?filter=_msp_accountid_value eq $accountId and msp_qualifier1 eq 'Corporate' and startswith(msp_qualifier2,'Cloud ')&select=msp_fullname,_msp_systemuserid_value&top=10" -Method GET -TimeoutSec 30
        
        foreach ($t in $teams.records) {
            if ($t.msp_fullname -and -not $sellerNames.ContainsKey($t.msp_fullname)) {
                $sellerNames[$t.msp_fullname] = $t._msp_systemuserid_value
            }
        }
    }
    
    Write-Host "Found $($sellerNames.Count) unique sellers" -ForegroundColor Green
    Write-Host ""
    
    # Look up each seller
    $results = @()
    foreach ($name in $sellerNames.Keys) {
        $userId = $sellerNames[$name]
        $alias = $null
        $email = $null
        
        if ($userId) {
            try {
                $user = Invoke-RestMethod -Uri "$baseUrl/entity/systemusers($userId)?select=domainname,internalemailaddress" -Method GET -TimeoutSec 10
                $alias = $user.domainname
                $email = $user.internalemailaddress
            } catch {
                # Try by name
            }
        }
        
        if (-not $alias) {
            # Try searching by name
            $escapedName = $name -replace "'", "''"
            try {
                $search = Invoke-RestMethod -Uri "$baseUrl/entity/systemusers?filter=fullname eq '$escapedName'&select=domainname,internalemailaddress&top=1" -Method GET -TimeoutSec 10
                if ($search.records.Count -gt 0) {
                    $alias = $search.records[0].domainname
                    $email = $search.records[0].internalemailaddress
                }
            } catch {}
        }
        
        $results += [PSCustomObject]@{
            Name = $name
            Alias = $alias
            Email = $email
            HasSystemUserId = [bool]$userId
        }
    }
    
    Write-Host "Results:" -ForegroundColor Green
    $results | Format-Table -AutoSize
    
    $withAlias = ($results | Where-Object { $_.Alias }).Count
    Write-Host ""
    Write-Host "Summary: $withAlias / $($results.Count) sellers have resolvable aliases" -ForegroundColor Cyan
    
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Conclusion ===" -ForegroundColor Cyan
Write-Host "If we can resolve aliases, we can add this to the import process."
