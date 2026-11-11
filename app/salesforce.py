"""Where classified leads go.

SalesforceSink upserts a Lead in a Salesforce org (dedupe on Email). DryRunSink writes
the exact same record to a local JSONL file so the whole flow can be demoed without
an org.

Only standard Lead fields are used, so this works in a fresh Developer Edition org
with zero setup.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .models import ClassifiedLead

DESCRIPTION_MARKER = "--- AI qualification ---"


def to_salesforce_lead(item: ClassifiedLead) -> dict:
    lead, c = item.lead, item.classification
    summary = [
        DESCRIPTION_MARKER,
        f"Fit score: {c.fit_score}/100 ({c.rating.value}) via {item.classifier}",
        f"Needs human review: {'YES' if c.needs_human_review else 'no'}",
        "Reasons:",
        *[f"- {r}" for r in c.reasons],
        f"Next action: {c.next_action}",
    ]
    if lead.message:
        summary += ["", "Original message:", lead.message]
    record = {
        "FirstName": lead.first_name,
        "LastName": lead.last_name,
        "Email": lead.email,
        "Company": lead.company,
        "Title": lead.title,
        "Website": lead.website,
        "NumberOfEmployees": lead.employee_count,
        "Country": lead.country,
        "LeadSource": lead.source,
        "Industry": c.industry.value,
        "Rating": c.rating.value,
        "Description": "\n".join(summary)[:32000],
    }
    return {k: v for k, v in record.items() if v is not None}


class Sink(Protocol):
    def write(self, item: ClassifiedLead) -> dict: ...


OUT_DIR = Path(__file__).resolve().parent.parent / "out"


class DryRunSink:
    action = "dry_run"

    def __init__(self, path: Path = OUT_DIR / "leads.jsonl"):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, item: ClassifiedLead, error: str | None = None) -> dict:
        record = to_salesforce_lead(item)
        entry = {
            "written_at": datetime.now(timezone.utc).isoformat(),
            "event_id": item.lead.event_id,
            "sobject": "Lead",
            "record": record,
        }
        if error:
            entry["error"] = error
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return {"action": self.action, "id": None, "path": str(self.path), **({"error": error} if error else {})}


class DeadLetterSink(DryRunSink):
    """Parks records that could not reach Salesforce so they can be replayed later."""

    action = "dead_letter"

    def __init__(self, reason: str | None = None, path: Path = OUT_DIR / "failed_writes.jsonl"):
        super().__init__(path)
        self.reason = reason

    def write(self, item: ClassifiedLead, error: str | None = None) -> dict:
        return super().write(item, error or self.reason)


class SalesforceSink:
    def __init__(self, sf=None):
        if sf is None:
            from simple_salesforce import Salesforce

            sf = Salesforce(
                username=os.environ["SF_USERNAME"],
                password=os.environ["SF_PASSWORD"],
                security_token=os.environ.get("SF_SECURITY_TOKEN", ""),
                domain=os.environ.get("SF_DOMAIN", "login"),
            )
        self.sf = sf

    def find_open_lead(self, email: str) -> str | None:
        from simple_salesforce import format_soql

        soql = format_soql(
            "SELECT Id FROM Lead WHERE Email = {} AND IsConverted = false "
            "ORDER BY CreatedDate DESC LIMIT 1",
            email,
        )
        records = self.sf.query(soql)["records"]
        return records[0]["Id"] if records else None

    def write(self, item: ClassifiedLead) -> dict:
        record = to_salesforce_lead(item)
        existing = self.find_open_lead(item.lead.email)
        if existing:
            self.sf.Lead.update(existing, record)
            return {"action": "updated", "id": existing}
        result = self.sf.Lead.create(record)
        return {"action": "created", "id": result["id"]}
