import { auth } from './auth'
import { NextResponse } from 'next/server'

export default auth((req) => {
  const { nextUrl } = req
  const session = req.auth

  // Not signed in → redirect directly to Microsoft login (skip the sign-in button page)
  if (!session) {
    const signInUrl = new URL('/api/auth/signin/microsoft-entra-id', nextUrl)
    signInUrl.searchParams.set('callbackUrl', nextUrl.pathname)
    return NextResponse.redirect(signInUrl)
  }

  // Signed in but not in the required group → access denied
  const allowedGroupId = process.env.AZURE_ALLOWED_GROUP_ID
  const inGroup = !allowedGroupId || (session.user?.groups ?? []).includes(allowedGroupId)

  if (!inGroup && nextUrl.pathname !== '/access-denied') {
    return NextResponse.redirect(new URL('/access-denied', nextUrl))
  }
})

export const config = {
  matcher: ['/((?!api/auth|_next/static|_next/image|favicon.ico).*)'],
}
