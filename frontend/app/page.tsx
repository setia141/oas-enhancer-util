'use client'

import { useState } from 'react'
import { useSession, signOut } from 'next-auth/react'
import UploadForm from '../components/UploadForm'
import ProgressTracker from '../components/ProgressTracker'
import ResultViewer from '../components/ResultViewer'
import type { Phase, Iteration, ReviewData, EnhancementResult, SSEEvent } from '../types'

function LoadingScreen() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, color: '#666', minHeight: '100vh' }}>
      <div style={{ fontSize: 40 }}>📄</div>
      <div style={{ fontSize: 15 }}>Signing you in...</div>
    </div>
  )
}

export default function Home() {
  const { data: session, status } = useSession()

  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [originalFilename, setOriginalFilename] = useState('')
  const [currentIteration, setCurrentIteration] = useState(0)
  const [iterations, setIterations] = useState<Iteration[]>([])
  const [reviewData, setReviewData] = useState<Record<number, ReviewData>>({})
  const [result, setResult] = useState<EnhancementResult | null>(null)

  if (status === 'loading') return <LoadingScreen />

  function resetAll() {
    setPhase('idle')
    setError('')
    setCurrentIteration(0)
    setIterations([])
    setReviewData({})
    setResult(null)
  }

  async function handleSubmit({ oasFile, postmanFile, instructions }: {
    oasFile: File
    postmanFile: File | null
    instructions: string
  }) {
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
        throw new Error((err as { detail?: string }).detail ?? `Server error ${resp.status}`)
      }

      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event: SSEEvent
          try { event = JSON.parse(line.slice(6)) } catch { continue }

          if (event.type === 'error') throw new Error(event.message)

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
                iteration:      event.iteration,
                review_summary: reviewData[event.iteration]?.summary ?? '',
                suggestions:    reviewData[event.iteration]?.suggestions ?? [],
                changes_made:   event.data.changes_made,
              },
            ])
          }

          if (event.type === 'done') {
            const { type: _, ...resultData } = event
            setResult(resultData as EnhancementResult)
            setIterations(event.iterations)
            setPhase('done')
          }
        }
      }
    } catch (e) {
      setError((e as Error).message)
      setPhase('error')
    }
  }

  const user = session?.user

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
        <button
          onClick={() => signOut({ callbackUrl: '/' })}
          style={{
            padding: '6px 14px', fontSize: 12,
            background: 'transparent', border: '1px solid #e0e0e0',
            borderRadius: 6, cursor: 'pointer', color: '#666',
            fontFamily: 'inherit', marginLeft: 8,
          }}
        >
          Sign out
        </button>
      </header>

      {/* Main */}
      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '32px 16px' }}>
        {phase === 'idle' && (
          <UploadForm onSubmit={handleSubmit} />
        )}

        {phase === 'running' && (
          <ProgressTracker
            currentIteration={currentIteration}
            iterations={iterations}
            reviewData={reviewData}
          />
        )}

        {phase === 'done' && result && (
          <ResultViewer
            result={result}
            originalFilename={originalFilename}
            userName={user?.name ?? ''}
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
            <button
              onClick={resetAll}
              style={{
                padding: '10px 20px', background: '#4285f4', color: '#fff',
                border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14,
                fontFamily: 'inherit',
              }}
            >
              Try Again
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
