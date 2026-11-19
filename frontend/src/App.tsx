import { ChatPanel } from './ChatPanel'
import { SummaryPanel } from './SummaryPanel'

export default function App() {
  return (
    <main className="layout">
      <header>
        <div>
          <h1>Finance spend intelligence assistant</h1>
          <p className="muted small">
            Answers are grounded in FIN-POL-014 and the 2025 invoice data. Every answer shows the policy text and the rows it used.
          </p>
        </div>
        <div className="contact">
          <span className="contact-label">Contact</span>
          <span className="contact-name">Sergio Arredondo</span>
        </div>
      </header>
      <SummaryPanel />
      <ChatPanel />
    </main>
  )
}
