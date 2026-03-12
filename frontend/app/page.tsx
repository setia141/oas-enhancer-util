'use client'

import { useState } from 'react'
import UploadForm from '../components/UploadForm'
import ProgressTracker from '../components/ProgressTracker'
import ResultViewer from '../components/ResultViewer'
import type { Phase, Iteration, IterationStep, ReviewData, EnhancementResult, SSEEvent } from '../types'

export default function Home() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [originalFilename, setOriginalFilename] = useState('')
  const [currentIteration, setCurrentIteration] = useState(0)
  const [currentStep, setCurrentStep] = useState<IterationStep>('reviewing')
  const [iterations, setIterations] = useState<Iteration[]>([])
  const [reviewData, setReviewData] = useState<Record<number, ReviewData>>({})
  const [result, setResult] = useState<EnhancementResult | null>(null)

  function resetAll() {
    setPhase('idle')
    setError('')
    setCurrentIteration(0)
    setCurrentStep('reviewing')
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
      const resp = await fetch('/api/enhance', { method: 'POST', body: formData })
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
          if (event.type === 'iteration_start') { setCurrentIteration(event.iteration); setCurrentStep('reviewing') }
          if (event.type === 'review_complete') {
            setReviewData(prev => ({ ...prev, [event.iteration]: event.data }))
          }
          if (event.type === 'enhance_start') setCurrentStep('enhancing')
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

  return (
    <div style={{ width: '100%', minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#f0f2f5' }}>

      <header style={{
        background: '#fff', borderBottom: '1px solid #e8eaed',
        padding: '0 24px', display: 'flex', alignItems: 'center', height: 56, flexShrink: 0,
      }}>
        <div style={{ fontSize: 20, marginRight: 10 }}>📄</div>
        <div style={{ fontWeight: 700, fontSize: 16 }}>OAS Enhancer</div>
      </header>

      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '32px 16px' }}>
        {phase === 'idle' && <UploadForm onSubmit={handleSubmit} />}

        {phase === 'running' && (
          <ProgressTracker
            currentIteration={currentIteration}
            currentStep={currentStep}
            iterations={iterations}
            reviewData={reviewData}
          />
        )}

        {phase === 'done' && result && (
          <ResultViewer
            result={result}
            originalFilename={originalFilename}
            userName=""
            onReset={resetAll}
          />
        )}

        {phase === 'error' && (
          <div style={{ width: '100%', maxWidth: 560 }}>
            <div style={{ padding: 16, background: '#fce8e6', color: '#c5221f', borderRadius: 8, fontSize: 13, marginBottom: 12 }}>
              ⚠ {error}
            </div>
            <button onClick={resetAll} style={{ padding: '10px 20px', background: '#4285f4', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14, fontFamily: 'inherit' }}>
              Try Again
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
