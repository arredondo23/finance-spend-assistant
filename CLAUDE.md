# CLAUDE.md

Project instructions for AI coding agents working in this repo.

## What this is

Take-home prototype: finance spend assistant. FastAPI backend (`backend/`), React + Vite frontend (`frontend/`), eval set (`eval/`). Design rationale is in `ai_harness/planning_conversation.md` and `ai_harness/implementation_plan.md`. Read the plan before changing architecture.

## Commands

- Backend: `cd backend && uv run uvicorn app.main:app --port 8000`
- Frontend: `cd frontend && npm run dev`
- Tests (no LLM): `cd backend && uv run pytest`
- Eval (real LLM calls, costs money): `cd backend && uv run pytest ../eval -v`
- Check ports first (`lsof -i:8000`, `lsof -i:5173`); use 8000 to 8099 and 5173 to 5179.

## Invariants (do not break)

- Exactly two HTTP endpoints: `GET /summary`, `POST /ask`.
- The LLM never writes code or SQL. It calls the fixed tools in `backend/app/tools.py`.
- Never sum or convert across currencies. Currency grouping is enforced in `data.aggregate`, not in the prompt.
- Evidence (policy text, rows, groups) is built by code from source files and tool results, never copied from LLM output.
- `/summary` and the tools share `backend/app/data.py`, so their numbers cannot disagree.
- Never describe an invoice as "paid"; there is no payment column. Segregation of duties (§7) cannot be checked; there is no requester column.
- Ground truths in `backend/tests/test_data.py` must keep passing. Eval expected values are computed independently of the tools; keep it that way.

## LLM

Claude on AWS Bedrock via `anthropic.AnthropicBedrock`. Config in `.env` (see `.env.example`). Claude Opus 5.5 rejects `temperature` and forced `tool_choice`; use `output_config.effort` and the JSON output schema instead.

## Scope

Prototype, 3 to 4 hour time box. No auth, Docker, CI/CD or visual polish. Don't add features beyond the plan without asking.
