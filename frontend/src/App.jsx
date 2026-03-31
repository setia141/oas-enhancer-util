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
  const { status, user } = useAuth()

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

  // ── Content only — nav/header/footer provided by the base HTML ─
  return (
    <div style={{ width: '100%', padding: '32px 16px' }}>

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

    </div>
  )
}
