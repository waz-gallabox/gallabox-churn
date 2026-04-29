#!/usr/bin/env python3
"""
Gallabox Churn — Zoho CRM Full Sync
Syncs Lead Owner (from Accounts module) + KAM Owner (from KAM module)
into PocketBase accounts table.

Match key: Gallabox_Account_Id (CRM) -> amplitude_id (PocketBase)
Fallback:  Email match

Run:
  python3 sync_zoho_crm.py        # full sync
  python3 sync_zoho_crm.py --dry  # dry run, no writes
"""
import os, sys, json, time, urllib.request, urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from zoho_auth import get_token, zoho_crm_get
from config import PB_BASE, PB_EMAIL, PB_PASSWORD

DRY = "--dry" in sys.argv

# ── PocketBase ────────────────────────────────────────────────────────────────
_pb_token = None

def pb_auth():
    global _pb_token
    if _pb_token: return _pb_token
    body = json.dumps({"identity": PB_EMAIL, "password": PB_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/_superusers/auth-with-password",
        data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as r:
        _pb_token = json.loads(r.read())["token"]
    return _pb_token

def pb_get(path):
    req = urllib.request.Request(f"{PB_BASE}{path}",
        headers={"Authorization": f"Bearer {pb_auth()}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def pb_patch(pb_id, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/accounts/records/{pb_id}",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {pb_auth()}"},
        method="PATCH"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def pb_get_all_accounts():
    accounts = []
    page = 1
    while True:
        d = pb_get(f"/api/collections/accounts/records?perPage=500&page={page}&fields=id,email,amplitude_id,company")
        accounts.extend(d.get("items", []))
        if page >= d.get("totalPages", 1): break
        page += 1
    return accounts

# ── Fetch CRM pages ───────────────────────────────────────────────────────────
def fetch_crm_module(module, fields):
    records = []
    page = 1
    print(f"[crm] Fetching {module}...")
    while True:
        try:
            data = zoho_crm_get(f"{module}", {"per_page": 200, "page": page, "fields": fields})
        except Exception as e:
            if "400" in str(e):
                print(f"  Zoho API limit reached at page {page} (max 2000 records per module)")
            else:
                print(f"  Zoho CRM fetch error at page {page}: {e}")
            break
        batch = data.get("data", [])
        if not batch: break
        records.extend(batch)
        print(f"  {module}: {len(records)} records")
        if not data.get("info", {}).get("more_records", False): break
        page += 1
        time.sleep(0.2)
    return records

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\nGallabox Churn — Zoho CRM Sync {'(DRY RUN)' if DRY else ''}")
    print("=" * 55)

    # Load PB accounts
    print("[pb] Loading accounts...")
    pb_accounts = pb_get_all_accounts()
    print(f"[pb] {len(pb_accounts)} accounts loaded.")

    email_to_pb = {(a.get("email") or "").lower().strip(): a for a in pb_accounts}
    amp_to_pb   = {(a.get("amplitude_id") or "").lower().strip(): a
                   for a in pb_accounts if a.get("amplitude_id")}

    # ── 1. Lead Owner from Accounts module ────────────────────────────────────
    crm_accounts = fetch_crm_module("Accounts", "Account_Name,Owner,Email,Gallabox_Account_Id,Industry_1")
    print(f"[crm] {len(crm_accounts)} CRM Accounts fetched.")

    lead_owner_map = {}   # pb_id -> {lead_owner, lead_owner_email, crm_account_id}
    for rec in crm_accounts:
        owner  = rec.get("Owner") or {}
        gb_id  = (rec.get("Gallabox_Account_Id") or "").lower().strip()
        email  = (rec.get("Email") or "").lower().strip()
        pb     = amp_to_pb.get(gb_id) or email_to_pb.get(email)
        industry = (rec.get("Industry_1") or "").strip()
        if pb and owner.get("name"):
            lead_owner_map[pb["id"]] = {
                "lead_owner":        owner["name"],
                "lead_owner_email":  owner.get("email", ""),
                "crm_account_id":    rec.get("id", ""),
                "industry":          industry if industry.lower() not in ("not sure", "na", "n/a", "") else "",
            }

    print(f"[match] Lead Owner matched: {len(lead_owner_map)} accounts")

    # ── 2. KAM Owner from KAM module ──────────────────────────────────────────
    kam_records = fetch_crm_module("KAM", "Name,Owner,Email,Email_1,Gallabox_Account_Id,Account_Name,KAM_Status,Region,Segmentation,ICP_Non_ICP,Industry")
    print(f"[crm] {len(kam_records)} KAM records fetched.")

    kam_map = {}   # pb_id -> {kam, kam_email, kam_status, ...}
    for rec in kam_records:
        owner  = rec.get("Owner") or {}
        gb_id  = (rec.get("Gallabox_Account_Id") or "").lower().strip()
        # KAM module's Email_1 is usually the customer email
        email  = (rec.get("Email_1") or rec.get("Email") or "").lower().strip()
        pb     = amp_to_pb.get(gb_id) or email_to_pb.get(email)
        kam_industry = (rec.get("Industry") or "").strip()
        if pb and owner.get("name"):
            entry = {"kam": owner["name"], "kam_email": owner.get("email", "")}
            if kam_industry and kam_industry.lower() not in ("not sure","na","n/a",""):
                entry["industry"] = kam_industry
            kam_map[pb["id"]] = entry

    print(f"[match] KAM Owner matched: {len(kam_map)} accounts")

    # ── 3. Merge and write to PocketBase ──────────────────────────────────────
    all_pb_ids = set(list(lead_owner_map.keys()) + list(kam_map.keys()))
    updated = errors = 0

    for pb_id in all_pb_ids:
        patch = {}
        if pb_id in lead_owner_map:
            patch.update(lead_owner_map[pb_id])
        if pb_id in kam_map:
            patch.update(kam_map[pb_id])

        if DRY:
            acct = next((a for a in pb_accounts if a["id"] == pb_id), {})
            lo = patch.get("lead_owner", "—")
            km = patch.get("kam", "—")
            print(f"  DRY: {acct.get('company','?')[:35]:<35} | owner={lo:<25} | kam={km}")
            updated += 1
            continue

        try:
            pb_patch(pb_id, patch)
            updated += 1
        except Exception as e:
            print(f"  [warn] {pb_id}: {e}")
            errors += 1

    print(f"\nSync complete:")
    print(f"  CRM Accounts fetched     : {len(crm_accounts)}")
    print(f"  KAM records fetched      : {len(kam_records)}")
    print(f"  Lead Owner set           : {len(lead_owner_map)}")
    print(f"  KAM Owner set            : {len(kam_map)}")
    print(f"  PocketBase updated       : {updated}")
    print(f"  Errors                   : {errors}")

if __name__ == "__main__":
    main()
