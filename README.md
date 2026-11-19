# Finance spend intelligence assistant

A small web app where a finance analyst asks questions about 2025 vendor invoices and the procurement policy (FIN-POL-014), and every answer shows what it is based on: the exact policy text, the invoice rows, and the query that produced them.

FastAPI backend, React (Vite + TypeScript) frontend, Claude Opus 5.5 on AWS Bedrock.

![The app answering "What are our top 5 vendors by total spend in 2025?": invoice data overview on the left, per-currency top 5 with policy evidence on the right](infographics/ui_top5.png)

## Contents

- [Setup](#setup)
  - [LLM path](#llm-path)
- [How it works](#how-it-works)
  - [`POST /ask` response](#post-ask-response)
- [Write-up](#write-up)
  - [What I built and what I left out](#what-i-built-and-what-i-left-out)
  - [How I'd evaluate it](#how-id-evaluate-it)
  - [What production would need](#what-production-would-need)
- [Time taken and next steps](#time-taken-and-next-steps)
- [AI harness](#ai-harness)

## Setup

Prerequisites: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+, and Bedrock access to Claude.

```bash
cp .env.example .env          # fill in Bedrock credentials, see comments in the file

# backend on :8000
cd backend
uv sync
uv run uvicorn app.main:app --port 8000

# frontend on :5173 (second terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The summary panel loads from `GET /summary` before any question is asked. API docs are at http://localhost:8000/docs.

Tests and eval:

```bash
cd backend
uv run pytest             # data ground truths, citation checker, API contract (no LLM needed)
uv run pytest ../eval -v  # 10-question eval, one test per question (makes real Bedrock calls)
```

### LLM path

**Claude Opus 5.5 on AWS Bedrock** (`us.anthropic.claude-opus-5-5`), through the Anthropic Python SDK's `AnthropicBedrock` client. `.env.example` documents both auth options: a Bedrock API key (`AWS_BEARER_TOKEN_BEDROCK`), which is what I used through a corporate Bedrock gateway (`ANTHROPIC_BEDROCK_BASE_URL`), or standard AWS credentials via boto3.

## How it works

![Architecture: browser to FastAPI to Claude, tool calls into the shared pandas data layer, and evidence built by code](infographics/invoice_qa_architecture_infographic.png)

```
Browser --POST /ask--> FastAPI --> Claude (policy text in system prompt)
                                     | tool calls (validated by Pydantic)
                                     v
                     query_invoices / aggregate / get_vendors
                                     | pandas data layer (shared with GET /summary)
                                     v
               Claude returns JSON: {status, answer, policy_sections}
                                     v
       code builds evidence: policy quotes from the file, rows from the tool calls
```

- **Two endpoints.** `GET /summary` is deterministic, no LLM. `POST /ask` runs the tool loop. The three tools are in-process Python functions, not HTTP endpoints.
- **Policy goes in the prompt.** About 50 lines, so no vector store. Policy-only questions ("who approves EUR 60,000?") run no tools.
- **Fixed tools, no generated code or SQL.** The model picks a tool and fills in arguments. Pydantic models generate the tool schemas, validate the arguments (validation errors go back to the model so it can fix the call), and define the API contract.
- **Evidence comes from code, not the model.** The model only returns prose and section IDs. The backend checks each ID against the policy file, drops unknown ones with a warning, and attaches the exact text. Rows and groups come straight from the tool results.
- **Routing is visible.** `route` in the response is derived from what was actually used (`policy`, `data`, both or neither), and the UI shows it as "Based on: ..." above the evidence.
- **Currency is never summed.** There are no FX rates, and §5.1 requires the ECB rate on the invoice date. `aggregate` always splits money metrics by currency in code, so "top 5 vendors" returns a top 5 per currency.
- **Failure handling.** Iteration cap (6 model round trips), 90 s timeout, refusal and truncation checks. All return `{error, message}` with HTTP 502/504, and the UI shows an error with Retry. Bad tool arguments are retried by the model. Declines (`status: "declined"`) are a normal answer, not an error.

### `POST /ask` response

```json
{
  "status": "answered | declined",
  "answer": "prose from the model",
  "route": ["policy", "data"],
  "policy_evidence": [{"section": "4.1", "text": "exact text from procurement_policy.md"}],
  "data_evidence": [{"tool": "query_invoices", "args": {}, "total_matched": 4, "truncated": false, "rows": [], "groups": null}],
  "warnings": ["Amounts are reported per currency..."],
  "llm": "bedrock:us.anthropic.claude-opus-5-5"
}
```

## Write-up

### What I built and what I left out

A simple prototype. Nothing fancy, but it works.

I spent most of the time thinking about the right architecture. Determinism is very important here, so the LLM has a narrow job: it translates the user's question into a call to one of three fixed tools (`query_invoices`, `aggregate`, `get_vendors`) and fills in the right parameters. It decides which tool to call and with what, but it can't create functions, code or SQL on the fly. If it could, the same question asked several times could end up with different answers. I didn't want that behaviour.

I left out auth, Docker, deployment, chat history, streaming responses, visual polish and FX conversion. Most of the questions in the assignment can be answered without them.

### How I'd evaluate it

Two different sets of evals.

The first is evals written as pytests, for questions where we know the expected answer. Here we can simply assert that a given number, invoice ID or word is in the answer. That's what [`eval/test_eval.py`](eval/test_eval.py) does today: 10 questions, with the expected values computed in plain pandas from the CSVs, independently of the app's tools.

The second set is harder and needs an LLM-as-a-judge. These are the checks you can't simply assert: how the assistant writes the answer to the user, or whether it declines for a good reason backed up by the policy. The judge needs a scoring rubric that spells out the criteria and how to score the assistant's answer against each one.

### What production would need

Probably no pandas for the data, SQL queries instead. The tools stay fixed; they'd just run parameterised SQL rather than pandas filters.

- **Real data and access control.** Replace the CSVs with read-only queries against the finance warehouse. Enforce row-level security per user (entity, cost center) in the tool layer, not in the prompt, so the model only sees rows the user is allowed to see. SSO for the 200 users.
- **Audit trail (§8.2).** Persist every question, user, model ID, prompt version, tool call with arguments, returned invoice IDs and the final answer. Today this only lives in the logs. The evidence is already structured, so it's one write per request.

## Time taken and next steps

Planning took about 40 minutes across two sessions (timestamps in `ai_harness/planning_conversation.md`). The build session, from scaffold to eval, README and repo setup, took about 45 minutes ([`ai_harness/build_session.md`](ai_harness/build_session.md)). Planning ran on Claude Sonnet 5.5 and the build on Claude Opus 5.5.

Next steps, in order: number and ID verification against tool results on every answer; a dated FX table so currencies can be combined with a visible label; a tighter citation rule in the prompt to cut over-citing; persisting the audit record per request; streaming.

## AI harness

I built this with Claude Code. Everything the brief asks for is in the repo:

- [`ai_harness/planning_conversation.md`](ai_harness/planning_conversation.md): the planning conversation, where the design decisions were made
- [`ai_harness/implementation_plan.md`](ai_harness/implementation_plan.md): the handoff plan the build followed
- [`ai_harness/build_session.md`](ai_harness/build_session.md): the build session log (Claude Opus 5.5; planning used Claude Sonnet 5.5)
- [`CLAUDE.md`](CLAUDE.md): project instructions for the coding agent
- [`backend/prompts/system.md`](backend/prompts/system.md): the runtime system prompt (the policy is injected at load)
- Tool descriptions in [`backend/app/tools.py`](backend/app/tools.py), which are part of the prompt
