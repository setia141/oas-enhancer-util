import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// Auth disabled for local testing.
// To re-enable: replace this with: export { default, config } from './utils/middleware'
export function middleware(req: NextRequest) {
  return NextResponse.next()
}
