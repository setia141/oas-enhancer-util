import { useState } from 'react'
import { useAuth } from './auth/useAuth'
import AccessDenied from './components/AccessDenied'
import UploadForm from './components/UploadForm'
import ProgressTracker from './components/ProgressTracker'
import ResultViewer from './components/ResultViewer'

function LoadingScreen() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      gap: 16, color: '#666', minHeight: '100vh',
    }}>
      <div style={{ fontSize: 40 }}>📄</div>
      <div style={{ fontSize: 15 }}>Signing you in...</div>
    </div>
  )
}

export default function App() {
  const { status, user, logout } = useAuth()

  // UI state machine: idle | running | done | error
  const [phase, setPhase] = useState('idle')
  const [error, setError] = useState('')
  const [originalFilename, setOriginalFilename] = useState('')

  // SSE progress state
  const [currentIteration, setCurrentIteration] = useState(0)
  const [iterations, setIterations] = useState([])       // completed iteration data
  const [reviewData, setReviewData] = useState({})       // iteration → review object

  // Final result
  const [result, setResult] = useState(null)

  function resetAll() {
    setPhase('idle')
    setError('')
    setCurrentIteration(0)
    setIterations([])
    setReviewData({})
    setResult(null)
  }

  async function handleSubmit({ oasFile, postmanFile, instructions }) {
    resetAll()
    setPhase('running')
    setOriginalFilename(oasFile.name)

    const formData = new FormData()
    formData.append('oas_file', oasFile)
    if (postmanFile) formData.append('postman_file', postmanFile)
    if (instructions) formData.append('instructions', instructions)

    try {
      const resp = await fetch('/enhance', { method: 'POST', body: formData })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err.detail || `Server error ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // keep incomplete last line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event
          try { event = JSON.parse(line.slice(6)) } catch { continue }

          if (event.type === 'error') {
            throw new Error(event.message)
          }

          if (event.type === 'iteration_start') {
            setCurrentIteration(event.iteration)
          }

          if (event.type === 'review_complete') {
            setReviewData(prev => ({ ...prev, [event.iteration]: event.data }))
          }

          if (event.type === 'enhance_complete') {
            setIterations(prev => [
              ...prev,
              {
                iteration: event.iteration,
                review_summary: reviewData[event.iteration]?.summary ?? '',
                suggestions: reviewData[event.iteration]?.suggestions ?? [],
                changes_made: event.data.changes_made ?? [],
              },
            ])
          }

          if (event.type === 'done') {
            setResult(event)
            setIterations(event.iterations ?? [])
            setPhase('done')
          }
        }
      }
    } catch (e) {
      setError(e.message)
      setPhase('error')
    }
  }

  // ── Auth gate ─────────────────────────────────────────────────
  if (status === 'loading') return <LoadingScreen />
  if (status === 'unauthorized') return <AccessDenied groupError={null} />

  // ── App shell ─────────────────────────────────────────────────
  return (
    <div style={{ width: '100%', minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#f0f2f5' }}>

      {/* Nav */}
      <header style={{
        background: '#fff', borderBottom: '1px solid #e8eaed',
        padding: '0 24px', display: 'flex', alignItems: 'center', gap: 12, height: 56, flexShrink: 0,
      }}>
        <div style={{ fontSize: 20 }}>📄</div>
        <div style={{ fontWeight: 700, fontSize: 16, flex: 1 }}>OAS Enhancer</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: '50%',
            background: 'linear-gradient(135deg, #4285f4, #34a853)',
            color: '#fff', display: 'flex', alignItems: 'center',
            justifyContent: 'center', fontSize: 13, fontWeight: 700,
          }}>
            {user?.name?.[0]?.toUpperCase()}
          </div>
          <div style={{ lineHeight: 1.3 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#1a1a1a' }}>{user?.name}</div>
            <div style={{ fontSize: 11, color: '#888' }}>{user?.email}</div>
          </div>
        </div>
        <button onClick={logout} style={{
          padding: '6px 14px', fontSize: 12,
          background: 'transparent', border: '1px solid #e0e0e0',
          borderRadius: 6, cursor: 'pointer', color: '#666',
          fontFamily: 'inherit', marginLeft: 8,
        }}>
          Sign out
        </button>
      </header>

      {/* Main */}
      <main style={{
        flex: 1, display: 'flex', alignItems: 'center',
        justifyContent: 'center', padding: '32px 16px',
      }}>
        {phase === 'idle' && (
          <UploadForm onSubmit={handleSubmit} loading={false} />
        )}

        {phase === 'running' && (
          <ProgressTracker
            currentIteration={currentIteration}
            iterations={iterations}
            reviewData={reviewData}
            isComplete={false}
          />
        )}

        {phase === 'done' && result && (
          <ResultViewer
            result={result}
            originalFilename={originalFilename}
            userName={user?.name}
            onReset={resetAll}
          />
        )}

        {phase === 'error' && (
          <div style={{ width: '100%', maxWidth: 560 }}>
            <div style={{
              padding: '16px', background: '#fce8e6', color: '#c5221f',
              borderRadius: 8, fontSize: 13, marginBottom: 12,
            }}>
              ⚠ {error}
            </div>
            <button onClick={resetAll} style={{
              padding: '10px 20px', background: '#4285f4', color: '#fff',
              border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14,
              fontFamily: 'inherit',
            }}>
              Try Again
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
