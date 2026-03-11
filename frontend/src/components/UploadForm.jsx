import { useRef, useState } from 'react'

function FileDropZone({ label, accept, file, onFile, icon }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function handleDrop(e) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) onFile(f)
  }

  return (
    <div
      onClick={() => inputRef.current.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      style={{
        border: `2px dashed ${dragging ? '#4285f4' : file ? '#34a853' : '#d0d5dd'}`,
        borderRadius: 12,
        padding: '24px 16px',
        textAlign: 'center',
        cursor: 'pointer',
        background: dragging ? '#e8f0fe' : file ? '#e6f4ea' : '#fafafa',
        transition: 'all 0.2s',
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={(e) => e.target.files[0] && onFile(e.target.files[0])}
      />
      <div style={{ fontSize: 28, marginBottom: 8 }}>{file ? '✅' : icon}</div>
      <div style={{ fontWeight: 600, fontSize: 14, color: '#333', marginBottom: 4 }}>{label}</div>
      {file ? (
        <div style={{ fontSize: 13, color: '#34a853', fontWeight: 500 }}>
          {file.name} ({(file.size / 1024).toFixed(1)} KB)
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#888' }}>
          Drag & drop or click to browse
        </div>
      )}
    </div>
  )
}

export default function UploadForm({ onSubmit, loading }) {
  const [oasFile, setOasFile] = useState(null)
  const [postmanFile, setPostmanFile] = useState(null)
  const [instructions, setInstructions] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    if (!oasFile) return
    onSubmit({ oasFile, postmanFile, instructions })
  }

  return (
    <div style={{
      width: '100%', maxWidth: 560,
      background: '#fff', borderRadius: 16,
      boxShadow: '0 4px 24px rgba(0,0,0,0.12)',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        background: 'linear-gradient(135deg, #4285f4, #34a853)',
        padding: '28px 24px', color: '#fff',
      }}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>📄</div>
        <div style={{ fontSize: 20, fontWeight: 700 }}>OAS Enhancer</div>
        <div style={{ fontSize: 13, opacity: 0.9, marginTop: 4 }}>
          Upload your OpenAPI spec and Postman collection to auto-generate examples
        </div>
      </div>

      <form onSubmit={handleSubmit} style={{ padding: '24px' }}>
        {/* OAS File */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#444', marginBottom: 8 }}>
            OpenAPI Spec <span style={{ color: '#e53935' }}>*</span>
          </label>
          <FileDropZone
            label="OAS / Swagger file"
            accept=".json,.yaml,.yml"
            file={oasFile}
            onFile={setOasFile}
            icon="📋"
          />
          <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>Accepts JSON, YAML (.yaml/.yml)</div>
        </div>

        {/* Postman File */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#444', marginBottom: 8 }}>
            Postman Collection <span style={{ color: '#888', fontWeight: 400 }}>(optional)</span>
          </label>
          <FileDropZone
            label="Postman Collection v2.1"
            accept=".json"
            file={postmanFile}
            onFile={setPostmanFile}
            icon="📮"
          />
          {postmanFile && (
            <button
              type="button"
              onClick={() => setPostmanFile(null)}
              style={{
                marginTop: 6, fontSize: 11, color: '#888',
                background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              }}
            >
              ✕ Remove
            </button>
          )}
        </div>

        {/* Instructions */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#444', marginBottom: 8 }}>
            Additional Instructions <span style={{ color: '#888', fontWeight: 400 }}>(optional)</span>
          </label>
          <textarea
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="e.g. Focus on POST endpoints, add error response examples, use realistic data..."
            rows={3}
            style={{
              width: '100%', padding: '10px 14px',
              border: '1px solid #e0e0e0', borderRadius: 8,
              fontSize: 13, outline: 'none', fontFamily: 'inherit',
              resize: 'vertical', lineHeight: 1.5,
            }}
          />
        </div>

        <button
          type="submit"
          disabled={!oasFile || loading}
          style={{
            width: '100%', padding: '13px',
            background: !oasFile || loading ? '#ccc' : '#4285f4',
            color: '#fff', border: 'none', borderRadius: 8,
            fontSize: 15, fontWeight: 600,
            cursor: !oasFile || loading ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          }}
        >
          {loading ? (
            <>
              <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span>
              Enhancing with AI...
            </>
          ) : (
            '✨ Enhance OAS'
          )}
        </button>
      </form>
    </div>
  )
}
