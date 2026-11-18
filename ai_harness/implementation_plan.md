# Implementation plan: Finance spend intelligence assistant

Handoff document for a fresh session. Read first: `assignment_brief.pdf`, `data_extracted/data/procurement_policy.md`, and `ai_harness/planning_conversation.md` (the reasoning behind every decision below).

Time box from the brief: 3 to 4 hours. Do not exceed it. Do not build auth, deployment, CI/CD, or polish.

## 1. Architecture

Two HTTP endpoints, nothing else.

| Endpoint | LLM? | Purpose |
|---|---|---|
| `GET /summary` | No | Overview of invoice data, loaded by the frontend on startup |
| `POST /ask` | Yes | Question in; answer plus evidence out |

Inside `/ask` the LLM calls three in-process Python tools. They are not HTTP endpoints. The LLM never sees an OpenAPI spec; it sees tool definitions generated from Pydantic models.

```
Browser --POST /ask--> FastAPI --> LLM (policy text in system prompt)
                                     | tool calls
                                     v
                    query_invoices / aggregate / get_vendors
                                     | pandas data layer (shared with /summary)
                                     v
                          LLM writes answer + cites policy sections
                                     v
          code builds evidence (policy quotes, rows, tool trace) --> Browser
```

Principles (all decided):
- Policy is a system-prompt block (about 50 lines). No vector DB, no skill mechanism in the app.
- Fixed, pre-written tools. The LLM picks a tool and fills in arguments; it never writes code or SQL.
- Evidence is built by code, not by the LLM. The LLM only writes prose and returns policy section IDs.
- `/summary` and the tools share one data layer, so numbers cannot disagree.
- Pydantic models do three jobs: generate tool JSON schemas, validate LLM-sent arguments (errors go back to the LLM for a retry), and define the FastAPI request/response contract.

## 2. Data facts (verified against the CSVs)

- 140 invoices, 10 vendors, no vendor_id mismatches, no unknown vendors. Dates 2025-01-03 to 2025-12-26.
- Currencies: 89 EUR, 27 GBP, 24 USD. No FX rates provided. Policy §5.1 says convert at ECB rate on invoice date, which we cannot do.
- 2 credit notes (negative): INV-20029 (EUR -52,749.39), INV-20096 (USD -29,534.55). Neither belongs to a Spanish vendor.
- 21 invoices missing PO, 25 missing approver, 29 invoices from non-ACTIVE vendors (PharmaPrint V-1006 INACTIVE, Crown Travel V-1010 ON_HOLD).
- No requester column, so §7 (segregation of duties) cannot be checked from data. The assistant must decline it.
- No payment-status column. Never say "paid"; say "unapproved" or "unprocessed".
- Vendor master carries country, category, status. Invoices carry vendor_id and name only, so join at load.
- Known ground truths for tests:
  - Spain vendors (V-1002, V-1006, V-1009): EUR 1,576,971.22 (30 invoices), GBP 646,618.51 (12), USD 343,748.06 (7), 49 total.
  - INACTIVE vendor and no approver: 3 invoices (INV-20056, INV-20108, INV-20136), all PharmaPrint.
  - ON_HOLD, EUR, amount over 50,000: 4 invoices (INV-20083, INV-20127, INV-20130, INV-20106), all Crown Travel.
  - "Who can approve EUR 60,000": Finance Director, §3 (50,000.01 to 250,000). Policy-only, no tool call.

## 3. Decisions to confirm at the start of the new session

1. **LLM access.** Not yet answered. Options: Anthropic API key, AWS Bedrock (the user's settings use `us.anthropic.*` model IDs), or Ollama. Use the Anthropic SDK with the provider and model ID read from env vars. Build the labelled stub regardless (section 6, step 7).
2. **Optional extra.** Recommended: eval set (8 to 10 question/answer pairs plus scoring script). Pick one at most.
3. **Currency handling.** Assumed accepted: report per currency, never sum across currencies, no invented FX rates. Mention a labelled static FX table as a README next step.
4. **Row cap.** Assumed accepted: `query_invoices` limit default 20, max 50.

## 4. Tool specifications

All Pydantic. Filters are optional and combined with AND.

### Shared filter model

```python
class InvoiceFilters(BaseModel):
    vendor_id: str | None
    vendor_name: str | None               # case-insensitive contains
    vendor_country: str | None
    vendor_category: str | None
    vendor_status: Literal["ACTIVE", "INACTIVE", "ON_HOLD"] | None
    currency: Literal["EUR", "GBP", "USD"] | None
    date_from: date | None
    date_to: date | None
    cost_center: str | None
    description_contains: str | None
    min_amount: float | None              # raw amount in the invoice's own currency
    max_amount: float | None
    has_po: bool | None
    has_approver: bool | None
    approved_by: str | None
```

### Tool 1: `query_invoices(filters, sort_by, limit)`

- Purpose: return individual invoice rows ("show me invoices where...").
- Args: `filters`, `sort_by` in {amount, invoice_date, vendor_name} default invoice_date, `sort_desc` default true, `limit` 1 to 50 default 20.
- Returns `total_matched`, `returned`, `truncated`, `rows`. Each row: invoice fields plus vendor_country, vendor_category, vendor_status, `is_credit_note` (amount < 0). Missing PO or approver is `null`, not an empty string.
- Tool description must say: amount filters are raw, so combine with `currency` for threshold questions; this tool does not compute totals, use `aggregate`.
- Empty result is valid (`total_matched: 0`); the prompt tells the LLM to report "no matching invoices".

### Tool 2: `aggregate(metric, group_by, filters, top_n, sort_desc)`

- Purpose: sums, counts, averages, optionally grouped ("how much", "how many", "top N").
- `metric` in {sum_amount, count, avg_amount}. `group_by` is a list from {vendor_name, vendor_country, vendor_category, vendor_status, cost_center, approved_by, description, month}. `top_n` 1 to 20.
- Currency is always an implicit grouping column for sum_amount and avg_amount, enforced in code. `top_n` ranks within each currency (up to N per currency).
- Returns per group: `keys`, `currency`, `value`, `invoice_count`, `credit_note_count`, `invoice_numbers`. Plus `total_invoices_matched`.
- Credit notes are included in sums; the count lets the LLM say so.

### Tool 3: `get_vendors(filters)` (proposed, not yet reviewed with the user)

- Purpose: look up the vendor master ("which vendors are on hold", "where is Helix based").
- Filters: vendor_id, vendor_name (contains), country, category, status.
- Returns vendor rows (id, name, country, category, status) and a count.
- Must be reviewed with the user before building; keep it small.

### Not tools

Policy lookup (in the system prompt), summary (`get_summary()` called directly by `/summary`).

## 5. API contracts

### `GET /summary`

Deterministic, no LLM. Fields: total invoice count; spend by currency (currency, total, count); spend by vendor status (status, currency, total, count); compliance flags (missing_po, missing_approver, non_active_vendor, credit_notes counts). All figures per currency, never combined.

### `POST /ask`

Request: `{ "question": str }` (non-empty, length-capped).

Response (Pydantic model):
- `status`: "answered" or "declined"
- `answer`: str
- `route`: subset of {"policy", "data"}, derived from what was actually used
- `policy_evidence`: list of `{section, text}`; section IDs returned by the LLM, validated against the policy file, text pulled from the file (never from the LLM)
- `data_evidence`: list of `{tool, args, total_matched, truncated, rows or groups}`
- `warnings`: list of str (truncation, per-currency notice, credit notes included)

Errors: LLM failure, timeout, or iteration cap reached returns a structured error body with an HTTP error status. The frontend must handle it.

## 6. Build steps (about 4 hours)

Suggested layout:

```
backend/
  app/main.py            FastAPI app, routes, CORS for the Vite dev port
  app/data.py            load CSVs, join vendors, filter/group helpers, get_summary()
  app/tools.py           Pydantic arg models, tool functions, tool registry, JSON schemas
  app/llm.py             provider client, tool-use loop (iteration cap, temperature 0), stub
  app/evidence.py        evidence collector, citation checker
  app/models.py          request/response models
  prompts/system.md      system prompt template (policy injected at load)
  tests/
frontend/                Vite + React
eval/                    optional extra
README.md
CLAUDE.md                project harness (brief asks for AI prompts and harness in the repo)
ai_harness/              planning log, this plan, further session logs
```

1. **Scaffold (15 min).** `uv` project for the backend, Vite React app, copy data into `backend/data/`. Check port availability before starting servers (FastAPI 8000 to 8099, Vite 5173 to 5179).
2. **Data layer (30 min).** Load and join. Filter function driven by `InvoiceFilters`. Group and aggregate helper. `get_summary()`. Write pytest checks against the known ground truths in section 2.
3. **Tools (30 min).** Pydantic arg models, tool functions returning invoice numbers for evidence, registry generating JSON schemas. Write careful tool descriptions; they are prompt engineering.
4. **System prompt (20 min).** Role, grounding rules (answer only from policy text and tool results; quote numbers only from tool results; never add across currencies; never claim payment status; say "in EUR" when a currency filter was applied; decline when neither source can answer; cite section IDs), full policy text, output format. Store in `prompts/system.md`.
5. **LLM loop and evidence (45 min).** Tool-use loop with iteration cap. Validate tool args via Pydantic; on validation error, return the error text to the LLM. Structured final output: answer, policy section IDs, declined flag. Citation checker and evidence collector. Response builder.
6. **Endpoints (15 min).** `/summary`, `/ask`, error handling, CORS.
7. **Stub LLM (15 min).** Clearly labelled in logs, README and the UI. Keyword router that maps a few question shapes to tool calls and a templated answer. The point is that the app runs without an API key; do not invest in it.
8. **Frontend (60 min).** Summary panel fetches on mount with its own loading, error and retry states. Chat panel with message list and per-message status (pending, answered, declined, error with retry). Under each answer an evidence block with three parts: policy quotes, data rows table (with truncation notice), and the query that ran (tool name and args). Disable input while a request is pending. The brief weights "how the UI makes clear what the answer is based on" most heavily.
9. **Extra (30 min).** If eval set: 8 to 10 questions with expected values computed by pandas independently of the tools (do not use the tools to compute ground truth), a scoring script, and one deliberately unanswerable question to test declining. Candidate questions: Spain total, top 5 vendors per currency, ON_HOLD EUR over 50,000, INACTIVE with no approver, EUR 60,000 approver, segregation of duties (expect decline), a payment-status question (expect decline), a fabricated vendor name (expect "not found").
10. **README (20 min).** Setup instructions, which LLM path was used (key, Bedrock, Ollama, or stub), then the write-up from the brief (half a page): what was built and left out; how to evaluate (ground-truth checks, citation validation, decline rate, human spot checks of evidence); what production needs (200 users, audit trail per §8.2 logging question, tool calls and rows, access control and row-level security, cost via model choice and caching, FX table, real database). Add how long it took and next steps. Link the AI harness folder.

## 7. Definition of done

- `GET /summary` and `POST /ask` work against the real data; frontend shows the summary before the first question.
- The four ground-truth questions in section 2 return correct figures with correct evidence.
- A policy-only question returns policy evidence and no rows; a data question returns rows and no policy unless relevant.
- Declined and error paths visible in the UI.
- README includes setup, the LLM path used, the three write-up items, time taken, and next steps.
- AI harness committed: project CLAUDE.md, `prompts/system.md`, planning log, and logs of the build sessions.
- Repo is public at least 48 hours before the interview.

## 8. Things not to do

- Do not add endpoints beyond the two (chat history is the only exception, and it is not the chosen extra).
- Do not let the LLM write code or SQL.
- Do not sum across currencies or invent FX rates.
- Do not take policy text or row data from the LLM's output into the evidence panel; always pull from source.
- Do not build a vector store, auth, Docker, or polish.
