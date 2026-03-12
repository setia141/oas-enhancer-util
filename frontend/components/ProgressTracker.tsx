'use client'

import { useState } from 'react'
import type { Iteration, IterationStep, ReviewData } from '../types'

const MAX_ITERATIONS = 5
const SUGGESTIONS_PREVIEW = 3
const CHANGES_PREVIEW = 4

interface CollapsibleListProps {
  items: string[]
  preview: number
  color: string
  moreColor: string
}

function CollapsibleList({ items, preview, color, moreColor }: CollapsibleListProps) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? items : items.slice(0, preview)
  const hidden = items.length - preview

  return (
    <ul style={{ margin: 0, paddingLeft: 16 }}>
      {visible.map((s, i) => (
        <li key={i} style={{ fontSize: 12, color, marginBottom: 2 }}>{s}</li>
      ))}
      {hidden > 0 && (
        <li
          onClick={() => setExpanded(e => !e)}
          style={{ fontSize: 12, color: moreColor, cursor: 'pointer', userSelect: 'none', marginTop: 2 }}
        >
          {expanded ? '▲ show less' : `+${hidden} more — click to expand`}
        </li>
      )}
    </ul>
  )
}

interface IterationRowProps {
  num: number
  status: 'pending' | 'active' | 'done' | 'skipped'
  step?: IterationStep
  review?: ReviewData
  changes?: string[]
}

function IterationRow({ num, status, step, review, changes }: IterationRowProps) {
  const colors = { pending: '#ccc', active: '#4285f4', done: '#34a853', skipped: '#34a853' }
  const color = colors[status]

  return (
    <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          background: color, color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700,
          boxShadow: status === 'active' ? `0 0 0 4px ${color}33` : 'none',
          transition: 'all 0.3s',
        }}>
          {status === 'done' || status === 'skipped' ? '✓' : num}
        </div>
        {num < MAX_ITERATIONS && (
          <div style={{ width: 2, flex: 1, minHeight: 24, background: status === 'done' ? '#34a853' : '#e0e0e0', marginTop: 4 }} />
        )}
      </div>

      <div style={{ flex: 1, paddingBottom: 16 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: status === 'pending' ? '#999' : '#1a1a1a', marginBottom: 4 }}>
          Iteration {num}
          {status === 'active' && step === 'reviewing' && (
            <span style={{ marginLeft: 8, fontSize: 12, color: '#4285f4', fontWeight: 400 }}>● reviewing...</span>
          )}
          {status === 'active' && step === 'enhancing' && (
            <span style={{ marginLeft: 8, fontSize: 12, color: '#f4a234', fontWeight: 400 }}>● enhancing spec...</span>
          )}
          {status === 'skipped' && (
            <span style={{ marginLeft: 8, fontSize: 12, color: '#34a853', fontWeight: 400 }}>✓ reviewer satisfied — done early</span>
          )}
        </div>

        {review && (
          <div style={{ background: '#f8f9fa', borderRadius: 8, padding: '10px 14px', border: '1px solid #e8eaed', marginBottom: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#888', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Reviewer
            </div>
            <div style={{ fontSize: 13, color: '#333', marginBottom: review.suggestions?.length ? 8 : 0 }}>
              {review.summary}
            </div>
            {review.suggestions?.length > 0 && (
              <CollapsibleList items={review.suggestions} preview={SUGGESTIONS_PREVIEW} color="#555" moreColor="#4285f4" />
            )}
          </div>
        )}

        {changes && changes.length > 0 && (
          <div style={{ background: '#e6f4ea', borderRadius: 8, padding: '10px 14px', border: '1px solid #c3e6cb' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#34a853', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Changes Applied
            </div>
            <CollapsibleList items={changes} preview={CHANGES_PREVIEW} color="#2d6a3f" moreColor="#34a853" />
          </div>
        )}
      </div>
    </div>
  )
}

interface ProgressTrackerProps {
  currentIteration: number
  currentStep: IterationStep
  iterations: Iteration[]
  reviewData: Record<number, ReviewData>
}

export default function ProgressTracker({ currentIteration, currentStep, iterations, reviewData }: ProgressTrackerProps) {
  const rows = Array.from({ length: MAX_ITERATIONS }, (_, i) => {
    const num = i + 1
    const iterData = iterations.find(it => it.iteration === num)
    const reviewForNum = reviewData[num]
    const isDone = iterData !== undefined
    const isActive = !isDone && num === currentIteration
    const isSkipped = reviewForNum?.satisfied && num === currentIteration

    return {
      num,
      status: (isSkipped ? 'skipped' : isDone ? 'done' : isActive ? 'active' : 'pending') as IterationRowProps['status'],
      step: isActive ? currentStep : undefined,
      review: reviewForNum,
      changes: iterData?.changes_made,
    }
  })

  return (
    <div style={{ width: '100%', maxWidth: 600, background: '#fff', borderRadius: 16, boxShadow: '0 4px 24px rgba(0,0,0,0.12)', overflow: 'hidden' }}>
      <div style={{ background: 'linear-gradient(135deg, #4285f4, #34a853)', padding: '20px 24px', color: '#fff' }}>
        <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 4 }}>✨ Enhancing your OAS spec</div>
        <div style={{ fontSize: 13, opacity: 0.9 }}>AI review → enhance loop · up to {MAX_ITERATIONS} iterations</div>
      </div>
      <div style={{ padding: '24px' }}>
        {rows.map(row => <IterationRow key={row.num} {...row} step={row.step} />)}
      </div>
    </div>
  )
}
