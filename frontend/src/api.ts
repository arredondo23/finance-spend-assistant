// Types mirror the Pydantic models in backend/app/models.py.

export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface Summary {
  invoice_count: number
  vendor_count: number
  date_from: string
  date_to: string
  total_spend_eur: number
  spend_by_currency: { currency: string; total: number; total_eur: number; count: number }[]
  spend_by_vendor_status: { status: string; currency: string; total: number; count: number }[]
  compliance_flags: { missing_po: number; missing_approver: number; non_active_vendor: number; credit_notes: number }
  fx: { converted_invoice_count: number; prior_rate_invoice_count: number; note: string }
  note: string
}

export type Row = Record<string, string | number | boolean | null>

export interface Group {
  keys: Record<string, string | null>
  currency: string | null
  value: number
  value_eur?: number
  converted_invoice_count?: number
  prior_rate_invoice_count?: number
  invoice_count: number
  credit_note_count: number
  invoice_numbers: string[]
}

export interface DataEvidence {
  tool: string
  args: Record<string, unknown>
  total_matched: number
  truncated: boolean
  rows: Row[] | null
  groups: Group[] | null
}

export interface AskResponse {
  status: 'answered' | 'declined'
  answer: string
  route: ('policy' | 'data')[]
  policy_evidence: { section: string; text: string }[]
  data_evidence: DataEvidence[]
  warnings: string[]
  llm: string
}

export class ApiError extends Error {}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 120_000): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, signal: AbortSignal.timeout(timeoutMs) })
  } catch (e) {
    const timedOut = e instanceof DOMException && e.name === 'TimeoutError'
    throw new ApiError(timedOut ? 'The request timed out.' : `Cannot reach the backend at ${API_URL}.`)
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    // Backend errors are {error, message}; FastAPI validation errors are {detail}.
    const msg = body?.message ?? (body?.detail ? JSON.stringify(body.detail) : res.statusText)
    throw new ApiError(`${res.status}: ${msg}`)
  }
  return res.json()
}

export const getSummary = () => request<Summary>('/summary', {}, 15_000)

export const ask = (question: string) =>
  request<AskResponse>('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })

export const fmtMoney = (n: number) => n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
