import { type FormEvent, useState } from 'react'
import { type AskResponse, ask } from './api'
import { Evidence } from './Evidence'

type Message =
  | { id: number; question: string; status: 'pending' }
  | { id: number; question: string; status: 'done'; response: AskResponse }
  | { id: number; question: string; status: 'error'; error: string }

const EXAMPLES = [
  'What are our top 5 vendors by total spend in 2025?',
  'What is our total spend with vendors based in Spain?',
  'Who is allowed to approve an invoice of EUR 60,000?',
  'Which invoices from inactive vendors have no approver, and what should happen to them?',
]

let nextId = 1

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const pending = messages.some((m) => m.status === 'pending')

  const update = (id: number, m: Message) => setMessages((prev) => prev.map((x) => (x.id === id ? m : x)))

  const run = (id: number, question: string) => {
    update(id, { id, question, status: 'pending' })
    ask(question)
      .then((response) => update(id, { id, question, status: 'done', response }))
      .catch((e: Error) => update(id, { id, question, status: 'error', error: e.message }))
  }

  const submit = (question: string) => {
    const q = question.trim()
    if (!q || pending) return
    const id = nextId++
    setMessages((prev) => [...prev, { id, question: q, status: 'pending' }])
    setInput('')
    run(id, q)
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit(input)
  }

  return (
    <section className="panel chat">
      <h2>Ask about invoices and policy</h2>

      <div className="messages">
        {messages.length === 0 && (
          <div className="examples">
            <p className="muted">Try one of these:</p>
            {EXAMPLES.map((q) => (
              <button key={q} className="example" onClick={() => submit(q)} disabled={pending}>{q}</button>
            ))}
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className="message">
            <div className="question">{m.question}</div>
            {m.status === 'pending' && <div className="answer muted">Thinking: querying policy and data…</div>}
            {m.status === 'error' && (
              <div className="answer error">
                <p>Request failed. {m.error}</p>
                <button onClick={() => run(m.id, m.question)} disabled={pending}>Retry</button>
              </div>
            )}
            {m.status === 'done' && (
              <div className={`answer ${m.response.status}`}>
                {m.response.status === 'declined' && <div className="status-tag">Declined: cannot answer from available sources</div>}
                <p className="answer-text">{m.response.answer}</p>
                <Evidence r={m.response} />
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={onSubmit} className="ask-form">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={pending ? 'Waiting for the answer…' : 'Ask a question'}
          disabled={pending}
          maxLength={1000}
        />
        <button type="submit" disabled={pending || !input.trim()}>Ask</button>
      </form>
    </section>
  )
}
