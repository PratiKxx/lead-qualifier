# Ideal Customer Profile (ICP)

<!--
This file is owned by Sales Ops / RevOps, not engineering. Edit it to change how leads
are scored; no code change or redeploy of logic is needed. It is injected verbatim
into the classifier's system prompt.
-->

We sell **Ledgerline**, an accounts-payable automation platform (invoice capture,
3-way PO matching, approval workflows, ERP sync with NetSuite, SAP S/4HANA, and
Oracle).

## Strong fit (score 75-100, rating Hot)
- 200-5,000 employees (mid-market).
- Industries with high invoice volume and PO-based purchasing: Manufacturing,
  Healthcare, Retail, Transportation, Construction, Food & Beverage.
- Already on NetSuite, SAP, or Oracle, or mentions migrating to one.
- Contact is in Finance: Controller, AP Manager, VP Finance, CFO.
- Mentions a concrete pain: manual invoice entry, late-payment penalties, month-end
  close taking too long, duplicate payments, audit findings.

## Moderate fit (score 40-74, rating Warm)
- 50-199 employees, or over 5,000 (enterprise deals have a longer cycle).
- Fit industry but contact is outside Finance (IT, Operations, Procurement).
- Interest is real but vague ("exploring options", "budget next year").

## Weak fit (score 0-39, rating Cold)
- Under 50 employees.
- Students, job seekers, vendors pitching us, competitors, or personal email
  addresses with no company context.
- No AP process to automate (e.g. pure services firms with few suppliers).

## Rules
- Never invent facts. If employee count is missing, infer only from clear evidence
  and say so in the reasons; otherwise treat it as unknown.
- Set needs_human_review=true when the data is too thin or contradictory to score.
- Industry must be the single best match from the allowed list; use "Other" only as
  a last resort.
