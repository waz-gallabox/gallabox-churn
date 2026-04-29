#!/usr/bin/env python3
"""
Gallabox Churn — ClickHouse behavioral scoring
Joins Chargebee billing (PocketBase) + ClickHouse conversation activity
No Amplitude — conversations are the right signal for a WhatsApp SaaS
"""
import json, urllib.request, urllib.parse, base64, os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD, CH_HOST, CH_USER, CH_PASS

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
            raw = r.read()
            return (json.loads(raw) if raw.strip() else {}), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

def ch_query(sql):
    creds = base64.b64encode(f"{CH_USER}:{CH_PASS}".encode()).decode()
    req = urllib.request.Request(CH_HOST,
        data=(sql + " FORMAT JSON").encode(),
        headers={"Authorization": f"Basic {creds}", "Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

def fetch_ch_activity():
    print("Fetching conversation activity from ClickHouse...")
    sql = """
    SELECT
        accountId                                                AS account_id,
        COUNT()                                                  AS total_convos,
        COUNTIf(createdAt >= now() - INTERVAL 7 DAY)            AS convos_7d,
        COUNTIf(createdAt >= now() - INTERVAL 14 DAY
            AND createdAt <  now() - INTERVAL 7 DAY)            AS convos_prev_7d,
        COUNTIf(createdAt >= now() - INTERVAL 30 DAY)           AS convos_30d,
        MAX(createdAt)                                           AS last_activity
    FROM default.conversations
    WHERE accountId != ''
    GROUP BY accountId
    """
    d = ch_query(sql)
    rows = d.get("data", [])
    print(f"  Got conversation data for {len(rows)} accounts")

    activity = {}
    for r in rows:
        activity[r["account_id"]] = r

    print(f"  Total with activity: {len(activity)}")
    return activity

def compute_scores(mrr, billing_status, plan, ch):
    c7   = int(ch.get("convos_7d", 0))
    p7   = int(ch.get("convos_prev_7d", 0))
    c30  = int(ch.get("convos_30d", 0))
    tot  = int(ch.get("total_convos", 0))
    last = ch.get("last_activity", "")
    wow  = round((c7 - p7) / p7 * 100, 1) if p7 > 0 else 0
    has_data = tot > 0

    churn_reasons  = []
    upsell_reasons = []

    # ── Churn score ──────────────────────────────────────────────────────────
    churn = 0

    if billing_status == "cancelled":
        churn += 55
        churn_reasons.append("Subscription cancelled")
    elif billing_status == "non_renewing":
        churn += 40
        churn_reasons.append("Subscription set to non-renew — not paying next cycle")
    elif billing_status == "paused":
        churn += 35
        churn_reasons.append("Subscription paused")
    elif billing_status == "in_trial":
        churn += 10
        churn_reasons.append("Still in trial — not yet converted to paid")
    elif billing_status == "unknown":
        churn += 15
        churn_reasons.append("Unknown billing status")

    if mrr == 0 and billing_status not in ["in_trial", "active"]:
        churn += 15
        churn_reasons.append("Zero MRR — no financial commitment")
    if mrr > 50000:
        churn -= 15
    elif mrr > 10000:
        churn -= 8

    if has_data:
        if c7 == 0 and p7 > 0:
            churn += 30
            churn_reasons.append(f"Went completely dark this week (had {p7} convos last week)")
        elif c7 == 0 and tot > 0:
            churn += 20
            churn_reasons.append("No conversations this week (has historical activity)")
        elif c7 == 0:
            churn += 10
            churn_reasons.append("Never meaningfully active — no conversations recorded")

        if wow < -70:
            churn += 22
            churn_reasons.append(f"Massive conversation drop — {abs(wow):.0f}% WoW decline")
        elif wow < -50:
            churn += 16
            churn_reasons.append(f"Severe conversation drop — {abs(wow):.0f}% WoW decline")
        elif wow < -30:
            churn += 10
            churn_reasons.append(f"Significant conversation drop — {abs(wow):.0f}% WoW decline")
        elif wow < -10:
            churn += 5
            churn_reasons.append(f"Conversation volume declining — {abs(wow):.0f}% WoW")
        elif wow > 20:
            churn -= 8
        elif wow > 10:
            churn -= 4

        if c7 < 5 and billing_status == "active":
            churn += 15
            churn_reasons.append(f"Very low usage — only {c7} conversations this week on paid plan")
        elif c7 < 20 and billing_status == "active":
            churn += 8
            churn_reasons.append(f"Low usage — {c7} conversations this week")
        elif c7 > 500:
            churn -= 10
        elif c7 > 200:
            churn -= 5
    else:
        churn += 15
        churn_reasons.append("No conversation data — account may not have activated product")

    churn = max(0, min(int(churn), 100))

    # ── Upsell score ─────────────────────────────────────────────────────────
    upsell = 0
    if billing_status in ["active", "in_trial"]:
        if c7 > 1000:
            upsell += 35
            upsell_reasons.append(f"Very high usage — {c7} conversations this week")
        elif c7 > 500:
            upsell += 28
            upsell_reasons.append(f"High usage — {c7} conversations this week")
        elif c7 > 200:
            upsell += 20
            upsell_reasons.append(f"Strong usage — {c7} conversations this week")
        elif c7 > 50:
            upsell += 12
            upsell_reasons.append(f"Moderate usage — {c7} conversations this week")

        if wow > 30:
            upsell += 20
            upsell_reasons.append(f"Rapid growth — conversations up {wow:.0f}% WoW")
        elif wow > 15:
            upsell += 12
            upsell_reasons.append(f"Growing fast — up {wow:.0f}% WoW")
        elif wow > 5:
            upsell += 6
            upsell_reasons.append(f"Positive growth trend — up {wow:.0f}% WoW")

        plan_l = plan.lower()
        if any(k in plan_l for k in ["free", "trial", "trail", "zone", "starter", "basic", "message-credits", "growth"]):
            upsell += 15
            upsell_reasons.append("On entry/mid-tier plan — natural upgrade path exists")
            if c7 > 50:
                upsell += 10
                upsell_reasons.append("High usage on lower plan — likely hitting limits")

        if 0 < mrr < 3000 and billing_status == "active":
            upsell += 10
            upsell_reasons.append(f"Low MRR (${mrr/100:.0f}/mo) — room to expand revenue")
        if mrr == 0 and c7 > 20:
            upsell += 15
            upsell_reasons.append("Active user on free/credits plan — strong conversion candidate")

    upsell = max(0, min(int(upsell), 100))

    # ── Health badge ─────────────────────────────────────────────────────────
    if billing_status == "cancelled":
        health = "red"
    elif churn >= 50:
        health = "red"
    elif churn >= 25 or wow < -20:
        health = "yellow"
    else:
        health = "green"

    # ── Explanation ──────────────────────────────────────────────────────────
    plan_s = plan.replace("-", " ")[:40]
    mrr_s  = f"${mrr/100:.0f}/mo" if mrr > 0 else "free/no MRR"
    act_s  = (f"{c7} conversations this week" +
              (f" (WoW: {wow:+.0f}%)" if p7 > 0 else " (first week data)")
              if has_data else "no conversation activity yet")

    if health == "red":
        exp = (f"High churn risk. Billing: {billing_status}. {act_s}. "
               f"Plan: {plan_s}, {mrr_s}. Action: urgent CSM call within 48h.")
    elif health == "yellow":
        exp = (f"Monitor closely. Billing: {billing_status}. {act_s}. "
               f"Plan: {plan_s}, {mrr_s}. Action: check-in or renewal nudge.")
    else:
        up = f" Upsell score {upsell} — strong upgrade candidate." if upsell >= 40 else ""
        exp = (f"Healthy. Billing: {billing_status}. {act_s}. "
               f"Plan: {plan_s}, {mrr_s}.{up}")

    return {
        "churn_score":    churn,
        "upsell_score":   upsell,
        "health":         health,
        "explanation":    exp,
        "churn_reasons":  churn_reasons,
        "upsell_reasons": upsell_reasons,
        "sessions_7d":    c7,
        "wow_delta":      wow,
    }

def main():
    print("=== Gallabox Churn ClickHouse Scorer ===\n")
    token = pb_auth()
    print("PocketBase auth OK")

    subs = json.load(open("/tmp/subs_live.json"))
    print(f"Loaded {len(subs)} Chargebee subscriptions")

    ch_data = fetch_ch_activity()

    # Score all PocketBase accounts
    stats = {"green":0, "yellow":0, "red":0, "with_ch":0, "with_sub":0,
             "total":0, "skipped":0}
    scored_at = datetime.now().isoformat()
    page = 1

    while True:
        res, _ = pb("GET", f"/api/collections/accounts/records?perPage=200&page={page}", token=token)
        if not res or not res.get("items"): break

        for acc in res["items"]:
            cb_id  = acc.get("chargebee_id", "")
            amp_id = acc.get("amplitude_id", "")  # = cf_Account_ID = ClickHouse accountId
            sub    = subs.get(cb_id, {})
            ch     = ch_data.get(amp_id, {})

            billing_status = sub.get("status", acc.get("status", "unknown"))

            # Only score accounts with active/in_trial/non_renewing subscription
            VALID_STATUSES = {"active", "in_trial", "non_renewing", "paused"}
            if billing_status not in VALID_STATUSES:
                stats["skipped"] += 1
                continue

            if sub: stats["with_sub"] += 1
            if ch:  stats["with_ch"]  += 1

            mrr  = sub.get("mrr", 0) / 100 if sub else acc.get("mrr", 0)
            plan = sub.get("plan", acc.get("plan", "unknown"))
            cur  = sub.get("currency", acc.get("currency", "INR"))

            # Patch account billing data
            if sub:
                pb("PATCH", f"/api/collections/accounts/records/{acc['id']}",
                   {"plan": plan[:100], "status": billing_status,
                    "mrr": mrr, "currency": cur}, token=token)

            sc = compute_scores(mrr, billing_status, plan, ch)
            stats[sc["health"]] += 1
            stats["total"] += 1

            pb("POST", "/api/collections/churn_scores/records", {
                "account_id":    acc["id"],
                "churn_score":   sc["churn_score"],
                "upsell_score":  sc["upsell_score"],
                "health":        sc["health"],
                "explanation":   sc["explanation"],
                "churn_reasons": sc["churn_reasons"],
                "upsell_reasons":sc["upsell_reasons"],
                "sessions_7d":   sc["sessions_7d"],
                "wow_delta":     sc["wow_delta"],
                "scored_at":     scored_at,
            }, token=token)

        if stats["total"] % 500 == 0 and stats["total"] > 0:
            print(f"  Scored {stats['total']}...", flush=True)

        if page >= res.get("totalPages", 1): break
        page += 1

    res2, _ = pb("GET", "/api/collections/churn_scores/records?perPage=1", token=token)
    print(f"\n=== Done ===")
    print(f"  Total scored:          {stats['total']}")
    print(f"  Skipped (no sub+data): {stats['skipped']}")
    print(f"  With Chargebee sub:    {stats['with_sub']}")
    print(f"  With ClickHouse data:  {stats['with_ch']}")
    print(f"  Green  (healthy):      {stats['green']}")
    print(f"  Yellow (at risk):      {stats['yellow']}")
    print(f"  Red    (churning):     {stats['red']}")
    print(f"  Total in DB:           {res2.get('totalItems','?') if res2 else '?'}")

if __name__ == "__main__":
    main()
