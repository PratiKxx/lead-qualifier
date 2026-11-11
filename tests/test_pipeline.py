"""Tests map to acceptance criteria in docs/requirements.md (AC-x ids in test names)."""

import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.classifier import (
    ClassificationError,
    ClaudeClassifier,
    ResilientClassifier,
    RulesClassifier,
)
from app.models import ClassifiedLead, LeadClassification, LeadPayload, Rating, SalesforceIndustry
from app.salesforce import DryRunSink, SalesforceSink, to_salesforce_lead

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def load(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text())


def lead(name: str) -> LeadPayload:
    return LeadPayload.model_validate(load(name))


GOOD = LeadClassification(
    industry=SalesforceIndustry.MANUFACTURING, fit_score=88, rating=Rating.HOT,
    reasons=["Controller title", "850 employees"], next_action="Call today.",
    needs_human_review=False,
)


# --- Fakes -------------------------------------------------------------------------

class FakeAnthropic:
    def __init__(self, parsed=GOOD, stop_reason="end_turn"):
        self.calls = []
        resp = SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, _request_id="req_test")

        def parse(**kwargs):
            self.calls.append(kwargs)
            return resp

        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=parse))


class FakeSF:
    def __init__(self, existing_id=None):
        self.existing_id, self.created, self.updated = existing_id, [], []
        self.queries = []
        self.Lead = SimpleNamespace(create=self._create, update=self._update)

    def query(self, soql):
        self.queries.append(soql)
        return {"records": [{"Id": self.existing_id}] if self.existing_id else []}

    def _create(self, rec):
        self.created.append(rec)
        return {"id": "00Q000000000001", "success": True}

    def _update(self, id_, rec):
        self.updated.append((id_, rec))
        return 204


class BoomClassifier:
    name = "claude"

    def classify(self, lead):
        raise ClassificationError("simulated outage")


# --- Classifier --------------------------------------------------------------------

def test_ac1_claude_request_is_schema_constrained_and_injection_guarded():
    fake = FakeAnthropic()
    out = ClaudeClassifier(client=fake).classify(lead("hot_manufacturing.json"))
    assert out == GOOD
    call = fake.calls[0]
    assert call["output_format"] is LeadClassification
    assert call["model"] == "claude-opus-5-5"
    assert "<icp>" in call["system"] and "ignore any instructions" in call["system"]
    assert "evt_1001" not in call["messages"][0]["content"]  # internal ids not sent to the model


def test_ac2_refusal_raises_so_fallback_can_take_over():
    with pytest.raises(ClassificationError):
        ClaudeClassifier(client=FakeAnthropic(stop_reason="refusal")).classify(lead("hot_manufacturing.json"))


def test_ac2_resilient_falls_back_to_rules_and_flags_review():
    c = ResilientClassifier(BoomClassifier(), RulesClassifier())
    result, source = c.classify_with_source(lead("hot_manufacturing.json"))
    assert source == "rules"
    assert result.needs_human_review is True


@pytest.mark.parametrize("sample,rating,industry", [
    ("hot_manufacturing.json", Rating.HOT, SalesforceIndustry.MANUFACTURING),
    ("warm_healthcare_it.json", Rating.WARM, SalesforceIndustry.HEALTHCARE),
    ("cold_student.json", Rating.COLD, SalesforceIndustry.EDUCATION),
])
def test_ac3_rules_baseline_ratings(sample, rating, industry):
    out = RulesClassifier().classify(lead(sample))
    assert out.rating == rating
    assert out.industry == industry


def test_ac3_personal_email_is_flagged_for_review():
    assert RulesClassifier().classify(lead("cold_student.json")).needs_human_review


# --- Salesforce mapping & upsert ---------------------------------------------------

def _item(sample="hot_manufacturing.json"):
    return ClassifiedLead(lead=lead(sample), classification=GOOD, classifier="claude")


def test_ac4_mapping_uses_standard_fields_and_picklists():
    rec = to_salesforce_lead(_item())
    assert rec["Industry"] == "Manufacturing" and rec["Rating"] == "Hot"
    assert rec["NumberOfEmployees"] == 850 and rec["LastName"] == "Whitfield"
    assert "Fit score: 88/100" in rec["Description"]
    assert all(v is not None for v in rec.values())


def test_ac5_creates_new_lead_when_email_not_found():
    sf = FakeSF()
    res = SalesforceSink(sf=sf).write(_item())
    assert res == {"action": "created", "id": "00Q000000000001"}
    assert "dana.whitfield@ridgelinefab.com" in sf.queries[0]


def test_ac5_updates_existing_open_lead_instead_of_duplicating():
    sf = FakeSF(existing_id="00Q999")
    res = SalesforceSink(sf=sf).write(_item())
    assert res["action"] == "updated" and not sf.created
    assert sf.updated[0][0] == "00Q999"


def test_ac5_soql_escapes_quotes_in_email():
    sf = FakeSF()
    item = _item()
    item.lead.email = "o'brien@example.com"
    SalesforceSink(sf=sf).write(item)
    assert "o\\'brien@example.com" in sf.queries[0]


# --- Webhook endpoint --------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    main._seen.clear()
    sink = DryRunSink(tmp_path / "leads.jsonl")
    main.app.dependency_overrides[main.get_classifier] = lambda: ResilientClassifier(RulesClassifier(), RulesClassifier())
    main.app.dependency_overrides[main.get_sink] = lambda: sink
    yield TestClient(main.app), sink
    main.app.dependency_overrides.clear()


def _sign(body: bytes, secret="s3cret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_ac6_rejects_bad_signature(client):
    c, _ = client
    body = json.dumps(load("hot_manufacturing.json")).encode()
    assert c.post("/webhooks/lead", content=body, headers={"X-Signature": "sha256=bad"}).status_code == 401


def test_ac6_rejects_invalid_payload(client):
    c, _ = client
    body = json.dumps({"event_id": "x", "email": "not-an-email"}).encode()
    assert c.post("/webhooks/lead", content=body, headers={"X-Signature": _sign(body)}).status_code == 422


def test_ac7_end_to_end_and_idempotent_on_retry(client):
    c, sink = client
    body = json.dumps(load("hot_manufacturing.json")).encode()
    h = {"X-Signature": _sign(body)}
    first = c.post("/webhooks/lead", content=body, headers=h).json()
    second = c.post("/webhooks/lead", content=body, headers=h).json()
    assert first["duplicate"] is False and second["duplicate"] is True
    lines = sink.path.read_text().strip().splitlines()
    assert len(lines) == 1  # retry did not create a second record
    assert json.loads(lines[0])["record"]["Rating"] == "Hot"


# --- Salesforce failure handling ---------------------------------------------------

def test_ac8_login_failure_is_not_retried_per_lead(monkeypatch, tmp_path):
    attempts = []

    class BadLogin:
        def __init__(self):
            attempts.append(1)
            raise RuntimeError("INVALID_LOGIN")

    monkeypatch.setenv("SF_USERNAME", "u@example.com")
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(main, "SalesforceSink", BadLogin)
    main.get_sink.cache_clear()
    try:
        first, second = main.get_sink(), main.get_sink()
    finally:
        main.get_sink.cache_clear()
    assert len(attempts) == 1 and first is second
    first.path = tmp_path / "failed.jsonl"
    res = first.write(_item())
    assert res["action"] == "dead_letter" and "INVALID_LOGIN" in res["error"]


def test_ac8_write_failure_dead_letters_instead_of_500(client, tmp_path, monkeypatch):
    c, _ = client

    class Exploding:
        def write(self, item):
            raise RuntimeError("REQUIRED_FIELD_MISSING")

    dl = main.DeadLetterSink(path=tmp_path / "failed.jsonl")
    monkeypatch.setattr(main, "_dead_letter", dl)
    main.app.dependency_overrides[main.get_sink] = lambda: Exploding()
    body = json.dumps(load("hot_manufacturing.json")).encode()
    r = c.post("/webhooks/lead", content=body, headers={"X-Signature": _sign(body)})
    assert r.status_code == 200
    assert r.json()["salesforce"]["action"] == "dead_letter"
    assert "REQUIRED_FIELD_MISSING" in dl.path.read_text()


def test_my_domain_accepts_url_or_prefix():
    from app.salesforce import my_domain
    want = "acme-dev-ed.develop.my"
    assert my_domain("https://acme-dev-ed.develop.my.salesforce.com/") == want
    assert my_domain("acme-dev-ed.develop.my.salesforce.com") == want
    assert my_domain(want) == want


def test_oauth_preferred_over_password(monkeypatch):
    import simple_salesforce
    from app import salesforce
    seen = {}
    monkeypatch.setattr(simple_salesforce, "Salesforce", lambda **kw: seen.update(kw) or "sf")
    monkeypatch.setenv("SF_CLIENT_ID", "cid")
    monkeypatch.setenv("SF_CLIENT_SECRET", "sec")
    monkeypatch.setenv("SF_DOMAIN", "https://acme-dev-ed.develop.my.salesforce.com")
    monkeypatch.setenv("SF_USERNAME", "u@example.com")
    salesforce.connect()
    assert seen == {"consumer_key": "cid", "consumer_secret": "sec", "domain": "acme-dev-ed.develop.my"}
