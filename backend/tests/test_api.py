"""API and evidence tests that run without an LLM."""

import pytest
from fastapi.testclient import TestClient

from app.evidence import check_citations, policy_sections
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_policy_sections_parsed():
    s = policy_sections()
    assert "Finance Director" in s["3"]
    assert s["3.1"].startswith("3.1 Approval is evidenced")
    assert s["4.1"].startswith("4.1 Payments may only")


def test_unknown_citations_dropped():
    ev, warnings = check_citations(["§3.1", "12.4"])
    assert [e.section for e in ev] == ["3.1"]
    assert "12.4" in warnings[0]


def test_summary(client):
    r = client.get("/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["invoice_count"] == 140
    assert {c["currency"] for c in body["spend_by_currency"]} == {"EUR", "GBP", "USD"}


def test_ask_validation(client):
    assert client.post("/ask", json={"question": ""}).status_code == 422
    assert client.post("/ask", json={}).status_code == 422


def test_bad_tool_args_return_error_to_llm():
    from app.evidence import EvidenceCollector
    from app.llm import _run_tool

    collector = EvidenceCollector()
    content, is_error = _run_tool("query_invoices", {"filters": {"vendor_status": "inactive"}}, collector)
    assert is_error and "vendor_status" in content and collector.items == []
