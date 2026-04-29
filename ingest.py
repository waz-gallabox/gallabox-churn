
#!/usr/bin/env python3
"""
Gallabox Churn Ingestion Pipeline
Pulls data from Chargebee + Amplitude -> PocketBase
"""

import json, urllib.request, urllib.parse, base64, subprocess, time, os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD, CB_SITE, CB_KEY

# ── Config ────────────────────────────────────────────────────────────────────
CB_CREDS = base64.b64encode(f"{CB_KEY}:".encode()).decode()

# ── Helpers ───────────────────────────────────────────────────────────────────
def pb_auth():
    res = pb_post_raw("/api/collections/_superusers/auth-with-password",
                      {"identity": PB_EMAIL, "password": PB_PASSWORD}, token=None)
    return res["token"]

def pb_post_raw(path, data, token):
    body = json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{PB_BASE}{path}", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def pb_request(method, path, data=None, token=None):
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{PB_BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

def cb_get(path):
    url = f"https://{CB_SITE}/api/v2/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {CB_CREDS}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def composio_run(tool, data):
    cmd = f"composio tools execute {tool} -d '{json.dumps(data)}' 2>/dev/null"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except:
        return {}

# ── Step 1: Fetch all Chargebee customers ─────────────────────────────────────
def fetch_chargebee_customers():
    print("Fetching Chargebee customers...")
    all_customers = []
    offset = None
    page = 0
    while True:
        path = "customers?limit=100"
        if offset:
            path += f"&offset={urllib.parse.quote(str(offset))}"
        data = cb_get(path)
        batch = [x["customer"] for x in data.get("list", [])]
        all_customers.extend(batch)
        page += 1
        print(f"  Page {page}: {len(batch)} customers (total: {len(all_customers)})")
        next_offset = data.get("next_offset")
        if not next_offset:
            break
        offset = next_offset
    print(f"  Total: {len(all_customers)} customers")
    return all_customers

# ── Step 2: Fetch active subscriptions ───────────────────────────────────────
def fetch_subscriptions():
    print("Fetching subscriptions...")
    subs = {}
    offset = None
    while True:
        path = "subscriptions?limit=100&status[is_not]=cancelled"
        if offset:
            path += f"&offset={urllib.parse.quote(str(offset))}"
        data = cb_get(path)
        for item in data.get("list", []):
            s = item["subscription"]
            cid = s.get("customer_id")
            if cid not in subs:
                items_list = s.get("subscription_items", [])
                plan = items_list[0].get("item_price_id", "N/A") if items_list else "N/A"
                subs[cid] = {
                    "plan": plan,
                    "status": s.get("status"),
                    "mrr": s.get("mrr", 0),
                    "currency": s.get("currency_code", ""),
                }
        next_offset = data.get("next_offset")
        if not next_offset:
            break
        offset = next_offset
    print(f"  Total unique subscriptions: {len(subs)}")
    return subs

# ── Step 3: Fetch Amplitude session data ──────────────────────────────────────
def fetch_amplitude_sessions():
    print("Fetching Amplitude session data...")
    today = datetime.now()
    end   = today.strftime("%Y%m%d")
    start = (today - timedelta(days=14)).strftime("%Y%m%d")

    result = composio_run("AMPLITUDE_GET_EVENT_SEGMENTATION", {
        "e": json.dumps({"event_type": "session_start"}),
        "start": start,
        "end": end,
        "m": "totals",
        "g": "user_id",
        "i": "7"
    })

    sessions_map = {}  # amplitude_id -> {current, previous, wow_delta}
    if result.get("successful"):
        data = result["data"]["data"]["data"]
        labels  = data.get("seriesLabels", [])
        series  = data.get("series", [])
        xvalues = data.get("xValues", [])

        for label, s in zip(labels, series):
            if not label or label == 0:
                continue
            uid = str(label)
            current  = s[1] if len(s) > 1 else s[0]
            previous = s[0] if len(s) > 0 else 0
            wow = ((current - previous) / previous * 100) if previous > 0 else 0
            sessions_map[uid] = {
                "current":  current,
                "previous": previous,
                "wow_delta": round(wow, 2),
                "period_start": xvalues[1] if len(xvalues) > 1 else "",
                "period_end":   end,
            }
        print(f"  Got session data for {len(sessions_map)} accounts")
    else:
        print(f"  Warning: {result.get('error', 'Unknown error')}")
    return sessions_map

# ── Step 4: Compute churn + upsell scores ─────────────────────────────────────
def compute_scores(account, sub, sessions):
    mrr       = sub.get("mrr", 0) / 100
    status    = sub.get("status", "active")
    wow_delta = sessions.get("wow_delta", 0)
    current   = sessions.get("current", 0)
    previous  = sessions.get("previous", 0)
    plan      = sub.get("plan", "")

    # Churn score (0-100, higher = more likely to churn)
    churn = 0

    # No sessions this week
    if current == 0 and previous > 0:
        churn += 40
    elif current == 0 and previous == 0:
        churn += 30

    # Session drop
    if wow_delta < -50:
        churn += 30
    elif wow_delta < -30:
        churn += 20
    elif wow_delta < -10:
        churn += 10

    # Low/no MRR (free tier more likely to churn)
    if mrr == 0:
        churn += 15
    elif mrr < 1000:
        churn += 5

    # Non-active subscription
    if status in ["cancelled", "paused"]:
        churn += 30
    elif status == "non_renewing":
        churn += 20

    churn = min(churn, 100)

    # Upsell score (0-100, higher = more ready to upgrade)
    upsell = 0

    # High session count
    if current > 500:
        upsell += 35
    elif current > 200:
        upsell += 25
    elif current > 100:
        upsell += 15

    # Session growth
    if wow_delta > 20:
        upsell += 20
    elif wow_delta > 10:
        upsell += 10

    # Low plan relative to usage
    free_indicators = ["free", "trial", "zone"]
    if any(f in plan.lower() for f in free_indicators) and current > 100:
        upsell += 25

    # Low MRR with high usage
    if mrr < 500 and current > 200:
        upsell += 20

    upsell = min(upsell, 100)

    # Health badge
    if churn >= 60:
        health = "red"
    elif churn >= 30 or wow_delta < -20:
        health = "yellow"
    else:
        health = "green"

    # AI explanation
    plan_short = plan.replace("-", " ")[:40]
    if health == "red":
        explanation = (
            f"High churn risk. Sessions this week: {current} "
            f"({'down ' + str(abs(int(wow_delta))) + '%' if wow_delta < 0 else 'no history'}). "
            f"On {plan_short} at ${mrr:.0f}/mo MRR. "
            f"Recommend: CSM outreach within 48 hours."
        )
    elif health == "yellow":
        explanation = (
            f"Watch this account. Sessions dropped {abs(int(wow_delta))}% WoW "
            f"({previous} -> {current}). "
            f"On {plan_short}. "
            f"Recommend: check in with a product tip or use-case nudge."
        )
    else:
        explanation = (
            f"Healthy account. {current} sessions this week "
            f"({'up ' + str(int(wow_delta)) + '%' if wow_delta > 0 else 'stable'}). "
            f"On {plan_short} at ${mrr:.0f}/mo. "
            + (f"Good upsell candidate — consider upgrade conversation." if upsell > 50 else "Keep nurturing.")
        )

    return {
        "churn_score":  round(churn, 1),
        "upsell_score": round(upsell, 1),
        "health":       health,
        "explanation":  explanation,
        "sessions_7d":  current,
        "wow_delta":    wow_delta,
    }

# ── Step 5: Write to PocketBase ───────────────────────────────────────────────
def upsert_account(token, chargebee_id, record):
    # Check if exists
    encoded = urllib.parse.quote(f'chargebee_id="{chargebee_id}"')
    res, err = pb_request("GET", f"/api/collections/accounts/records?filter={encoded}", token=token)
    if res and res.get("items"):
        pb_id = res["items"][0]["id"]
        pb_request("PATCH", f"/api/collections/accounts/records/{pb_id}", record, token)
        return pb_id
    else:
        res2, err2 = pb_request("POST", "/api/collections/accounts/records", record, token)
        if res2:
            return res2["id"]
    return None

def write_session_snapshot(token, pb_account_id, snap):
    data = {
        "account_id":    pb_account_id,
        "period_start":  snap.get("period_start", ""),
        "period_end":    snap.get("period_end", ""),
        "sessions":      snap.get("current", 0),
        "prev_sessions": snap.get("previous", 0),
        "wow_delta":     snap.get("wow_delta", 0),
    }
    pb_request("POST", "/api/collections/session_snapshots/records", data, token)

def write_churn_score(token, pb_account_id, scores):
    data = {
        "account_id":   pb_account_id,
        "churn_score":  scores["churn_score"],
        "upsell_score": scores["upsell_score"],
        "health":       scores["health"],
        "explanation":  scores["explanation"],
        "sessions_7d":  scores["sessions_7d"],
        "wow_delta":    scores["wow_delta"],
        "scored_at":    datetime.now().isoformat(),
    }
    pb_request("POST", "/api/collections/churn_scores/records", data, token)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n=== Gallabox Churn Ingestion Pipeline ===\n")

    # Auth
    print("Authenticating with PocketBase...")
    token = pb_auth()
    print("  OK\n")

    # Fetch data
    customers  = fetch_chargebee_customers()
    subs       = fetch_subscriptions()
    amp_data   = fetch_amplitude_sessions()

    print(f"\nProcessing {len(customers)} accounts...")

    stats = {"green": 0, "yellow": 0, "red": 0, "no_amp": 0, "written": 0}

    for c in customers:
        cb_id      = c.get("id")
        amp_id     = c.get("cf_Account_ID", "")
        email      = c.get("cf_Account_Email") or c.get("email", "")
        company    = c.get("cf_Account_name") or c.get("company", "Unknown")
        currency   = c.get("preferred_currency_code", "INR")

        sub = subs.get(cb_id, {
            "plan": "unknown", "status": "unknown", "mrr": 0, "currency": currency
        })
        sessions = amp_data.get(amp_id, {})

        if not sessions:
            stats["no_amp"] += 1

        scores = compute_scores(c, sub, sessions)
        stats[scores["health"]] += 1

        # Build account record
        account_record = {
            "chargebee_id":     cb_id,
            "amplitude_id":     amp_id,
            "company":          company[:100],
            "email":            email[:200] if email else "",
            "plan":             sub.get("plan", "unknown")[:100],
            "mrr":              sub.get("mrr", 0) / 100,
            "currency":         sub.get("currency", currency),
            "status":           sub.get("status", "unknown"),
            "channel_provider": c.get("cf_Channel_Provider", ""),
            "cb_created_at":    str(c.get("created_at", "")),
        }

        pb_id = upsert_account(token, cb_id, account_record)
        if pb_id:
            if sessions:
                write_session_snapshot(token, pb_id, sessions)
            write_churn_score(token, pb_id, scores)
            stats["written"] += 1
            if stats["written"] % 50 == 0:
                print(f"  Written {stats['written']} accounts...")

    print(f"\n=== Done ===")
    print(f"  Total written:   {stats['written']}")
    print(f"  Green (healthy): {stats['green']}")
    print(f"  Yellow (watch):  {stats['yellow']}")
    print(f"  Red (at risk):   {stats['red']}")
    print(f"  No Amplitude:    {stats['no_amp']}")

if __name__ == "__main__":
    main()
