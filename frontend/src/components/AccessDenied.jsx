import { useAuth } from '../auth/useAuth'

export default function AccessDenied({ user, groupError }) {
  const { logout } = useAuth()

  return (
    <div style={{
      width: '100%', maxWidth: 420,
      background: '#fff', borderRadius: 16,
      boxShadow: '0 4px 24px rgba(0,0,0,0.12)',
      overflow: 'hidden', textAlign: 'center',
    }}>
      <div style={{
        background: '#fce8e6', padding: '32px 24px',
        borderBottom: '1px solid #f5c6c3',
      }}>
        <div style={{ fontSize: 48, marginBottom: 8 }}>🚫</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: '#c5221f' }}>Access Denied</div>
      </div>

      <div style={{ padding: '28px 28px' }}>
        {user && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            background: '#f8f9fa', borderRadius: 8, padding: '10px 14px',
            marginBottom: 20, textAlign: 'left',
          }}>
            <div style={{
              width: 36, height: 36, borderRadius: '50%',
              background: '#e8f0fe', color: '#4285f4',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16, fontWeight: 700, flexShrink: 0,
            }}>
              {user.name?.[0]?.toUpperCase()}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#1a1a1a' }}>{user.name}</div>
              <div style={{ fontSize: 12, color: '#888' }}>{user.email}</div>
            </div>
          </div>
        )}

        {groupError ? (
          <>
            <p style={{ fontSize: 14, color: '#555', lineHeight: 1.6, marginBottom: 12 }}>
              Group membership could not be verified.
            </p>
            <p style={{ fontSize: 12, color: '#c5221f', background: '#fce8e6', padding: '10px 14px', borderRadius: 6, marginBottom: 16, textAlign: 'left', lineHeight: 1.6 }}>
              {groupError}
            </p>
          </>
        ) : (
          <>
            <p style={{ fontSize: 14, color: '#555', lineHeight: 1.6, marginBottom: 8 }}>
              Your account is not in the authorized Azure AD group for this application.
            </p>
            <p style={{ fontSize: 13, color: '#888', marginBottom: 24 }}>
              Contact your administrator to request access.
            </p>
          </>
        )}

        <button
          onClick={logout}
          style={{
            width: '100%', padding: '11px',
            background: '#fff', border: '1px solid #d0d5dd',
            borderRadius: 8, fontSize: 14, fontWeight: 600,
            cursor: 'pointer', color: '#444', fontFamily: 'inherit',
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
