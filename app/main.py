"""Webhook service: POST /webhooks/lead -> classify -> write to Salesforce.

Run:  uvicorn app.main:app --reload
Mode is chosen from the environment (see .env.example):
- ANTHROPIC_API_KEY set     -> Claude classifies, rules are the fallback
- not set                   -> rules only
- SF_USERNAME set           -> real Salesforce writes
- not set / DRY_RUN=1       -> records go to out/leads.jsonl
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import ValidationError

from .classifier import ClaudeClassifier, ResilientClassifier, RulesClassifier
from .models import ClassifiedLead, LeadPayload
from .salesforce import DryRunSink, SalesforceSink, Sink

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lead-qualifier")

app = FastAPI(title="Lead Qualifier", version="1.0.0")


@lru_cache
def get_classifier() -> ResilientClassifier:
    rules = RulesClassifier()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ResilientClassifier(ClaudeClassifier(), rules)
    log.info("No ANTHROPIC_API_KEY: using rules-only classifier")
    return ResilientClassifier(rules, rules)


@lru_cache
def get_sink() -> Sink:
    if os.environ.get("SF_USERNAME") and os.environ.get("DRY_RUN", "0") != "1":
        return SalesforceSink()
    log.info("Salesforce not configured or DRY_RUN=1: writing to out/leads.jsonl")
    return DryRunSink()


# In-memory idempotency guard. Webhook senders retry on timeouts, so the same
# event_id can arrive twice. In production this would be Redis or a DB table.
_seen: dict[str, dict] = {}


def verify_signature(body: bytes, signature: str | None) -> None:
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        return  # signature checking disabled for local dev
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/webhooks/lead")
async def receive_lead(
    request: Request,
    x_signature: str | None = Header(default=None),
    classifier: ResilientClassifier = Depends(get_classifier),
    sink: Sink = Depends(get_sink),
) -> dict:
    body = await request.body()
    verify_signature(body, x_signature)
    try:
        lead = LeadPayload.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc

    if lead.event_id in _seen:
        return {**_seen[lead.event_id], "duplicate": True}

    classification, source = classifier.classify_with_source(lead)
    item = ClassifiedLead(lead=lead, classification=classification, classifier=source)
    write_result = sink.write(item)

    result = {
        "event_id": lead.event_id,
        "classifier": source,
        "classification": classification.model_dump(mode="json"),
        "salesforce": write_result,
        "duplicate": False,
    }
    _seen[lead.event_id] = result
    log.info(
        "lead=%s industry=%s score=%s rating=%s via=%s sf=%s",
        lead.event_id, classification.industry.value, classification.fit_score,
        classification.rating.value, source, write_result.get("action"),
    )
    return result
