import { PublicClientApplication, LogLevel } from '@azure/msal-browser'

export const msalConfig = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID,
    authority: `https://login.microsoftonline.com/${import.meta.env.VITE_AZURE_TENANT_ID}`,
    redirectUri: import.meta.env.VITE_REDIRECT_URI || window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: 'sessionStorage',
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii || import.meta.env.PROD) return
        if (level === LogLevel.Error) console.error('[MSAL]', message)
        if (level === LogLevel.Warning) console.warn('[MSAL]', message)
      },
    },
  },
}

// Basic scopes — group membership is read from ID token claims,
// so GroupMember.Read.All (admin consent) is NOT required.
export const graphScopes = {
  scopes: ['openid', 'profile', 'email'],
}

// The Azure AD group Object ID that is allowed to access this app
export const ALLOWED_GROUP_ID = import.meta.env.VITE_AZURE_ALLOWED_GROUP_ID

export const msalInstance = new PublicClientApplication(msalConfig)
