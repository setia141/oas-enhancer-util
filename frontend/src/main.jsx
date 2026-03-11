import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MsalProvider } from '@azure/msal-react'
import { msalInstance } from './auth/msalConfig'
import App from './App.jsx'
import './index.css'

// Must initialize and process any redirect response BEFORE rendering,
// otherwise MSAL loses the auth code from the URL on first render.
msalInstance.initialize().then(async () => {
  await msalInstance.handleRedirectPromise()

  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <MsalProvider instance={msalInstance}>
        <App />
      </MsalProvider>
    </StrictMode>,
  )
})
