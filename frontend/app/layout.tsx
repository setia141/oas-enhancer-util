import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'OAS Enhancer',
  description: 'AI-powered OpenAPI Specification enhancer',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
