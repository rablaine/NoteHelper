# Test runner script that ensures clean environment
# Unsets DATABASE_URL and sets TESTING flag before running tests

$env:DATABASE_URL = $null
Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
$env:TESTING = 'true'

# Run pytest with all arguments passed to this script
pytest @args
