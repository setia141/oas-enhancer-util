import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  output: 'standalone', // required for Docker single-image build

  async rewrites() {
    // Proxy API calls to the FastAPI backend.
    // In dev: backend runs on localhost:8000
    // In Docker: backend runs on 127.0.0.1:8000 (same container)
    const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'
    return [
      { source: '/enhance', destination: `${backend}/enhance` },
      { source: '/convert', destination: `${backend}/convert` },
      { source: '/health',  destination: `${backend}/health`  },
    ]
  },
}

export default nextConfig
