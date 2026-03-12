import { NextRequest } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

export async function POST(req: NextRequest) {
  const formData = await req.formData()

  const upstream = await fetch(`${BACKEND_URL}/enhance`, {
    method: 'POST',
    body: formData,
  })

  // Pass the backend stream straight through — no buffering
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'Content-Type':      'text/event-stream',
      'Cache-Control':     'no-cache',
      'X-Accel-Buffering': 'no',
    },
  })
}
