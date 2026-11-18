"""API and evidence tests that run without an LLM (stub provider)."""

import pytest
from fastapi.testclient import TestClient

from app.evidence import check_citations, policy_sections
from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "stub")
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


def test_stub_policy_only(client):
    body = client.post("/ask", json={"question": "Who is allowed to approve an invoice of EUR 60,000?"}).json()
    assert "Finance Director" in body["answer"]
    assert body["route"] == ["policy"] and body["data_evidence"] == []
    assert body["policy_evidence"][0]["section"] == "3"
    assert body["llm"].startswith("stub")


def test_stub_data_question(client):
    body = client.post("/ask", json={"question": "Total spend with vendors based in Spain?"}).json()
    groups = body["data_evidence"][0]["groups"]
    assert {g["currency"]: g["value"] for g in groups}["EUR"] == 1576971.22
    assert "data" in body["route"]


def test_bad_tool_args_return_error_to_llm():
    from app.evidence import EvidenceCollector
    from app.llm import _run_tool

    collector = EvidenceCollector()
    content, is_error = _run_tool("query_invoices", {"filters": {"vendor_status": "inactive"}}, collector)
    assert is_error and "vendor_status" in content and collector.items == []
