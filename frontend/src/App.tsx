import { ChatPanel } from './ChatPanel'
import { SummaryPanel } from './SummaryPanel'

export default function App() {
  return (
    <main className="layout">
      <header>
        <h1>Finance spend intelligence assistant</h1>
        <p className="muted small">
          Answers are grounded in FIN-POL-014 and the 2025 invoice data. Every answer shows the policy text and the rows it used.
        </p>
      </header>
      <SummaryPanel />
      <ChatPanel />
    </main>
  )
}
