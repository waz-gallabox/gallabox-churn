"""
Zoho Desk Integration for Gallabox Churn
------------------------------------
Fetches support tickets and extracts churn signals per account/customer.
Auto-refreshes OAuth token using stored refresh token.

Current scope: Desk.tickets.READ
  - Can fetch all tickets with status/priority filters
  - Can fetch individual ticket details
  - Client-side filtering by email/category

To enable email search, regenerate OAuth with scope:
  Desk.tickets.READ,Desk.search.READ,Desk.contacts.READ

Churn signals extracted:
  - Disconnection / Deactivation / Cancellation tickets
  - High ticket volume per account
  - Escalated tickets
  - MRR Impact custom field
  - Retention Status custom field
  - Overdue tickets
"""

import requests
import json
import os
import sys
import time
from typing import Optional

# Load credentials from project config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ZOHO_CLIENT_ID as CLIENT_ID, ZOHO_CLIENT_SECRET as CLIENT_SECRET, \
    ZOHO_REFRESH_TOKEN as REFRESH_TOKEN, ZOHO_DESK_ORG_ID as ORG_ID

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL    = "https://desk.zoho.in/api/v1"
TOKEN_URL   = "https://accounts.zoho.in/oauth/v2/token"
TOKEN_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".zoho_token.json")

CHURN_CATEGORIES = {"Disconnection", "Deactivation", "Cancellation", "Refund"}
CHURN_KEYWORDS   = ["deactivat", "cancel", "discontinue", "pause subscription",
                    "refund", "stop service", "exit", "closing account"]


# ── Token Management ──────────────────────────────────────────────────────────
def _load_cached_token() -> Optional[dict]:
    if os.path.exists(TOKEN_CACHE):
        with open(TOKEN_CACHE) as f:
            return json.load(f)
    return None


def _save_token(data: dict):
    data["fetched_at"] = time.time()
    with open(TOKEN_CACHE, "w") as f:
        json.dump(data, f, indent=2)


def get_access_token() -> str:
    cached = _load_cached_token()
    if cached:
        age = time.time() - cached.get("fetched_at", 0)
        if age < 3500:
            return cached["access_token"]

    print("[zoho_desk] Refreshing access token...")
    resp = requests.post(TOKEN_URL, params={
        "refresh_token": REFRESH_TOKEN,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type":    "refresh_token",
    })
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"Token refresh failed: {data}")
    _save_token(data)
    print(f"[zoho_desk] Token refreshed. Scope: {data.get('scope')}")
    return data["access_token"]


def _headers() -> dict:
    return {
        "Authorization": f"Zoho-oauthtoken {get_access_token()}",
        "orgId": ORG_ID,
        "Content-Type": "application/json",
    }


# ── Core API ──────────────────────────────────────────────────────────────────
def get_tickets(limit=50, from_index=0, status=None, priority=None) -> list:
    """
    Fetch tickets. Supported filters with Desk.tickets.READ:
      status   = Open | Closed | Resolved | On Hold | Pending
      priority = Low | Medium | High | Urgent
    """
    params = {"limit": min(limit, 100), "from": from_index, "sortBy": "-createdTime"}
    if status:
        params["status"] = status
    if priority:
        params["priority"] = priority

    resp = requests.get(f"{BASE_URL}/tickets", headers=_headers(), params=params)
    resp.raise_for_status()
    return resp.json().get("data", [])


def get_ticket_detail(ticket_id: str) -> dict:
    resp = requests.get(f"{BASE_URL}/tickets/{ticket_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_all_tickets_paginated(max_tickets=1000) -> list:
    """Paginate through all tickets (used for batch churn analysis)."""
    all_tickets = []
    batch = 100
    from_index = 0
    while len(all_tickets) < max_tickets:
        page = get_tickets(limit=batch, from_index=from_index)
        if not page:
            break
        all_tickets.extend(page)
        from_index += batch
        if len(page) < batch:
            break
    return all_tickets


def search_tickets_by_email(email: str, all_tickets: list = None) -> list:
    """
    Find all tickets for a given email.
    Requires Desk.search.READ for API-side search.
    Falls back to client-side filter if all_tickets provided.
    """
    # Try API search first (needs Desk.search.READ scope)
    try:
        resp = requests.get(f"{BASE_URL}/tickets/search", headers=_headers(), params={
            "limit": 50, "from": 0, "email": email
        })
        if resp.status_code == 200:
            return resp.json().get("data", [])
    except Exception:
        pass

    # Fall back: client-side filter
    if all_tickets is not None:
        return [t for t in all_tickets if (t.get("email") or "").lower() == email.lower()]

    # Last resort: fetch recent tickets and filter
    tickets = get_tickets(limit=100)
    return [t for t in tickets if (t.get("email") or "").lower() == email.lower()]


# ── Churn Signal Extraction ───────────────────────────────────────────────────
def is_churn_ticket(ticket: dict) -> bool:
    category = (ticket.get("category") or "").strip()
    subject  = (ticket.get("subject") or "").lower()
    if category in CHURN_CATEGORIES:
        return True
    if any(kw in subject for kw in CHURN_KEYWORDS):
        return True
    return False


def extract_churn_signals(ticket: dict) -> dict:
    cf = ticket.get("cf") or ticket.get("customFields") or {}
    return {
        "ticket_id":        ticket.get("id"),
        "ticket_number":    ticket.get("ticketNumber"),
        "email":            ticket.get("email"),
        "business_name":    cf.get("cf_business_name_84000530805") or cf.get("Business Name"),
        "subject":          ticket.get("subject"),
        "status":           ticket.get("status"),
        "status_type":      ticket.get("statusType"),
        "category":         ticket.get("category"),
        "sub_category":     ticket.get("subCategory"),
        "priority":         ticket.get("priority"),
        "is_escalated":     ticket.get("isEscalated", False),
        "is_overdue":       ticket.get("isOverDue", False),
        "is_churn_ticket":  is_churn_ticket(ticket),
        "mrr_impact":       cf.get("cf_mrr_impact") or cf.get("MRR_Impact"),
        "retention_status": cf.get("cf_retention_status") or cf.get("Retention Status"),
        "client_success":   cf.get("cf_client_success_84000482140") or cf.get("Client Success"),
        "thread_count":     int(ticket.get("threadCount") or 0),
        "comment_count":    int(ticket.get("commentCount") or 0),
        "sentiment":        ticket.get("sentiment"),
        "created_time":     ticket.get("createdTime"),
        "closed_time":      ticket.get("closedTime"),
        "web_url":          ticket.get("webUrl"),
    }


def get_churn_signals_for_email(email: str, all_tickets: list = None) -> dict:
    """
    Core Gallabox Churn function: given a customer email,
    returns a structured churn risk profile from their support history.
    """
    tickets = search_tickets_by_email(email, all_tickets)
    if not tickets:
        return {
            "email": email,
            "ticket_count": 0,
            "risk_score": 0,
            "risk_reasons": [],
            "churn_tickets": [],
        }

    signals       = [extract_churn_signals(t) for t in tickets]
    churn_tickets = [s for s in signals if s["is_churn_ticket"]]
    escalated     = [s for s in signals if s["is_escalated"]]
    overdue       = [s for s in signals if s["is_overdue"]]
    open_tickets  = [s for s in signals if s["status_type"] == "Open"]

    risk_score   = 0
    risk_reasons = []

    if churn_tickets:
        risk_score += 50
        risk_reasons.append(f"{len(churn_tickets)} churn/disconnection ticket(s)")
    if escalated:
        risk_score += 20
        risk_reasons.append(f"{len(escalated)} escalated ticket(s)")
    if overdue:
        risk_score += 10
        risk_reasons.append(f"{len(overdue)} overdue ticket(s)")
    if len(tickets) > 10:
        risk_score += 10
        risk_reasons.append(f"High support volume ({len(tickets)} tickets)")
    if open_tickets:
        risk_score += 10
        risk_reasons.append(f"{len(open_tickets)} currently open ticket(s)")

    return {
        "email":           email,
        "ticket_count":    len(tickets),
        "churn_tickets":   churn_tickets,
        "escalated_count": len(escalated),
        "overdue_count":   len(overdue),
        "open_count":      len(open_tickets),
        "risk_score":      min(risk_score, 100),
        "risk_reasons":    risk_reasons,
        "all_signals":     signals,
    }


def batch_churn_report(max_tickets=500) -> list:
    """
    Fetch recent tickets, identify all churn signals,
    group by email/business, return ranked churn risk list.
    """
    print(f"[zoho_desk] Fetching up to {max_tickets} tickets for batch analysis...")
    all_tickets = get_all_tickets_paginated(max_tickets)
    print(f"[zoho_desk] Fetched {len(all_tickets)} tickets.")

    # Group by email
    by_email = {}
    for t in all_tickets:
        email = (t.get("email") or "unknown").lower()
        by_email.setdefault(email, []).append(t)

    results = []
    for email, tickets in by_email.items():
        signals       = [extract_churn_signals(t) for t in tickets]
        churn_tickets = [s for s in signals if s["is_churn_ticket"]]
        if not churn_tickets:
            continue

        escalated    = [s for s in signals if s["is_escalated"]]
        risk_score   = min(50 + len(escalated) * 20, 100)
        business     = churn_tickets[0].get("business_name") or email

        results.append({
            "email":          email,
            "business_name":  business,
            "churn_tickets":  len(churn_tickets),
            "total_tickets":  len(tickets),
            "escalated":      len(escalated),
            "risk_score":     risk_score,
            "latest_subject": churn_tickets[0]["subject"],
            "latest_date":    churn_tickets[0]["created_time"],
            "web_url":        churn_tickets[0]["web_url"],
        })

    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        max_t = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        report = batch_churn_report(max_t)
        print(f"\nGallabox Churn — Top {len(report)} at-risk accounts from Zoho Desk\n")
        print(f"{'#':<4} {'Email':<35} {'Business':<25} {'Churn Tickets':<15} {'Risk Score'}")
        print("-" * 95)
        for i, r in enumerate(report[:20], 1):
            print(f"{i:<4} {r['email'][:34]:<35} {str(r['business_name'])[:24]:<25} {r['churn_tickets']:<15} {r['risk_score']}/100")

    elif len(sys.argv) > 1:
        email = sys.argv[1]
        print(f"\nGallabox Churn — Zoho Desk signals for: {email}\n")
        result = get_churn_signals_for_email(email)
        print(json.dumps(result, indent=2))

    else:
        print("Fetching latest churn tickets...\n")
        tickets = get_tickets(limit=50)
        churn = [t for t in tickets if is_churn_ticket(t)]
        print(f"Found {len(churn)} churn tickets out of {len(tickets)} recent tickets:\n")
        for t in churn:
            s = extract_churn_signals(t)
            print(f"  #{s['ticket_number']} | {s['email']} | {s['category']} | {s['subject'][:50]}")
        if not churn:
            print("No churn tickets in latest 50. Try: python3 zoho_desk.py batch")
