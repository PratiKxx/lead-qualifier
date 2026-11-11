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
| `SF_CLIENT_ID` / `SF_CLIENT_SECRET` / `SF_DOMAIN` | Real Salesforce writes (OAuth) |

### Salesforce setup (OAuth client credentials, about 10 minutes)
Orgs created in Winter '26 or later disable username/password (SOAP) login by default,
and Salesforce retires it in Summer '27. This service uses OAuth 2.0 client credentials
instead, so no password goes in `.env`.

1. Sign up free at developer.salesforce.com/signup.
2. Setup → Quick Find **External Client App Manager** → **New External Client App**.
   Name it `Lead Qualifier`, Distribution State **Local**.
3. Under API (Enable OAuth Settings): tick **Enable OAuth**, callback URL
   `https://login.salesforce.com/services/oauth2/success` (required but unused), scope
   **Manage user data via APIs (api)**, tick **Enable Client Credentials Flow**. Create.
4. On the app's **Policies** tab → Edit → OAuth Policies: tick **Enable Client Credentials
   Flow** and set **Run As** to your own user. Save.
5. **Settings** tab → OAuth Settings → **Consumer Key and Secret** (you verify by email).
   Put them in `.env` as `SF_CLIENT_ID` / `SF_CLIENT_SECRET`.
6. Setup → **My Domain**: copy the current My Domain URL into `SF_DOMAIN`.
7. `python scripts/check_salesforce.py` (allow up to 10 minutes after creating the app).
8. Run the samples, then Leads tab → list view **All Open Leads**. Each lead shows
   Industry, Rating, and the AI qualification block in Description.

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
