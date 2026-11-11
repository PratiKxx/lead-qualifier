"""Try the Salesforce login from .env exactly once and explain the result.

Usage: python scripts/check_salesforce.py
Each failed attempt counts toward Salesforce's lockout limit (about 10), so this
never retries.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceAuthenticationFailed

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

missing = [k for k in ("SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN") if not os.environ.get(k)]
if missing:
    sys.exit(f"Missing in .env: {', '.join(missing)}")

domain = os.environ.get("SF_DOMAIN", "login")
print(f"Logging in as {os.environ['SF_USERNAME']} via {domain}.salesforce.com ...")
try:
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
        domain=domain,
    )
except SalesforceAuthenticationFailed as exc:
    print(f"\nFAILED: {exc}\n")
    print("Most common causes, in order:")
    print("  1. SF_USERNAME is your login email, not your Salesforce username.")
    print("     Check: avatar > Settings > Personal Information > Username.")
    print("  2. The security token is stale. Changing your password invalidates it.")
    print("     Avatar > Settings > Reset My Security Token, use the NEWEST email.")
    print("  3. Password typo. Log in at login.salesforce.com with the same values to confirm.")
    print("  4. Locked out after repeated failures: wait 15 minutes or reset your password.")
    print("  5. If the error mentions SOAP/API login being disabled, the org blocks this")
    print("     login method; switch to OAuth (Connected App / External Client App).")
    sys.exit(1)

total = sf.query("SELECT COUNT() FROM Lead")["totalSize"]
print(f"\nOK: connected to {sf.sf_instance}. The org has {total} Lead(s).")
