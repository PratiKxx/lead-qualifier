"""Post sample payloads to the running webhook, signing them like a real sender would.

Usage: python scripts/send_sample.py [samples/*.json ...] [--url http://localhost:8000]
"""
import argparse
import glob
import hashlib
import hmac
import json
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("files", nargs="*", default=sorted(glob.glob("samples/*.json")))
parser.add_argument("--url", default="http://localhost:8000/webhooks/lead")
args = parser.parse_args()

secret = os.environ.get("WEBHOOK_SECRET")
for path in args.files:
    body = open(path, "rb").read()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    r = httpx.post(args.url, content=body, headers=headers, timeout=120)
    if r.status_code != 200:
        print(f"{path}: HTTP {r.status_code} {r.text}", file=sys.stderr)
        continue
    d = r.json()
    c = d["classification"]
    print(f"{path}\n  {c['industry']:<16} score={c['fit_score']:>3} {c['rating']:<5} "
          f"review={c['needs_human_review']} via={d['classifier']} sf={d['salesforce']['action']}")
    for reason in c["reasons"]:
        print(f"    - {reason}")
