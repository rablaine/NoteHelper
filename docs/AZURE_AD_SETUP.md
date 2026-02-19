# Azure AD Authentication Setup Guide

NoteHelper now supports Azure AD (Entra ID) OAuth authentication. This guide walks you through setting up authentication for your deployment.

## Overview

The application uses Microsoft Authentication Library (MSAL) to authenticate users via Azure Active Directory. Once configured, users will sign in with their Microsoft accounts and the app automatically creates a user profile.

## Prerequisites

- An Azure subscription
- Admin access to your Azure AD tenant (or ability to register applications)
- NoteHelper application running

## Step-by-Step Setup

### 1. Register Application in Azure Portal

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** > **App registrations**
3. Click **New registration**
4. Fill in the registration form:
   - **Name:** NoteHelper (or your preferred name)
   - **Supported account types:** 
     - Choose "Accounts in this organizational directory only" for single tenant
     - Or "Accounts in any organizational directory" for multi-tenant
   - **Redirect URI:** 
     - Platform: **Web**
     - URI: `http://localhost:5000/auth/callback` (for local development)
     - For production: `https://yourdomain.com/auth/callback`
5. Click **Register**

### 2. Configure Application

#### Add Client Secret

1. In your newly registered app, go to **Certificates & secrets**
2. Click **New client secret**
3. Add a description (e.g., "NoteHelper Production Key")
4. Choose expiration period (recommendation: 24 months)
5. Click **Add**
6. **Important:** Copy the secret **Value** immediately (you won't be able to see it again!)

#### Configure API Permissions

1. Go to **API permissions**
2. The app should already have **User.Read** permission (Microsoft Graph)
3. If not, click **Add a permission** > **Microsoft Graph** > **Delegated permissions** > Select **User.Read**
4. Click **Add permissions**
5. (Optional) Click **Grant admin consent** if you have admin privileges

### 3. Configure Application Environment

1. Copy the following values from your Azure AD app registration:
   - **Application (client) ID** - from the Overview page
   - **Directory (tenant) ID** - from the Overview page
   - **Client secret Value** - from the secret you just created

2. Update your `.env` file:

```bash
# Azure AD OAuth Configuration
AZURE_CLIENT_ID=your-application-client-id-here
AZURE_CLIENT_SECRET=your-client-secret-value-here
AZURE_TENANT_ID=your-directory-tenant-id-here
AZURE_REDIRECT_URI=http://localhost:5000/auth/callback
```

3. For production deployment, update `AZURE_REDIRECT_URI` to match your production URL:
```bash
AZURE_REDIRECT_URI=https://yourdomain.com/auth/callback
```

### 4. Update Azure AD Redirect URIs (for Production)

When deploying to production:

1. Go back to your Azure AD app registration
2. Navigate to **Authentication**
3. Under **Web** redirect URIs, click **Add URI**
4. Enter your production callback URL: `https://yourdomain.com/auth/callback`
5. Click **Save**

## Testing Authentication

1. Restart your Flask application to load the new environment variables
2. Navigate to `http://localhost:5000`
3. You should be redirected to Microsoft's login page
4. Sign in with your Microsoft account
5. After successful authentication, you'll be redirected back to NoteHelper

## Troubleshooting

### "Authentication failed: No authorization code received"

- Check that your redirect URI in Azure AD matches exactly what's in your `.env` file
- Ensure the URL includes the protocol (`http://` or `https://`)

### "AADSTS50011: The reply URL specified in the request does not match"

- The redirect URI in your app doesn't match what's registered in Azure AD
- Go to Azure AD > App registrations > Your app > Authentication
- Verify the redirect URI is exactly `http://localhost:5000/auth/callback` (or your production URL)

### "Azure AD authentication is not configured"

- Your `.env` file is missing Azure AD configuration
- Check that `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_TENANT_ID` are set
- Restart the Flask application after updating `.env`

### Users can't access the app

- Ensure you've granted **User.Read** permission in Azure AD
- If using single-tenant setup, ensure users are in your Azure AD tenant
- Check Azure AD sign-in logs for detailed error messages

## Security Best Practices

1. **Never commit secrets to Git**
   - `.env` file is in `.gitignore` by default
   - Use environment variables or Azure Key Vault for production

2. **Rotate client secrets regularly**
   - Set expiration periods on secrets
   - Update `.env` file before expiration

3. **Use HTTPS in production**
   - HTTP redirect URIs are only for local development
   - Production must use HTTPS

4. **Limit application permissions**
   - Only request `User.Read` scope (default)
   - Don't add unnecessary Microsoft Graph permissions

## Multi-Tenant Setup (Optional)

If you want to allow users from any Azure AD tenant:

1. In Azure AD app registration, go to **Authentication**
2. Under **Supported account types**, select:
   - "Accounts in any organizational directory (Any Azure AD directory - Multitenant)"
3. Update `.env`:
```bash
AZURE_TENANT_ID=common
```

## Removing Authentication (Development Only)

To disable authentication temporarily for local development:

1. Comment out the Azure AD configuration in `.env`
2. The app will show a warning but continue to work
3. **Note:** This is not recommended for production

## Additional Resources

- [Microsoft Identity Platform Documentation](https://docs.microsoft.com/en-us/azure/active-directory/develop/)
- [MSAL Python Documentation](https://msal-python.readthedocs.io/)
- [Azure AD App Registration Guide](https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
