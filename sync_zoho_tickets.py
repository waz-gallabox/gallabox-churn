#!/usr/bin/env python3
"""
Gallabox Churn — Zoho Desk Ticket Sync
Fetches all tickets from Zoho Desk, matches them to active accounts by email,
and upserts into PocketBase zoho_tickets collection.

Run:
  python3 sync_zoho_tickets.py           # full sync (latest 2000 tickets)
  python3 sync_zoho_tickets.py --quick   # latest 200 tickets only
"""

import json
import sys
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD, ZOHO_DESK_ORG_ID, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN

ZOHO_ORG_ID   = ZOHO_DESK_ORG_ID
ZOHO_BASE     = "https://desk.zoho.in/api/v1"
ZOHO_TOKEN_URL = "https://accounts.zoho.in/oauth/v2/token"
TOKEN_CACHE        = "/tmp/gallabox_churn_zoho_token.json"

CHURN_CATEGORIES = {"Disconnection", "Deactivation", "Cancellation", "Refund"}
CHURN_KEYWORDS   = ["deactivat", "cancel", "discontinue", "pause subscription",
                    "refund", "stop service", "closing account", "subscription cancelled"]

QUICK_MODE = "--quick" in sys.argv
MAX_TICKETS = 200 if QUICK_MODE else 2000

# ── Zoho Auth ─────────────────────────────────────────────────────────────────
def get_zoho_token() -> str:
    try:
        with open(TOKEN_CACHE) as f:
            cached = json.load(f)
        if time.time() - cached.get("fetched_at", 0) < 3500:
            return cached["access_token"]
    except Exception:
        pass

    print("[zoho] Refreshing token...")
    params = urllib.parse.urlencode({
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id":     ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type":    "refresh_token",
    })
    req = urllib.request.Request(f"{ZOHO_TOKEN_URL}?{params}", method="POST")
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    if "access_token" not in data:
        raise ValueError(f"Token refresh failed: {data}")
    data["fetched_at"] = time.time()
    with open(TOKEN_CACHE, "w") as f:
        json.dump(data, f)
    print(f"[zoho] Token refreshed. Scope: {data.get('scope')}")
    return data["access_token"]


def zoho_get(path: str, params: dict = None) -> dict:
    token = get_zoho_token()
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request(
        f"{ZOHO_BASE}/{path}{qs}",
        headers={
            "Authorization": f"Zoho-oauthtoken {token}",
            "orgId": ZOHO_ORG_ID,
        }
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


# ── PocketBase ────────────────────────────────────────────────────────────────
_pb_token = None

def pb_auth() -> str:
    global _pb_token
    if _pb_token:
        return _pb_token
    body = json.dumps({"identity": PB_EMAIL, "password": PB_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/_superusers/auth-with-password",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            _pb_token = json.loads(r.read())["token"]
    except urllib.error.HTTPError as e:
        raise ValueError(f"PocketBase auth failed: {e.read().decode()}")
    return _pb_token


def pb_request(method: str, path: str, data: dict = None):
    token = pb_auth()
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    req = urllib.request.Request(f"{PB_BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()


def get_all_active_accounts() -> dict:
    """Returns {email.lower(): pb_account_id} for all active accounts."""
    email_to_id = {}
    page = 1
    per_page = 500
    while True:
        path = f"/api/collections/accounts/records?filter=status%3D%22active%22&perPage={per_page}&page={page}&fields=id,email"
        res, err = pb_request("GET", path)
        if err or not res:
            break
        for item in res.get("items", []):
            email = (item.get("email") or "").lower().strip()
            if email:
                email_to_id[email] = item["id"]
        if page >= res.get("totalPages", 1):
            break
        page += 1
    return email_to_id


def get_existing_ticket_ids() -> set:
    """Returns set of ticket_ids already in PocketBase."""
    ticket_ids = set()
    page = 1
    while True:
        path = f"/api/collections/zoho_tickets/records?perPage=500&page={page}&fields=ticket_id"
        res, _ = pb_request("GET", path)
        if not res:
            break
        for item in res.get("items", []):
            ticket_ids.add(item.get("ticket_id", ""))
        if page >= res.get("totalPages", 1):
            break
        page += 1
    return ticket_ids


def get_pb_record_id_by_ticket(ticket_id: str):
    """Find PocketBase record id for a given zoho ticket_id."""
    encoded = urllib.parse.quote(f'ticket_id="{ticket_id}"')
    path = f"/api/collections/zoho_tickets/records?filter={encoded}&perPage=1&fields=id"
    res, _ = pb_request("GET", path)
    items = res.get("items", []) if res else []
    return items[0]["id"] if items else None


# ── Churn Detection ───────────────────────────────────────────────────────────
def is_churn_ticket(ticket: dict) -> bool:
    category = (ticket.get("category") or "").strip()
    subject  = (ticket.get("subject") or "").lower()
    if category in CHURN_CATEGORIES:
        return True
    return any(kw in subject for kw in CHURN_KEYWORDS)


# ── Fetch Zoho Tickets ────────────────────────────────────────────────────────
def fetch_all_tickets(max_tickets: int) -> list:
    tickets = []
    batch = 100
    from_idx = 0
    print(f"[zoho] Fetching up to {max_tickets} tickets...")
    while len(tickets) < max_tickets:
        data = zoho_get("tickets", {"limit": batch, "from": from_idx, "sortBy": "-createdTime"})
        page = data.get("data", [])
        if not page:
            break
        tickets.extend(page)
        print(f"  fetched {len(tickets)} tickets so far...")
        from_idx += batch
        if len(page) < batch:
            break
        time.sleep(0.3)  # be gentle with Zoho rate limits
    return tickets


# ── Main Sync ─────────────────────────────────────────────────────────────────
def main():
    print(f"\nGallabox Churn Zoho Desk Sync — {'QUICK' if QUICK_MODE else 'FULL'} mode")
    print("=" * 50)

    # 1. Load active accounts
    print("[pb] Loading active accounts...")
    email_to_id = get_all_active_accounts()
    print(f"[pb] {len(email_to_id)} active accounts loaded.")

    # 2. Fetch Zoho tickets
    tickets = fetch_all_tickets(MAX_TICKETS)
    print(f"[zoho] {len(tickets)} tickets fetched total.")

    # 3. Match + sync
    synced_at = datetime.now(timezone.utc).isoformat()
    matched = 0
    upserted = 0
    skipped = 0

    for t in tickets:
        email = (t.get("email") or "").lower().strip()
        account_id = email_to_id.get(email)
        if not account_id:
            skipped += 1
            continue

        matched += 1
        ticket_id = t.get("id", "")

        record = {
            "account_id":     account_id,
            "ticket_id":      ticket_id,
            "ticket_number":  t.get("ticketNumber", ""),
            "subject":        t.get("subject", ""),
            "status":         t.get("status", ""),
            "status_type":    t.get("statusType", ""),
            "category":       t.get("category") or "",
            "sub_category":   t.get("subCategory") or "",
            "priority":       t.get("priority") or "",
            "is_escalated":   bool(t.get("isEscalated", False)),
            "is_overdue":     bool(t.get("isOverDue", False)),
            "is_churn_ticket": is_churn_ticket(t),
            "thread_count":   int(t.get("threadCount") or 0),
            "created_time":   t.get("createdTime") or "",
            "closed_time":    t.get("closedTime") or "",
            "web_url":        t.get("webUrl") or "",
            "synced_at":      synced_at,
        }

        # Try create first; if 400 (duplicate unique key), fetch id and patch
        res, err = pb_request("POST", "/api/collections/zoho_tickets/records", record)
        if err:
            # Could be duplicate — try to find and patch
            pb_id = get_pb_record_id_by_ticket(ticket_id)
            if pb_id:
                res, err = pb_request("PATCH", f"/api/collections/zoho_tickets/records/{pb_id}", record)
            if err:
                print(f"  [warn] ticket {ticket_id}: {err[:120]}")
                continue
        upserted += 1

    print(f"\nSync complete:")
    print(f"  Total tickets fetched : {len(tickets)}")
    print(f"  Matched to accounts   : {matched}")
    print(f"  Upserted to PocketBase: {upserted}")
    print(f"  Skipped (no match)    : {skipped}")


if __name__ == "__main__":
    main()
