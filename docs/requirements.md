# Requirements: Inbound Lead Qualification

## Problem
Inbound leads from web forms land in Salesforce unqualified. SDRs open every one by
hand to decide industry and fit, so hot leads wait hours for a first touch while
students and vendors take up the same attention.

## Goal
Every inbound lead arrives in Salesforce **already tagged** with Industry, a 0-100 fit
score, a Hot/Warm/Cold rating, the reasons behind the score, and a next action,
within seconds of form submission.

## Scope
**In:** webhook intake, LLM classification against an editable ICP, rules fallback,
create-or-update of the Salesforce Lead, idempotency, signature verification.
**Out (later):** lead assignment rules, Slack alerts for Hot leads, enrichment
(Clearbit/ZoomInfo), a feedback loop from closed-won data back into the ICP.

## Stakeholders
| Role | Need |
|---|---|
| SDR / AE | Know which leads to call first and why |
| Sales Ops / RevOps | Change scoring criteria without an engineering ticket |
| Marketing | Lead source and quality reporting |
| Salesforce admin | No new custom fields or picklist values required to go live |

## User stories and acceptance criteria
Test names in `tests/test_pipeline.py` carry the AC id, which gives traceability.

| ID | Story | Acceptance criteria | Tests |
|---|---|---|---|
| AC-1 | As an SDR I get a consistent, explained score | Classifier output is validated against a fixed schema; Industry is restricted to Salesforce's standard picklist; lead text is treated as untrusted (prompt-injection guard) | `test_ac1_*` |
| AC-2 | As Sales Ops I never lose a lead to an AI outage | If the LLM errors or refuses, the rules engine scores the lead and it is flagged `needs_human_review` | `test_ac2_*` |
| AC-3 | As Sales Ops I have a deterministic baseline | Rules engine rates the reference samples Hot / Warm / Cold as expected; personal email domains are flagged | `test_ac3_*` |
| AC-4 | As a SF admin I need zero org changes | Only standard Lead fields; score, reasons and next action go into Description | `test_ac4_*` |
| AC-5 | As an SDR I don't want duplicate leads | Match on Email against open (unconverted) Leads; update if found, else create; SOQL input is escaped | `test_ac5_*` |
| AC-6 | As security I only accept genuine webhooks | HMAC-SHA256 signature required when a secret is set; malformed payloads get 422 | `test_ac6_*` |
| AC-7 | As ops I can rely on sender retries | Re-delivery of the same `event_id` returns the first result and writes nothing new | `test_ac7_*` |

## Field mapping
| Webhook field | Salesforce Lead field | Notes |
|---|---|---|
| first_name / last_name | FirstName / LastName | LastName required by SF |
| email | Email | Dedupe key |
| company | Company | Required by SF |
| title, website, country | Title, Website, Country | |
| employee_count | NumberOfEmployees | |
| source | LeadSource | |
| *(classifier)* industry | Industry | Standard picklist value |
| *(classifier)* rating | Rating | Hot / Warm / Cold |
| *(classifier)* score, reasons, next action, review flag | Description | Prefixed `--- AI qualification ---` |

## Open questions / decisions
- **Dedupe key.** Email is simple but misses the same person on two addresses. Revisit
  with a matching rule if duplicates show up in UAT.
- **Custom fields.** A `Fit_Score__c` number field would allow list views sorted by
  score. Deferred so the first release needs no admin work.
- **Human review queue.** Leads flagged `needs_human_review` should go to a queue via
  an assignment rule. Needs RevOps sign-off on queue ownership.
