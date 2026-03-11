import NextAuth from 'next-auth'
import type { OAuthConfig } from 'next-auth/providers'

const tenantId = process.env.AZURE_TENANT_ID!
const base = `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0`

interface AzureProfile {
  sub: string
  name: string
  email?: string
  preferred_username?: string
  groups?: string[]
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  trustHost: true,
  providers: [
    {
      id: 'microsoft-entra-id',
      name: 'Microsoft',
      type: 'oauth',
      clientId:     process.env.AZURE_CLIENT_ID,
      clientSecret: process.env.AZURE_CLIENT_SECRET,
      authorization: {
        url: `${base}/authorize`,
        params: { scope: 'openid profile email User.Read offline_access' },
      },
      token: `${base}/token`,
      userinfo: 'https://graph.microsoft.com/oidc/userinfo',
      checks: ['state'],
      // Azure AD requires client_id in the request body (client_secret_post)
      client: { token_endpoint_auth_method: 'client_secret_post' },
      profile(profile: AzureProfile) {
        return {
          id:    profile.sub,
          name:  profile.name,
          email: profile.email ?? profile.preferred_username ?? '',
          image: null,
        }
      },
    } as OAuthConfig<AzureProfile>,
  ],

  callbacks: {
    async jwt({ token, account }) {
      if (account?.id_token) {
        try {
          const claims = JSON.parse(
            Buffer.from(account.id_token.split('.')[1], 'base64').toString()
          )
          token.groups = (claims.groups as string[]) ?? []
        } catch {
          token.groups = []
        }
      }
      return token
    },

    async session({ session, token }) {
      session.user.groups = (token.groups as string[]) ?? []
      return session
    },
  },
})
