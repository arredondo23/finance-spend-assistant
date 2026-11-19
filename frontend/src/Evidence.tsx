import { type AskResponse, type DataEvidence, type Group, type Row, fmtMoney } from './api'

const ROW_COLUMNS = [
  'invoice_number', 'invoice_date', 'vendor_name', 'vendor_status', 'vendor_country',
  'amount', 'currency', 'amount_eur', 'fx_rate', 'fx_rate_date', 'po_number', 'approved_by', 'description',
]
const NUM_COLUMNS = ['amount', 'amount_eur', 'fx_rate']
const MONEY_COLUMNS = ['amount', 'amount_eur']
const VENDOR_COLUMNS = ['vendor_id', 'vendor_name', 'country', 'category', 'status']

function routeLabel(route: AskResponse['route']) {
  if (route.includes('policy') && route.includes('data')) return 'Policy + invoice data'
  if (route.includes('policy')) return 'Policy only'
  if (route.includes('data')) return 'Invoice data only'
  return 'No source used'
}

export function Evidence({ r }: { r: AskResponse }) {
  return (
    <div className="evidence">
      <div className="badges">
        <span className="badge">Based on: {routeLabel(r.route)}</span>
        <span className="badge">Answered by: {r.llm}</span>
      </div>

      {r.warnings.length > 0 && (
        <ul className="warnings">
          {r.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}

      <h4>Policy cited ({r.policy_evidence.length})</h4>
      {r.policy_evidence.length === 0 ? (
        <p className="muted small">No policy sections were used.</p>
      ) : (
        r.policy_evidence.map((p) => (
          <blockquote key={p.section}>
            <div className="cite">FIN-POL-014 §{p.section}</div>
            <pre>{p.text}</pre>
          </blockquote>
        ))
      )}

      <h4>Data queried ({r.data_evidence.length} {r.data_evidence.length === 1 ? 'query' : 'queries'})</h4>
      {r.data_evidence.length === 0 ? (
        <p className="muted small">No data was queried.</p>
      ) : (
        r.data_evidence.map((d, i) => <DataBlock key={i} d={d} />)
      )}
    </div>
  )
}

function DataBlock({ d }: { d: DataEvidence }) {
  const shown = d.rows?.length ?? d.groups?.length ?? 0
  return (
    <div className="data-block">
      <div className="query">
        <code>{d.tool}</code>
        <code className="args">{JSON.stringify(d.args)}</code>
      </div>
      <p className="small">
        {d.total_matched} {d.tool === 'get_vendors' ? 'vendors' : 'invoices'} matched.
        {d.truncated && <strong className="trunc"> Showing {shown} of {d.total_matched}: the list is truncated.</strong>}
      </p>
      {d.groups && <GroupTable groups={d.groups} />}
      {d.rows && d.rows.length > 0 && (
        <RowTable rows={d.rows} columns={d.tool === 'get_vendors' ? VENDOR_COLUMNS : ROW_COLUMNS} />
      )}
    </div>
  )
}

function GroupTable({ groups }: { groups: Group[] }) {
  if (groups.length === 0) return <p className="muted small">No matching invoices.</p>
  const keyCols = Object.keys(groups[0].keys)
  const isMoney = groups[0].currency !== null
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            {keyCols.map((k) => <th key={k}>{k}</th>)}
            {isMoney && <th>Currency</th>}
            <th className="num">Value</th>
            {isMoney && <th className="num">EUR equivalent</th>}
            {isMoney && <th className="num">Converted</th>}
            <th className="num">Invoices</th>
            <th className="num">Credit notes</th>
            <th>Invoice numbers (lineage)</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g, i) => (
            <tr key={i}>
              {keyCols.map((k) => <td key={k}>{g.keys[k] ?? <em>none</em>}</td>)}
              {isMoney && <td>{g.currency}</td>}
              <td className="num">{isMoney ? fmtMoney(g.value) : g.value}</td>
              {isMoney && <td className="num">{fmtMoney(g.value_eur ?? g.value)}</td>}
              {isMoney && (
                <td className="num" title="Invoices converted from GBP/USD; in brackets, those using the last ECB rate before the invoice date">
                  {g.converted_invoice_count ?? 0}{g.prior_rate_invoice_count ? ` (${g.prior_rate_invoice_count} prior-day rate)` : ''}
                </td>
              )}
              <td className="num">{g.invoice_count}</td>
              <td className="num">{g.credit_note_count}</td>
              <td>
                <details>
                  <summary>{g.invoice_numbers.length} invoices</summary>
                  <span className="small">{g.invoice_numbers.join(', ')}</span>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Cell({ row, c }: { row: Row; c: string }) {
  const v = row[c]
  if (c === 'fx_rate_date') {
    if (v === null) return <td className="muted">n/a</td>
    const prior = v !== row.invoice_date
    return (
      <td className={prior ? 'prior-rate' : ''} title={prior ? 'No ECB rate on the invoice date; last published rate used' : undefined}>
        {String(v)}{prior && ' *'}
      </td>
    )
  }
  if (v === null) return <td><em className="missing">missing</em></td>
  return (
    <td className={NUM_COLUMNS.includes(c) ? 'num' : ''}>
      {MONEY_COLUMNS.includes(c) ? fmtMoney(v as number) : String(v)}
    </td>
  )
}

function RowTable({ rows, columns }: { rows: Row[]; columns: string[] }) {
  return (
    <div className="scroll">
      <table>
        <thead><tr>{columns.map((c) => <th key={c} className={NUM_COLUMNS.includes(c) ? 'num' : ''}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={row.is_credit_note ? 'credit' : ''}>
              {columns.map((c) => <Cell key={c} row={row} c={c} />)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
