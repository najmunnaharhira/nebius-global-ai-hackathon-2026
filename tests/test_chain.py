import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chain import analyze_chain, normalize_name
from app.llm import parse_json
from app.main import app
from app.models import CaseInput, Document, Parcel, Party, ProposedSale

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def load(name):
    return CaseInput(**json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8")))


def codes(engine):
    return sorted(f.code for f in engine.flags)


def khatian(owners, dag="1", area=10.0, mouza="Testpur"):
    return Document(id="K", doc_type="khatian", date="2000-01-01", mouza=mouza,
                    owners=[Party(name=n, share=s) for n, s in owners],
                    parcels=[Parcel(dag=dag, area_decimal=area)])


def deed(i, date, seller, buyer, area, dag="1", mouza="Testpur"):
    return Document(id=i, doc_type="deed", date=date, deed_no=i, mouza=mouza,
                    sellers=[Party(name=seller)], buyers=[Party(name=buyer)],
                    parcels=[Parcel(dag=dag, area_decimal=area)])


def mutation(i, date, owner, dag="1", area=10.0):
    return Document(id=i, doc_type="mutation", date=date, owners=[Party(name=owner)],
                    parcels=[Parcel(dag=dag, area_decimal=area)])


# ---------- name handling

def test_honorifics_are_ignored():
    assert normalize_name("Md. Rahim Uddin") == normalize_name("Mohammad Rahim Uddin") == "rahim uddin"
    assert normalize_name("Mst. Salma Begum") == "salma begum"
    assert normalize_name("মোঃ রহিম উদ্দিন") == "রহিম উদ্দিন"


# ---------- sample cases

def test_clean_chain_has_no_flags():
    case = load("1-clean-chain")
    e = analyze_chain(case.documents, case.proposed)
    assert e.flags == []
    assert e.risk() == "low"
    assert [(h.name, h.area_decimal) for h in e.holdings_list()] == [("Salma Begum", 33.0)]


def test_double_sale_case_flags_every_problem():
    case = load("2-double-sale")
    e = analyze_chain(case.documents, case.proposed)
    assert codes(e) == sorted([
        "SALE_BEFORE_ACQUISITION", "MISSING_LINK", "DOUBLE_SALE", "PROPOSED_UNBACKED", "NO_MUTATION",
    ])
    assert e.risk() == "high"


def test_name_mismatch_case():
    case = load("3-name-mismatch")
    e = analyze_chain(case.documents, case.proposed)
    assert "NAME_MISMATCH" in codes(e)


# ---------- individual rules

def test_oversell():
    docs = [khatian([("A", 1)], area=10), deed("D1", "2010-01-01", "A", "B", 15)]
    e = analyze_chain(docs)
    assert "OVERSELL" in codes(e)
    # only what A actually held passes to B
    assert {h.name: h.area_decimal for h in e.holdings_list()} == {"B": 10.0}


def test_partial_double_sale():
    docs = [khatian([("A", 1)], area=10),
            deed("D1", "2010-01-01", "A", "B", 6),
            deed("D2", "2011-01-01", "A", "C", 6)]
    e = analyze_chain(docs)
    assert "DOUBLE_SALE" in codes(e)


def test_shares_split_land():
    docs = [khatian([("A", 0.5), ("B", 0.5)], area=40), deed("D1", "2010-01-01", "A", "C", 25)]
    e = analyze_chain(docs)
    assert "OVERSELL" in codes(e)  # A owned only 20


def test_dag_and_mouza_mismatch():
    docs = [khatian([("A", 1)], dag="1"), deed("D1", "2010-01-01", "A", "B", 5, dag="2", mouza="Elsewhere")]
    e = analyze_chain(docs)
    assert {"DAG_NOT_IN_RECORD", "MOUZA_MISMATCH"} <= set(codes(e))


def test_proposed_oversell_and_mutation_ok():
    docs = [khatian([("A", 1)], area=10), deed("D1", "2010-01-01", "A", "B", 10),
            mutation("M1", "2010-06-01", "B")]
    e = analyze_chain(docs, ProposedSale(seller="B", dag="1", area_decimal=12))
    assert codes(e) == ["PROPOSED_OVERSELL"]


def test_record_owner_selling_needs_no_mutation():
    docs = [khatian([("A", 1)], area=10)]
    e = analyze_chain(docs, ProposedSale(seller="Md. A", dag="1", area_decimal=10))
    assert e.flags == []


# ---------- model reply parsing

def test_parse_json_tolerates_thinking_and_fences():
    reply = '<think>let me see {not json}</think>Here you go:\n```json\n{"a": {"b": "x}y"}}\n```'
    assert parse_json(reply) == {"a": {"b": "x}y"}}


# ---------- API (offline mode: no key set)

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    return TestClient(app)


def test_api_samples_and_analyze_offline(client):
    samples = client.get("/api/samples").json()
    assert len(samples) == 3
    case = client.get("/api/samples/2-double-sale").json()
    r = client.post("/api/analyze", json={"documents": case["documents"], "proposed": case["proposed"]})
    assert r.status_code == 200
    body = r.json()
    assert body["risk"] == "high"
    assert body["checklist"] and all(i["en"] and i["bn"] for i in body["checklist"])
    assert [t["status"] for t in body["trace"]] == ["rules", "skipped", "skipped"]


def test_extract_requires_key(client):
    r = client.post("/api/extract", files={"files": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 503


def test_sample_path_traversal_blocked(client):
    assert client.get("/api/samples/..%2Fapp%2Fmain").status_code == 404


def test_live_path_uses_ultra_and_super(monkeypatch):
    """With a key set, analysis calls Ultra then Super (Token Factory mocked)."""
    import app.llm as llm

    calls = []

    def fake_chat(model, messages, max_tokens=2048, temperature=0.1):
        calls.append(model)
        if model == llm.MODEL_REASON:
            return ('<think>…</think>{"summary_en": "Risky.", "summary_bn": "ঝুঁকিপূর্ণ।",'
                    ' "explanations": {"F1": "Why it matters."},'
                    ' "additional_flags": [{"severity": "low", "title": "Gap", "detail": "Long gap."}]}', 900)
        return ('{"items": [{"en": "Do X", "bn": "X করুন", "priority": "must", "related_flag": "F1"}]}', 300)

    monkeypatch.setenv("NEBIUS_API_KEY", "test")
    monkeypatch.setattr(llm, "chat", fake_chat)
    case = load("2-double-sale")
    r = TestClient(app).post("/api/analyze", json=case.model_dump())
    body = r.json()
    assert calls == [llm.MODEL_REASON, llm.MODEL_CHECKLIST]
    assert body["summary_en"] == "Risky."
    assert body["flags"][0]["explanation"] == "Why it matters."
    assert body["flags"][-1]["code"] == "AI_REVIEW"
    assert body["checklist"] == [{"en": "Do X", "bn": "X করুন", "priority": "must", "related_flag": "F1"}]
    assert [t["status"] for t in body["trace"]] == ["rules", "ok", "ok"]
