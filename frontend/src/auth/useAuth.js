/**
 * useAuth — MSAL wrapper with automatic Azure AD redirect and group membership check.
 *
 * States:
 *  loading      → MSAL in progress (redirect handling, token acquisition, group check)
 *  unauthorized → signed in but not in the required Azure AD group
 *  authorized   → signed in AND group-verified
 *
 * There is NO unauthenticated state exposed to the UI — if no account is found,
 * loginRedirect() fires immediately and the browser navigates to Azure AD.
 */
import { useEffect, useRef, useState } from 'react'
import { useMsal } from '@azure/msal-react'
import { InteractionStatus } from '@azure/msal-browser'
import { graphScopes, ALLOWED_GROUP_ID } from './msalConfig'

async function checkGroupMembership(instance, account) {
  if (!ALLOWED_GROUP_ID) return true

  // Primary: read groups from ID token claims — no admin consent needed.
  // Requires "Security groups" claim enabled in Azure AD App Registration →
  // Token configuration → Add groups claim.
  const tokenGroups = account.idTokenClaims?.groups
  if (Array.isArray(tokenGroups)) {
    return tokenGroups.includes(ALLOWED_GROUP_ID)
  }

  // Fallback: token claims not configured or user is in >200 groups (overage).
  // Calls Graph API — requires GroupMember.Read.All admin consent.
  try {
    const tokenResp = await instance.acquireTokenSilent({
      scopes: ['GroupMember.Read.All'],
      account,
    })
    const resp = await fetch('https://graph.microsoft.com/v1.0/me/checkMemberGroups', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${tokenResp.accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ groupIds: [ALLOWED_GROUP_ID] }),
    })
    if (!resp.ok) throw new Error(`Graph API ${resp.status}`)
    const data = await resp.json()
    return data.value?.includes(ALLOWED_GROUP_ID) ?? false
  } catch {
    throw new Error(
      'Group membership could not be verified. ' +
      'Enable "Security groups" claim in Azure AD App Registration → Token configuration, ' +
      'or grant admin consent for GroupMember.Read.All.'
    )
  }
}

export function useAuth() {
  const { instance, accounts, inProgress } = useMsal()
  const [status, setStatus] = useState('loading')
  const [user, setUser] = useState(null)
  const [groupError, setGroupError] = useState(null)
  const redirecting = useRef(false)

  const account = accounts[0] ?? null

  useEffect(() => {
    // Wait until MSAL has finished any in-progress interaction (e.g. handleRedirectPromise)
    if (inProgress !== InteractionStatus.None) return

    if (!account) {
      // No session — kick off redirect to Azure AD immediately, no button needed
      if (!redirecting.current) {
        redirecting.current = true
        instance.loginRedirect(graphScopes).catch(console.error)
      }
      return
    }

    // Account found — verify group membership
    setStatus('loading')
    setGroupError(null)

    checkGroupMembership(instance, account)
      .then((isMember) => {
        if (isMember) {
          setUser({
            name: account.name || account.username,
            email: account.username,
            accountId: account.homeAccountId,
          })
          setStatus('authorized')
        } else {
          setStatus('unauthorized')
        }
      })
      .catch((err) => {
        console.error('Group check failed:', err)
        setGroupError(err.message)
        setStatus('unauthorized')
      })
  }, [account, inProgress, instance])

  function logout() {
    instance.logoutRedirect({
      account,
      postLogoutRedirectUri: window.location.origin,
    }).catch(console.error)
  }

  return { status, user, logout, groupError }
}
