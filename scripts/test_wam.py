"""Test MSAL broker (WAM) - Windows native account picker."""
from msal import PublicClientApplication
import base64
import json

TENANT_ID = '72f988bf-86f1-41af-91ab-2d7cd011db47'
CLIENT_ID = '14d82eec-204b-4c2f-b7e8-296a70dab67e'  # Graph PowerShell

app = PublicClientApplication(
    CLIENT_ID,
    authority=f'https://login.microsoftonline.com/{TENANT_ID}',
    enable_broker_on_windows=True
)

scopes = ['User.Read', 'Calendars.Read', 'OnlineMeetings.Read']
print('Opening Windows account picker...')
print('Look for a native Windows dialog (not browser)!')

result = app.acquire_token_interactive(
    scopes=scopes, 
    prompt='select_account',
    parent_window_handle=app.CONSOLE_WINDOW_HANDLE
)

if 'access_token' in result:
    print('\nSUCCESS! Got token')
    # Decode scopes
    parts = result['access_token'].split('.')
    payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
    claims = json.loads(base64.b64decode(payload))
    scp = claims.get('scp', 'none')
    print(f'Scopes in token: {scp}')
else:
    print(f'\nError: {result.get("error_description", result)}')
