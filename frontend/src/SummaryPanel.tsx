import { useCallback, useEffect, useState } from 'react'
import { type Summary, fmtMoney, getSummary } from './api'

type State = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; data: Summary }

export function SummaryPanel() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  const fetchSummary = useCallback(() => {
    getSummary()
      .then((data) => setState({ kind: 'ready', data }))
      .catch((e: Error) => setState({ kind: 'error', message: e.message }))
  }, [])

  useEffect(fetchSummary, [fetchSummary])

  const load = () => {
    setState({ kind: 'loading' })
    fetchSummary()
  }

  return (
    <section className="panel summary">
      <h2>Invoice data overview</h2>
      {state.kind === 'loading' && <p className="muted">Loading summary…</p>}
      {state.kind === 'error' && (
        <div className="error">
          <p>Could not load the summary. {state.message}</p>
          <button onClick={load}>Retry</button>
        </div>
      )}
      {state.kind === 'ready' && <SummaryBody s={state.data} />}
    </section>
  )
}

function SummaryBody({ s }: { s: Summary }) {
  const f = s.compliance_flags
  return (
    <>
      <p>
        <strong>{s.invoice_count}</strong> invoices from <strong>{s.vendor_count}</strong> vendors, {s.date_from} to {s.date_to}.
      </p>

      <h3>Spend by currency</h3>
      <table>
        <thead><tr><th>Currency</th><th className="num">Total</th><th className="num">Invoices</th></tr></thead>
        <tbody>
          {s.spend_by_currency.map((c) => (
            <tr key={c.currency}><td>{c.currency}</td><td className="num">{fmtMoney(c.total)}</td><td className="num">{c.count}</td></tr>
          ))}
        </tbody>
      </table>

      <h3>Spend by vendor status</h3>
      <table>
        <thead><tr><th>Status</th><th>Currency</th><th className="num">Total</th><th className="num">Invoices</th></tr></thead>
        <tbody>
          {s.spend_by_vendor_status.map((r) => (
            <tr key={r.status + r.currency} className={r.status !== 'ACTIVE' ? 'flag' : ''}>
              <td>{r.status}</td><td>{r.currency}</td><td className="num">{fmtMoney(r.total)}</td><td className="num">{r.count}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Compliance flags</h3>
      <ul className="flags">
        <li><strong>{f.missing_po}</strong> missing PO (§2)</li>
        <li><strong>{f.missing_approver}</strong> missing approver (§3.1)</li>
        <li><strong>{f.non_active_vendor}</strong> from non-ACTIVE vendors (§4.1)</li>
        <li><strong>{f.credit_notes}</strong> credit notes (§6.1)</li>
      </ul>
      <p className="muted small">{s.note}</p>
    </>
  )
}
