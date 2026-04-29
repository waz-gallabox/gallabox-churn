
#!/usr/bin/env python3
"""
Gallabox Churn Fix + Rescore
1. Delete all duplicate churn_score records (keep only latest per account)
2. Re-fetch subscriptions properly and update account status/plan/mrr
3. Recompute scores with correct billing signals
4. Link Amplitude data where available
"""
import json, urllib.request, urllib.parse, base64, subprocess, os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD, CB_SITE, CB_KEY

CB_CREDS = base64.b64encode(f"{CB_KEY}:".encode()).decode()

def pb_auth():
    body = json.dumps({"identity": PB_EMAIL, "password": PB_PASSWORD}).encode()
    req = urllib.request.Request(f"{PB_BASE}/api/collections/_superusers/auth-with-password",
        data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["token"]

def pb(method, path, data=None, token=None):
    body = json.dumps(data).encode() if data else None
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{PB_BASE}{path}", data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return (json.loads(body) if body.strip() else {}), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

def cb_get(path):
    url = f"https://{CB_SITE}/api/v2/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {CB_CREDS}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# ── STEP 1: Delete all churn_scores, start fresh ─────────────────────────────
def clear_churn_scores(token):
    print("Clearing duplicate churn scores...")
    deleted = 0
    while True:
        res, _ = pb("GET", "/api/collections/churn_scores/records?perPage=200", token=token)
        if not res or not res.get("items"):
            break
        for item in res["items"]:
            pb("DELETE", f"/api/collections/churn_scores/records/{item['id']}", token=token)
            deleted += 1
        if len(res["items"]) < 200:
            break
    print(f"  Deleted {deleted} score records")

# ── STEP 2: Fetch all subscriptions indexed by customer_id ───────────────────
def fetch_all_subscriptions():
    print("Fetching all subscriptions from Chargebee...")
    subs = {}
    offset = None
    while True:
        path = "subscriptions?limit=100"
        if offset:
            path += f"&offset={urllib.parse.quote(str(offset))}"
        data = cb_get(path)
        for item in data.get("list", []):
            s = item["subscription"]
            cid = s.get("customer_id")
            # Keep most recent active sub per customer
            if cid not in subs or s.get("status") == "active":
                items_list = s.get("subscription_items", [])
                plan = items_list[0].get("item_price_id", "N/A") if items_list else s.get("plan_id","N/A")
                subs[cid] = {
                    "plan":     plan,
                    "status":   s.get("status", "unknown"),
                    "mrr":      s.get("mrr", 0),
                    "currency": s.get("currency_code", "INR"),
                }
        next_offset = data.get("next_offset")
        if not next_offset:
            break
        offset = next_offset
    print(f"  Total subscriptions: {len(subs)}")
    return subs

# ── STEP 3: Fetch Amplitude sessions ─────────────────────────────────────────
def fetch_amplitude():
    print("Fetching Amplitude session data...")
    today = datetime.now()
    end   = today.strftime("%Y%m%d")
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    payload = {
        "e":     json.dumps({"event_type": "session_start"}),
        "start": start, "end": end,
        "m":     "totals", "g": "user_id", "i": "7"
    }
    cmd = f"composio tools execute AMPLITUDE_GET_EVENT_SEGMENTATION -d '{json.dumps(payload)}' > /tmp/amp_fix.json 2>/dev/null && echo ok"
    subprocess.run(cmd, shell=True, capture_output=True, text=True)
    sessions_map = {}
    try:
        d = json.load(open("/tmp/amp_fix.json"))
        if d.get("successful"):
            data   = d["data"]["data"]["data"]
            labels = data.get("seriesLabels", [])
            series = data.get("series", [])
            xvals  = data.get("xValues", [])
            for label, s in zip(labels, series):
                if not label or label == 0: continue
                cur  = s[1] if len(s) > 1 else s[0]
                prev = s[0] if len(s) > 0 else 0
                wow  = ((cur - prev) / prev * 100) if prev > 0 else 0
                sessions_map[str(label)] = {
                    "current": cur, "previous": prev,
                    "wow_delta": round(wow, 2),
                    "xvals": xvals,
                }
            print(f"  Got {len(sessions_map)} Amplitude accounts")
        else:
            print(f"  Amplitude error: {d.get('error','unknown')}")
    except Exception as e:
        print(f"  Parse error: {e}")
    return sessions_map

# ── STEP 4: Scoring logic ─────────────────────────────────────────────────────
def compute_scores(mrr, status, plan, sessions):
    cur       = sessions.get("current", 0)
    prev      = sessions.get("previous", 0)
    wow       = sessions.get("wow_delta", 0)
    has_amp   = bool(sessions)

    # ── Churn score ──
    churn = 0

    # Billing signals
    if status == "cancelled":           churn += 50
    elif status == "non_renewing":      churn += 35
    elif status == "paused":            churn += 30
    elif status == "in_trial":          churn += 20
    elif status == "unknown":           churn += 15
    # MRR signal
    if mrr == 0:                        churn += 20
    elif mrr < 500:                     churn += 10
    elif mrr > 5000:                    churn -= 5   # high value = stickier

    # Behavioral signals (only if Amplitude data available)
    if has_amp:
        if cur == 0 and prev > 0:       churn += 30
        elif cur == 0:                  churn += 15
        if wow < -50:                   churn += 25
        elif wow < -30:                 churn += 15
        elif wow < -10:                 churn += 8

    churn = max(0, min(churn, 100))

    # ── Upsell score ──
    upsell = 0

    # High engagement
    if has_amp:
        if cur > 500:                   upsell += 35
        elif cur > 200:                 upsell += 25
        elif cur > 100:                 upsell += 15
        elif cur > 50:                  upsell += 8
        if wow > 30:                    upsell += 20
        elif wow > 15:                  upsell += 12
        elif wow > 5:                   upsell += 6

    # Low plan relative to potential
    plan_lower = plan.lower()
    free_keywords = ["free", "trial", "trail", "zone", "starter", "basic"]
    if any(k in plan_lower for k in free_keywords):
        upsell += 20
        if has_amp and cur > 50:        upsell += 15

    # Low MRR but active and paying
    if 0 < mrr < 2000 and status == "active":
        upsell += 15
    elif mrr == 0 and status in ["active", "in_trial"]:
        upsell += 10

    upsell = max(0, min(upsell, 100))

    # ── Health ──
    if churn >= 55:                     health = "red"
    elif churn >= 25 or (has_amp and wow < -20):  health = "yellow"
    else:                               health = "green"

    # ── Explanation ──
    plan_s = plan.replace("-", " ")[:40]
    mrr_s  = f"${mrr/100:.0f}/mo" if mrr > 0 else "no MRR"
    amp_s  = f"{cur} sessions this week (WoW: {wow:+.0f}%)" if has_amp else "no behavioral data yet"

    if health == "red":
        exp = (f"High churn risk. Status: {status}. {amp_s}. "
               f"Plan: {plan_s}, {mrr_s}. "
               f"Recommend: urgent CSM outreach within 48h.")
    elif health == "yellow":
        exp = (f"Monitor closely. Status: {status}. {amp_s}. "
               f"Plan: {plan_s}, {mrr_s}. "
               f"Recommend: check-in with a product tip or renewal nudge.")
    else:
        upsell_note = f" Strong upsell candidate (score: {upsell})." if upsell >= 40 else ""
        exp = (f"Healthy account. Status: {status}. {amp_s}. "
               f"Plan: {plan_s}, {mrr_s}.{upsell_note}")

    return {
        "churn_score":  round(churn, 1),
        "upsell_score": round(upsell, 1),
        "health":       health,
        "explanation":  exp,
        "sessions_7d":  cur,
        "wow_delta":    wow,
    }

# ── STEP 5: Update accounts + write fresh scores ──────────────────────────────
def update_and_score(token, subs, amp):
    print("\nUpdating accounts and writing fresh scores...")
    stats = {"green": 0, "yellow": 0, "red": 0, "with_sub": 0, "with_amp": 0, "total": 0}
    page = 1
    while True:
        res, _ = pb("GET", f"/api/collections/accounts/records?perPage=200&page={page}", token=token)
        if not res or not res.get("items"):
            break
        for acc in res["items"]:
            cb_id  = acc.get("chargebee_id", "")
            amp_id = acc.get("amplitude_id", "")
            sub    = subs.get(cb_id, {})
            sess   = amp.get(amp_id, {}) if amp_id else {}

            if sub:  stats["with_sub"] += 1
            if sess: stats["with_amp"] += 1

            mrr    = sub.get("mrr", 0) / 100 if sub else (acc.get("mrr", 0))
            status = sub.get("status", acc.get("status", "unknown"))
            plan   = sub.get("plan",   acc.get("plan", "unknown"))
            cur    = sub.get("currency", acc.get("currency", "INR"))

            # Update account with fresh billing data
            if sub:
                pb("PATCH", f"/api/collections/accounts/records/{acc['id']}", {
                    "plan": plan[:100], "status": status,
                    "mrr": mrr, "currency": cur,
                }, token=token)

            scores = compute_scores(mrr, status, plan, sess)
            stats[scores["health"]] += 1
            stats["total"] += 1

            pb("POST", "/api/collections/churn_scores/records", {
                "account_id":   acc["id"],
                "churn_score":  scores["churn_score"],
                "upsell_score": scores["upsell_score"],
                "health":       scores["health"],
                "explanation":  scores["explanation"],
                "sessions_7d":  scores["sessions_7d"],
                "wow_delta":    scores["wow_delta"],
                "scored_at":    datetime.now().isoformat(),
            }, token=token)

        if page % 5 == 0:
            print(f"  Processed {stats['total']} accounts...")
        if page >= res.get("totalPages", 1):
            break
        page += 1

    return stats

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n=== Gallabox Churn Fix + Rescore ===\n")
    token = pb_auth()
    print("PocketBase auth OK\n")

    clear_churn_scores(token)
    subs = fetch_all_subscriptions()
    amp  = fetch_amplitude()

    stats = update_and_score(token, subs, amp)

    print(f"\n=== Results ===")
    print(f"  Total accounts scored: {stats['total']}")
    print(f"  With subscription:     {stats['with_sub']}")
    print(f"  With Amplitude data:   {stats['with_amp']}")
    print(f"  Green  (healthy):      {stats['green']}")
    print(f"  Yellow (at risk):      {stats['yellow']}")
    print(f"  Red    (churning):     {stats['red']}")

    # Verify churn_scores count
    res, _ = pb("GET", "/api/collections/churn_scores/records?perPage=1", token=token)
    print(f"\n  churn_scores in DB:    {res['totalItems'] if res else '?'}")

if __name__ == "__main__":
    main()
