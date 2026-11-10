# Lead Qualifier

A webhook service that takes a new inbound lead, has Claude classify its **industry**
and **fit** against an Ideal Customer Profile, and creates or updates the Lead in
**Salesforce**, so SDRs open a lead that is already scored and explained.

```
Web form / HubSpot / Typeform
          │  POST /webhooks/lead  (HMAC-signed JSON)
          ▼
 ┌─────────────────────┐   verify signature → validate payload → idempotency check
 │  FastAPI webhook    │
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   Claude (schema-constrained output, ICP in system prompt)
 │  ResilientClassifier│── on error/refusal ──► deterministic rules engine + review flag
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   find open Lead by Email → update, else create
 │  Salesforce sink    │   (or DRY_RUN → out/leads.jsonl)
 └─────────────────────┘
```

## What lands in Salesforce

| Field | Example |
|---|---|
| Industry | `Manufacturing` (always a valid standard picklist value) |
| Rating | `Hot` |
| Description | `Fit score: 88/100 (Hot) via claude` · reasons · next action · review flag · original message |

Requirements, acceptance criteria, and field mapping: [docs/requirements.md](docs/requirements.md).

## Design decisions

- **Structured output, not free text.** The model must return a Pydantic schema
  (`LeadClassification`). Industry is an enum of Salesforce's *standard* Lead picklist
  values, so a write can't fail on an invalid picklist value and the org needs no setup.
- **The ICP lives in a markdown file** ([config/icp.md](config/icp.md)) that RevOps can
  edit. Changing who counts as a good lead needs no code change.
- **Never drop a lead.** If the API errors or the model refuses, a rules engine scores
  the lead and sets `needs_human_review`. The rules engine also runs the whole demo
  with no API key.
- **Webhook hygiene.** HMAC-SHA256 signatures, 422 on bad payloads, and idempotency on
  `event_id`, because senders retry on timeouts and you don't want two Leads.
- **Prompt-injection guard.** Lead text is user input. The system prompt tells the
  model to ignore instructions inside it, and `samples/injection_attempt.json` tests it.
- **Dedupe on Email** against unconverted Leads, with SOQL parameters escaped.

## Run it

```bash
python -m venv .venv
.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in what you have; blanks fall back to dry-run / rules
pytest                        # 14 tests, no network needed
uvicorn app.main:app --reload
python scripts/send_sample.py # posts every file in samples/ with a valid signature
```

| You set | Behavior |
|---|---|
| nothing | Rules classifier, records written to `out/leads.jsonl` |
| `ANTHROPIC_API_KEY` | Claude classifies, rules are the fallback |
| `SF_USERNAME` / `SF_PASSWORD` / `SF_SECURITY_TOKEN` | Real Salesforce writes |

### Salesforce Developer org setup (5 minutes)
1. Sign up free at developer.salesforce.com/signup.
2. Avatar → Settings → **Reset My Security Token**; the token is emailed.
3. Put username, password, and token in `.env`. No custom fields are needed.
4. Run the samples, then open the **Leads** tab. Each lead shows Industry, Rating,
   and the AI qualification block in Description.

## Sample results (rules mode)

```
hot_manufacturing.json   Manufacturing  score=100 Hot   review=False
warm_healthcare_it.json  Healthcare     score= 55 Warm  review=False
cold_student.json        Education      score=  0 Cold  review=True
injection_attempt.json   Retail         score= 30 Cold  review=False
```

## Built with Claude Code
Built in one working session with Claude Code as the AI pair programmer, working
requirements-first: problem statement, acceptance criteria and field mapping in
`docs/requirements.md`, then the service, then tests named after each AC id so every
requirement traces to a passing test. Claude Code wrote the code and tests and ran the
end-to-end check against a live local server.

## Next steps
- Assignment rule that routes `needs_human_review` leads to a queue
- Slack alert on Hot leads
- `Fit_Score__c` custom field for list views sorted by score
- Compare Claude's ratings with closed-won outcomes to tune the ICP
