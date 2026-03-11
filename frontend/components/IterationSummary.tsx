'use client'

import { useState } from 'react'
import type { Iteration, EnhancementSummary } from '../types'

interface BadgeProps {
  count: string
  color: string
}

function Badge({ count, color }: BadgeProps) {
  return (
    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: color + '22', color, fontWeight: 600, marginLeft: 8 }}>
      {count}
    </span>
  )
}

interface IterationCardProps {
  data: Iteration
  defaultOpen: boolean
}

function IterationCard({ data, defaultOpen }: IterationCardProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div style={{ border: '1px solid #e8eaed', borderRadius: 10, overflow: 'hidden', marginBottom: 12 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width: '100%', padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 8, background: '#f8f9fa', border: 'none', cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left' }}
      >
        <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#4285f4', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, flexShrink: 0 }}>
          {data.iteration}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#1a1a1a' }}>
            Iteration {data.iteration}
            <Badge count={`${data.suggestions?.length} suggestions`} color="#4285f4" />
            <Badge count={`${data.changes_made?.length} changes`} color="#34a853" />
          </div>
          <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>{data.review_summary}</div>
        </div>
        <span style={{ fontSize: 16, color: '#888' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ padding: '16px', display: 'flex', gap: 16 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#4285f4', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Reviewer Suggestions
            </div>
            {data.suggestions?.length > 0 ? (
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {data.suggestions.map((s, i) => (
                  <li key={i} style={{ fontSize: 13, color: '#444', marginBottom: 6, lineHeight: 1.5 }}>{s}</li>
                ))}
              </ul>
            ) : (
              <div style={{ fontSize: 13, color: '#888' }}>No suggestions</div>
            )}
          </div>

          <div style={{ width: 1, background: '#e8eaed' }} />

          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#34a853', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Changes Applied
            </div>
            {data.changes_made?.length > 0 ? (
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {data.changes_made.map((c, i) => (
                  <li key={i} style={{ fontSize: 13, color: '#2d6a3f', marginBottom: 6, lineHeight: 1.5 }}>{c}</li>
                ))}
              </ul>
            ) : (
              <div style={{ fontSize: 13, color: '#888' }}>No changes recorded</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

interface IterationSummaryProps {
  iterations: Iteration[]
  summary?: EnhancementSummary
}

export default function IterationSummary({ iterations, summary }: IterationSummaryProps) {
  if (!iterations?.length) {
    return <div style={{ padding: 24, color: '#888', textAlign: 'center' }}>No iteration data available.</div>
  }

  const stats = [
    { label: 'Iterations Run',  value: summary?.total_iterations ?? iterations.length, color: '#4285f4' },
    { label: 'Total Changes',   value: summary?.total_changes ?? 0,                    color: '#34a853' },
    { label: 'Completed By',    value: summary?.completed_by_reviewer ? 'Reviewer ✓' : 'Max Iterations', color: summary?.completed_by_reviewer ? '#34a853' : '#fbbc04' },
  ]

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
        {stats.map(({ label, value, color }) => (
          <div key={label} style={{ background: '#f8f9fa', border: '1px solid #e8eaed', borderRadius: 8, padding: '12px 14px', textAlign: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
            <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>
      {iterations.map((it, i) => (
        <IterationCard key={it.iteration} data={it} defaultOpen={i === iterations.length - 1} />
      ))}
    </div>
  )
}
