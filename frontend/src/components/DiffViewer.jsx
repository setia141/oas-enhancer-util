import { useMemo, useState } from 'react'

/**
 * Simple line-based diff.
 * Returns per-line type: 'unchanged' | 'added' | 'removed'
 */
function computeDiff(origStr, enhStr) {
  const origLines = origStr.split('\n')
  const enhLines = enhStr.split('\n')

  // Build frequency map of trimmed lines in each side
  const origCount = new Map()
  const enhCount = new Map()
  origLines.forEach(l => origCount.set(l, (origCount.get(l) ?? 0) + 1))
  enhLines.forEach(l => enhCount.set(l, (enhCount.get(l) ?? 0) + 1))

  const origResult = origLines.map(line => ({
    content: line,
    type: (enhCount.get(line) ?? 0) > 0 ? 'unchanged' : 'removed',
  }))

  const enhResult = enhLines.map(line => ({
    content: line,
    type: (origCount.get(line) ?? 0) > 0 ? 'unchanged' : 'added',
  }))

  const addedCount = enhResult.filter(l => l.type === 'added').length
  const removedCount = origResult.filter(l => l.type === 'removed').length

  return { origResult, enhResult, addedCount, removedCount }
}

const LINE_COLORS = {
  added:     { bg: '#e6f4ea', border: '#34a853', num: '#a8d5b5' },
  removed:   { bg: '#fce8e6', border: '#ea4335', num: '#f5bfba' },
  unchanged: { bg: 'transparent', border: 'transparent', num: '#ccc' },
}

function DiffPanel({ lines, title, badge, badgeColor }) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
      <div style={{
        padding: '10px 14px', background: '#f8f9fa',
        borderBottom: '1px solid #e8eaed', display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{title}</span>
        {badge != null && (
          <span style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 10,
            background: badgeColor + '22', color: badgeColor, fontWeight: 600,
          }}>
            {badge}
          </span>
        )}
      </div>
      <div style={{ overflowY: 'auto', fontFamily: 'monospace', fontSize: 12, lineHeight: '20px' }}>
        {lines.map((line, i) => {
          const style = LINE_COLORS[line.type]
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                background: style.bg,
                borderLeft: `3px solid ${style.border}`,
              }}
            >
              <span style={{
                minWidth: 40, textAlign: 'right', paddingRight: 8,
                color: style.num, userSelect: 'none', flexShrink: 0,
                paddingTop: 1, paddingBottom: 1,
              }}>
                {i + 1}
              </span>
              <span style={{
                whiteSpace: 'pre', overflow: 'hidden', textOverflow: 'ellipsis',
                paddingRight: 8, paddingTop: 1, paddingBottom: 1,
                color: line.type === 'added' ? '#1e6e35' : line.type === 'removed' ? '#c5221f' : '#333',
              }}>
                {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}
                {line.content}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function DiffViewer({ originalStr, finalStr }) {
  const [showOnlyChanges, setShowOnlyChanges] = useState(false)

  const { origResult, enhResult, addedCount, removedCount } = useMemo(
    () => computeDiff(originalStr ?? '', finalStr ?? ''),
    [originalStr, finalStr]
  )

  const filteredOrig = showOnlyChanges ? origResult.filter(l => l.type !== 'unchanged') : origResult
  const filteredEnh = showOnlyChanges ? enhResult.filter(l => l.type !== 'unchanged') : enhResult

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px',
        borderBottom: '1px solid #e8eaed', background: '#fafafa',
      }}>
        <span style={{
          fontSize: 12, padding: '2px 10px', borderRadius: 10,
          background: '#e6f4ea', color: '#34a853', fontWeight: 600,
        }}>
          +{addedCount} added
        </span>
        <span style={{
          fontSize: 12, padding: '2px 10px', borderRadius: 10,
          background: '#fce8e6', color: '#ea4335', fontWeight: 600,
        }}>
          -{removedCount} removed
        </span>
        <div style={{ flex: 1 }} />
        <label style={{ fontSize: 12, color: '#555', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={showOnlyChanges}
            onChange={e => setShowOnlyChanges(e.target.checked)}
          />
          Show changes only
        </label>
      </div>

      {/* Side-by-side panels */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', gap: 0 }}>
        <DiffPanel
          lines={filteredOrig}
          title="Original"
          badge={removedCount ? `-${removedCount}` : null}
          badgeColor="#ea4335"
        />
        <div style={{ width: 1, background: '#e8eaed', flexShrink: 0 }} />
        <DiffPanel
          lines={filteredEnh}
          title="Enhanced"
          badge={addedCount ? `+${addedCount}` : null}
          badgeColor="#34a853"
        />
      </div>
    </div>
  )
}
