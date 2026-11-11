"""Try the Salesforce connection from .env exactly once and explain the result.

Usage: python scripts/check_salesforce.py
Never retries: failed password logins count toward Salesforce's lockout limit.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from simple_salesforce.exceptions import SalesforceAuthenticationFailed  # noqa: E402

from app.salesforce import connect, my_domain  # noqa: E402

load_dotenv(ROOT / ".env")

oauth = bool(os.environ.get("SF_CLIENT_ID"))
if oauth:
    missing = [k for k in ("SF_CLIENT_SECRET", "SF_DOMAIN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    if my_domain(os.environ["SF_DOMAIN"]) in ("login", "test"):
        sys.exit("SF_DOMAIN must be your My Domain (Setup > My Domain), not 'login', for OAuth.")
    print(f"OAuth client credentials against {my_domain(os.environ['SF_DOMAIN'])}.salesforce.com ...")
else:
    print(f"Legacy password login as {os.environ.get('SF_USERNAME')} ...")

try:
    sf = connect()
except SalesforceAuthenticationFailed as exc:
    print(f"\nFAILED: {exc}\n")
    if oauth:
        print("Check, in order:")
        print("  1. External Client App > Policies: 'Enable Client Credentials Flow' is on")
        print("     and 'Run As' is set to your user.")
        print("  2. OAuth scope includes 'Manage user data via APIs (api)'.")
        print("  3. Client ID/secret copied fully; SF_DOMAIN is your My Domain.")
        print("  4. New apps can take up to 10 minutes to start working.")
    else:
        print("Orgs created in Winter '26+ disable password (SOAP) login by default.")
        print("Use OAuth instead: see 'Salesforce setup' in the README.")
    sys.exit(1)
except KeyError as exc:
    sys.exit(f"Missing in .env: {exc}")

total = sf.query("SELECT COUNT() FROM Lead")["totalSize"]
print(f"\nOK: connected to {sf.sf_instance}. The org has {total} Lead(s).")
