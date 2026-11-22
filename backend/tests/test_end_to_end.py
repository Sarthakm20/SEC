"""End-to-end: synthetic company -> DB + vector index -> LangGraph pipeline -> API."""

import pytest
from fastapi.testclient import TestClient

from app.db import repo
from app.ingest.chunker import index_text
from app.models import Verdict
from tests.factories import ACME, acme_chunks, acme_facts


@pytest.fixture(scope="module")
def client():
    from app.services import get_services

    repo.upsert_company(ACME)
    repo.replace_facts("ACME", acme_facts(), [])
    chunks = acme_chunks()
    repo.replace_chunks(chunks[0].accession, chunks)
    svc = get_services()
    svc.store.upsert(chunks, svc.embedder.embed_documents([index_text(c) for c in chunks]))
    svc.refresh_indexes()
    from app.api.main import app

    with TestClient(app) as c:
        yield c


def test_numeric_question_is_verified(client):
    r = client.post("/api/query", json={"question": "How did Acme's revenue change in fiscal 2024?"})
    assert r.status_code == 200
    d = r.json()
    assert d["verification"]["verdict"] == Verdict.VERIFIED.value
    assert "25.0%" in d["answer"] and "$1.25B" in d["answer"]
    assert [e["step"] for e in d["trace"]][:2] == ["plan", "financials"]
    assert d["calculations"] and d["calculations"][0]["inputs"]


def test_narrative_question_cites_passages(client):
    d = client.post("/api/query", json={"question": "What supply chain risks does Acme describe?"}).json()
    assert d["passages"] and "[S" in d["answer"]
    assert any("Taiwan" in p["chunk"]["text"] for p in d["passages"])
    assert d["verification"]["verdict"] in ("verified", "partially_verified")


def test_out_of_scope_abstains(client):
    d = client.post("/api/query", json={"question": "Should I buy Acme stock?"}).json()
    assert d["verification"]["verdict"] == "insufficient_evidence" and "can't answer" in d["answer"]


def test_missing_year_abstains(client):
    d = client.post("/api/query", json={"question": "What was Acme's revenue in fiscal 2031?"}).json()
    assert d["verification"]["verdict"] == "insufficient_evidence"
    assert not d["facts"]


def test_followup_in_thread(client):
    client.post("/api/query", json={"question": "What was Acme's gross margin in fiscal 2024?", "thread_id": "t1"})
    d = client.post("/api/query", json={"question": "and the operating margin?", "thread_id": "t1"}).json()
    assert d["plan"]["tickers"] == ["ACME"] and "24.0%" in d["answer"]


def test_overview_compare_and_runs(client):
    ov = client.get("/api/companies/ACME/overview?fiscal_year=2024").json()
    assert ov["kpis"][0]["display"] == "$1.25B" and abs(float(ov["kpis"][0]["yoy"]) - 0.25) < 1e-9
    cmp = client.get("/api/compare?tickers=ACME&fiscal_year=2024&metrics=gross_margin,current_ratio").json()
    assert cmp["rows"][0]["values"]["ACME"]["display"] == "60.0%"
    runs = client.get("/api/runs").json()
    assert runs and client.get(f"/api/runs/{runs[0]['run_id']}").status_code == 200
    assert client.get("/api/companies/ZZZZ/overview").status_code == 404


def test_validation(client):
    assert client.post("/api/query", json={"question": "x"}).status_code == 422
    assert client.post("/api/query", json={"question": "valid question", "thread_id": "bad id!"}).status_code == 422
