import { useState } from 'react'
import DiffViewer from './DiffViewer'
import IterationSummary from './IterationSummary'

function countExamples(oas) {
  let count = 0
  for (const pathItem of Object.values(oas?.paths ?? {})) {
    for (const [method, op] of Object.entries(pathItem)) {
      if (!['get','post','put','patch','delete','options','head'].includes(method)) continue
      const req = Object.values(op?.requestBody?.content ?? {})
        .reduce((n, m) => n + Object.keys(m?.examples ?? {}).length, 0)
      const res = Object.values(op?.responses ?? {})
        .flatMap(r => Object.values(r?.content ?? {}))
        .reduce((n, m) => n + Object.keys(m?.examples ?? {}).length, 0)
      count += req + res
    }
  }
  return count
}

const TABS = [
  { id: 'yaml',     label: 'Enhanced YAML' },
  { id: 'diff',     label: 'Diff View' },
  { id: 'summary',  label: 'Change History' },
  { id: 'endpoints',label: 'Endpoint Summary' },
]

export default function ResultViewer({ result, originalFilename, userName, onReset }) {
  const [tab, setTab] = useState('diff')
  const [copied, setCopied] = useState(false)
  const [exporting, setExporting] = useState(false)

  const { final_spec, final_spec_yaml, original_spec_yaml, iterations, summary } = result
  const yamlStr = final_spec_yaml ?? ''
  const exampleCount = countExamples(final_spec)
  const pathCount = Object.keys(final_spec?.paths ?? {}).length

  function handleCopy() {
    navigator.clipboard.writeText(yamlStr)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleDownload() {
    const blob = new Blob([yamlStr], { type: 'text/yaml' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = originalFilename?.replace(/\.(json|yaml|yml)$/, '_enhanced.yaml') ?? 'enhanced_oas.yaml'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  async function handleExportPostman() {
    setExporting(true)
    try {
      const file = new File([yamlStr], 'enhanced.yaml', { type: 'text/yaml' })
      const form = new FormData()
      form.append('oas_file', file)
      const resp = await fetch('/convert', { method: 'POST', body: form })
      if (!resp.ok) throw new Error(`Conversion failed: ${resp.status}`)
      const data = await resp.json()
      const out = JSON.stringify(data.collection, null, 2)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob([out], { type: 'application/json' }))
      a.download = originalFilename?.replace(/\.(json|yaml|yml)$/, '_postman.json') ?? 'collection.postman.json'
      a.click()
    } catch (e) {
      alert(`Export failed: ${e.message}`)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div style={{
      width: '100%', maxWidth: 1100,
      background: '#fff', borderRadius: 16,
      boxShadow: '0 4px 24px rgba(0,0,0,0.12)',
      overflow: 'hidden', display: 'flex', flexDirection: 'column',
      height: '88vh',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 20px',
        background: 'linear-gradient(135deg, #34a853, #4285f4)',
        color: '#fff', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 16 }}>✅ Enhancement Complete</div>
          <div style={{ fontSize: 12, opacity: 0.9, marginTop: 2 }}>
            {pathCount} endpoints · {exampleCount} examples · {summary?.total_iterations ?? 0} iteration{summary?.total_iterations !== 1 ? 's' : ''} · {summary?.total_changes ?? 0} total changes
            {userName && ` · by ${userName}`}
          </div>
        </div>
        <button onClick={onReset} style={{
          padding: '7px 14px', fontSize: 13,
          background: 'rgba(255,255,255,0.2)', border: '1px solid rgba(255,255,255,0.4)',
          borderRadius: 8, color: '#fff', cursor: 'pointer', fontFamily: 'inherit',
        }}>
          ← New File
        </button>
      </div>

      {/* Tabs + actions */}
      <div style={{
        display: 'flex', alignItems: 'center',
        borderBottom: '1px solid #e8eaed', padding: '0 16px', flexShrink: 0,
      }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '10px 14px', fontSize: 13,
            fontWeight: tab === t.id ? 600 : 400,
            color: tab === t.id ? '#4285f4' : '#666',
            borderBottom: tab === t.id ? '2px solid #4285f4' : '2px solid transparent',
            background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
          }}>
            {t.label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleCopy} style={btnStyle}>{copied ? '✅ Copied' : '📋 Copy'}</button>
          <button onClick={handleDownload} style={{ ...btnStyle, background: '#4285f4', color: '#fff', borderColor: '#4285f4' }}>⬇ Download YAML</button>
          <button onClick={handleExportPostman} disabled={exporting} style={{ ...btnStyle, color: '#ff6c37', borderColor: '#ff6c37' }}>
            {exporting ? '⟳' : '📮'} Postman
          </button>
        </div>
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {tab === 'yaml' && (
          <pre style={{
            margin: 0, padding: '16px 20px', fontSize: 12, lineHeight: 1.6,
            background: '#1e1e2e', color: '#cdd6f4',
            flex: 1, overflow: 'auto',
          }}>
            {yamlStr}
          </pre>
        )}

        {tab === 'diff' && (
          <DiffViewer originalStr={original_spec_yaml} finalStr={final_spec_yaml} />
        )}

        {tab === 'summary' && (
          <IterationSummary iterations={iterations} summary={summary} />
        )}

        {tab === 'endpoints' && (
          <EndpointSummary oas={final_spec} />
        )}
      </div>
    </div>
  )
}

const btnStyle = {
  padding: '6px 12px', fontSize: 12,
  background: '#fff', border: '1px solid #e0e0e0',
  borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit', color: '#444',
}

function EndpointSummary({ oas }) {
  const methods = ['get','post','put','patch','delete']
  const colors = { get: '#34a853', post: '#4285f4', put: '#fbbc04', patch: '#ff6d00', delete: '#e53935' }

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto' }}>
      {Object.entries(oas?.paths ?? {}).map(([path, pathItem]) => (
        <div key={path} style={{ marginBottom: 10 }}>
          {methods.map(method => {
            const op = pathItem[method]
            if (!op) return null
            const req = Object.values(op?.requestBody?.content ?? {}).reduce((n, m) => n + Object.keys(m?.examples ?? {}).length, 0)
            const res = Object.values(op?.responses ?? {}).flatMap(r => Object.values(r?.content ?? {})).reduce((n, m) => n + Object.keys(m?.examples ?? {}).length, 0)
            const total = req + res
            return (
              <div key={method} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '9px 14px', borderRadius: 8, marginBottom: 6,
                background: '#f8f9fa', border: '1px solid #e8eaed',
              }}>
                <span style={{
                  padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                  color: '#fff', background: colors[method] ?? '#888',
                  textTransform: 'uppercase', minWidth: 52, textAlign: 'center',
                }}>
                  {method}
                </span>
                <span style={{ fontSize: 13, fontFamily: 'monospace', flex: 1 }}>{path}</span>
                <span style={{ fontSize: 12, color: '#888' }}>{op.summary ?? ''}</span>
                <span style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 600,
                  background: total > 0 ? '#e6f4ea' : '#fce8e6',
                  color: total > 0 ? '#34a853' : '#c5221f',
                }}>
                  {total > 0 ? `+${total} examples` : 'no examples'}
                </span>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
