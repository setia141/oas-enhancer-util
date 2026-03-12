export interface Iteration {
  iteration: number
  review_summary: string
  suggestions: string[]
  changes_made: string[]
}

export interface EnhancementSummary {
  total_iterations: number
  total_changes: number
  completed_by_reviewer: boolean
}

export interface EnhancementResult {
  original_spec: Record<string, unknown>
  original_spec_yaml: string
  final_spec: Record<string, unknown>
  final_spec_yaml: string
  iterations: Iteration[]
  summary: EnhancementSummary
}

export interface OASOperation {
  summary?: string
  description?: string
  tags?: string[]
  requestBody?: {
    content?: Record<string, { examples?: Record<string, unknown> }>
  }
  responses?: Record<string, {
    content?: Record<string, { examples?: Record<string, unknown> }>
  }>
}

export interface OASSpec {
  paths?: Record<string, Record<string, OASOperation>>
  [key: string]: unknown
}

export type Phase = 'idle' | 'running' | 'done' | 'error'

export interface ReviewData {
  satisfied: boolean
  summary: string
  suggestions: string[]
}

export type SSEEvent =
  | { type: 'iteration_start'; iteration: number }
  | { type: 'review_complete'; iteration: number; data: ReviewData }
  | { type: 'enhance_start'; iteration: number }
  | { type: 'enhance_complete'; iteration: number; data: { changes_made: string[] } }
  | ({ type: 'done' } & EnhancementResult)
  | { type: 'error'; message: string }

export type IterationStep = 'reviewing' | 'enhancing'
