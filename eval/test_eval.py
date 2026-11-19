"""Small eval set for POST /ask, one pytest per case.

Ground truth is computed here with plain pandas straight from the CSVs, independently of the app's tools,
so a bug in the tools cannot also hide in the expected values.

Run:  cd backend && uv run pytest ../eval -v
Each run makes real LLM calls to Bedrock. Full responses are written to eval/last_run.json.
"""

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")
load_dotenv(ROOT / ".env")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# ---------- independent ground truth ----------
inv = pd.read_csv(ROOT / "backend/data/invoices_2025_clean.csv", parse_dates=["invoice_date"])
ven = pd.read_csv(ROOT / "backend/data/vendor_master.csv")
df = inv.merge(ven[["vendor_id", "country", "status"]], on="vendor_id")

# ECB rate on the invoice date, or the last one published before it (weekends, TARGET holidays). EUR is 1.0.
ecb = pd.read_csv(ROOT / "backend/data/conversion/eurofxref-hist.csv", usecols=["Date", "USD", "GBP"], parse_dates=["Date"])
ecb = ecb.melt(id_vars="Date", var_name="currency", value_name="rate").dropna().sort_values("Date")
df = pd.merge_asof(df.sort_values("invoice_date"), ecb, left_on="invoice_date", right_on="Date", by="currency")
df.loc[df.currency == "EUR", "rate"] = 1.0
df["amount_eur"] = (df.amount / df.rate).round(2)


def money(x: float) -> str:
    return f"{x:.2f}"


spain_eur = df[df.country == "Spain"]["amount_eur"].sum()
top5 = df.groupby("vendor_name")["amount_eur"].sum().sort_values(ascending=False).head(5)
gbp_total = df[df.currency == "GBP"]["amount"].sum()
q1_eur = df[(df.currency == "EUR") & (df.invoice_date >= "2025-01-01") & (df.invoice_date <= "2025-03-31")]["amount"].sum()

CASES = [
    {"id": "spain_total", "q": "What is our total spend with vendors based in Spain?",
     "status": "answered", "numbers": [money(spain_eur)], "sections": ["5.1"], "needs_data": True},
    {"id": "top5_vendors", "q": "What are our top 5 vendors by total spend in 2025?",
     "status": "answered", "numbers": [money(v) for v in top5.values], "text": list(top5.index), "needs_data": True},
    {"id": "gbp_original_currency", "q": "How much did we spend in GBP, in the original currency?",
     "status": "answered", "numbers": [money(gbp_total)], "needs_data": True},
    {"id": "inactive_over_50k_eur", "q": "Which invoices from inactive vendors are above EUR 50,000 once GBP and USD are converted to EUR?",
     "status": "answered", "invoices": sorted(df[(df.status == "INACTIVE") & (df.amount_eur > 50000)].invoice_number),
     "needs_data": True},
    {"id": "approver_60k", "q": "Who is allowed to approve an invoice of EUR 60,000?",
     "status": "answered", "text": ["Finance Director"], "sections": ["3"], "needs_data": False},
    {"id": "inactive_no_approver", "q": "Which invoices from inactive vendors have no approver?",
     "status": "answered", "invoices": sorted(df[(df.status == "INACTIVE") & df.approved_by.isna()].invoice_number),
     "needs_data": True},
    {"id": "on_hold_eur_50k", "q": "Which EUR invoices over 50,000 come from vendors that are on hold, and what does policy require?",
     "status": "answered",
     "invoices": sorted(df[(df.status == "ON_HOLD") & (df.currency == "EUR") & (df.amount > 50000)].invoice_number),
     "sections": ["4.1"], "needs_data": True},
    {"id": "missing_po_count", "q": "How many invoices are missing a PO number?",
     "status": "answered", "numbers": [str(int(df.po_number.isna().sum()))], "needs_data": True},
    {"id": "q1_eur_spend", "q": "What was our total EUR-denominated spend in Q1 2025 (January to March)?",
     "status": "answered", "numbers": [money(q1_eur)], "needs_data": True},
    {"id": "segregation_of_duties", "q": "Were any invoices approved by the same person who requested them?",
     "status": "declined", "section_prefix": "7"},
    {"id": "payment_status", "q": "Which invoices have been paid late?", "status": "declined"},
    {"id": "fake_vendor", "q": "How much did we spend with Acme Widgets Ltd?", "no_matches": True},
]


def score(case: dict, status_code: int, body: dict) -> list[str]:
    """Return a list of failed checks (empty = pass)."""
    if status_code != 200:
        return [f"HTTP {status_code}: {body}"]
    fails = []
    answer = body["answer"]
    flat = answer.replace(",", "")
    cited = [p["section"] for p in body["policy_evidence"]]
    evidence_invoices = {r["invoice_number"] for d in body["data_evidence"] for r in (d["rows"] or []) if "invoice_number" in r}

    if "status" in case and body["status"] != case["status"]:
        fails.append(f"status {body['status']} != {case['status']}")
    for n in case.get("numbers", []):
        if n not in flat:
            fails.append(f"number {n} not in answer")
    for t in case.get("text", []):
        if t.lower() not in answer.lower():
            fails.append(f"text '{t}' not in answer")
    for s in case.get("sections", []):
        if s not in cited:
            fails.append(f"section {s} not cited (cited {cited})")
    if (p := case.get("section_prefix")) and not any(c.split(".")[0] == p for c in cited):
        fails.append(f"no §{p}.x cited (cited {cited})")
    if "invoices" in case:
        if set(case["invoices"]) != evidence_invoices:
            fails.append(f"evidence rows {sorted(evidence_invoices)} != {case['invoices']}")
        missing = [i for i in case["invoices"] if i not in answer]
        if missing:
            fails.append(f"invoices not named in answer: {missing}")
    if case.get("needs_data") is True and not body["data_evidence"]:
        fails.append("expected a data query, none ran")
    if case.get("needs_data") is False and body["data_evidence"]:
        fails.append("policy-only question ran a data query")
    if case.get("no_matches") and any(d["total_matched"] > 0 for d in body["data_evidence"]):
        fails.append("expected no matching rows")
    if case.get("no_matches") and re.search(r"\d{1,3}(,\d{3})+\.\d{2}", answer):
        fails.append("answer quotes an amount for a vendor that does not exist")
    return fails


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def results():
    collected = []
    yield collected
    out = Path(__file__).resolve().parent / "last_run.json"
    out.write_text(json.dumps(collected, indent=2))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_eval_case(case, client, results):
    t = time.time()
    r = client.post("/ask", json={"question": case["q"]})
    fails = score(case, r.status_code, r.json())
    results.append({"id": case["id"], "question": case["q"], "pass": not fails, "fails": fails,
                    "seconds": round(time.time() - t, 1), "response": r.json()})
    assert not fails, "; ".join(fails)
