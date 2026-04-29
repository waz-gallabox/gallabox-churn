#!/usr/bin/env python3
"""Score all accounts using pre-fetched subscription data + ClickHouse/Amplitude"""
import json, urllib.request, urllib.parse, base64, subprocess, os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD

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

def fetch_amplitude():
    print("Fetching Amplitude...", flush=True)
    today = datetime.now()
    end   = today.strftime("%Y%m%d")
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    payload = {"e": json.dumps({"event_type": "session_start"}),
               "start": start, "end": end, "m": "totals", "g": "user_id", "i": "7"}
    subprocess.run(
        f"composio tools execute AMPLITUDE_GET_EVENT_SEGMENTATION -d '{json.dumps(payload)}' > /tmp/amp_score.json 2>/dev/null",
        shell=True)
    sessions_map = {}
    try:
        d = json.load(open("/tmp/amp_score.json"))
        if d.get("successful"):
            data = d["data"]["data"]["data"]
            for label, s in zip(data.get("seriesLabels",[]), data.get("series",[])):
                if not label or label == 0: continue
                cur  = s[1] if len(s)>1 else s[0]
                prev = s[0] if s else 0
                wow  = ((cur-prev)/prev*100) if prev>0 else 0
                sessions_map[str(label)] = {"current":cur,"previous":prev,"wow_delta":round(wow,2)}
            print(f"  {len(sessions_map)} Amplitude accounts", flush=True)
    except Exception as e:
        print(f"  Amplitude error: {e}", flush=True)
    return sessions_map

def compute_scores(mrr, status, plan, sessions, conv_7d=None, conv_wow=None):
    """
    Returns churn_score, upsell_score, health, explanation,
    churn_reasons (list), upsell_reasons (list)
    """
    # Use ClickHouse conv data if available, else Amplitude session data
    if conv_7d is not None:
        cur  = conv_7d
        prev = conv_7d / (1 + (conv_wow or 0)/100) if conv_wow else 0
        wow  = conv_wow or 0
        has_activity = True
    else:
        cur  = sessions.get("current", 0)
        prev = sessions.get("previous", 0)
        wow  = sessions.get("wow_delta", 0)
        has_activity = bool(sessions)

    churn_reasons  = []
    upsell_reasons = []

    # ── Churn score ──────────────────────────────────────────────────────────
    churn = 0

    # Billing status signals
    if status == "cancelled":
        churn += 55
        churn_reasons.append("Subscription cancelled")
    elif status == "non_renewing":
        churn += 40
        churn_reasons.append("Subscription set to non-renew")
    elif status == "paused":
        churn += 35
        churn_reasons.append("Subscription paused")
    elif status == "in_trial":
        churn += 15
        churn_reasons.append("Still in trial — not yet converted")
    elif status == "unknown":
        churn += 20
        churn_reasons.append("Unknown billing status")

    # MRR signals
    if mrr == 0 and status not in ["in_trial", "cancelled"]:
        churn += 20
        churn_reasons.append("Zero MRR — likely on free/credits plan")
    elif 0 < mrr < 500:
        churn += 8
        churn_reasons.append(f"Low MRR (${mrr/100:.0f}/mo) — low switching cost")
    elif mrr > 10000:
        churn -= 10  # sticky large account

    # Activity signals
    if has_activity:
        if cur == 0 and prev > 0:
            churn += 25
            churn_reasons.append(f"Zero activity this week (was {int(prev)} last week)")
        elif cur == 0:
            churn += 10
            churn_reasons.append("No activity data this week")
        if wow < -50:
            churn += 20
            churn_reasons.append(f"Activity dropped {abs(int(wow))}% week-over-week")
        elif wow < -30:
            churn += 12
            churn_reasons.append(f"Activity dropped {abs(int(wow))}% week-over-week")
        elif wow < -10:
            churn += 5
            churn_reasons.append(f"Slight activity decline ({abs(int(wow))}% WoW)")
    else:
        churn_reasons.append("No activity data available")

    churn = max(0, min(int(churn), 100))

    # ── Upsell score ─────────────────────────────────────────────────────────
    upsell = 0

    if status not in ["active", "in_trial"]:
        upsell = 0  # no point upselling churned accounts
    else:
        if has_activity:
            if cur > 500:
                upsell += 35
                upsell_reasons.append(f"High usage — {int(cur)} conversations/sessions this week")
            elif cur > 200:
                upsell += 25
                upsell_reasons.append(f"Good usage — {int(cur)} conversations/sessions this week")
            elif cur > 100:
                upsell += 15
                upsell_reasons.append(f"Moderate usage — {int(cur)} conversations/sessions this week")
            elif cur > 50:
                upsell += 8
                upsell_reasons.append(f"Growing usage — {int(cur)} conversations/sessions this week")

            if wow > 30:
                upsell += 20
                upsell_reasons.append(f"Strong growth — activity up {int(wow)}% WoW")
            elif wow > 10:
                upsell += 10
                upsell_reasons.append(f"Positive growth trend — up {int(wow)}% WoW")

        plan_l = plan.lower()
        if any(k in plan_l for k in ["free", "trial", "trail", "zone", "starter", "basic", "message-credits"]):
            upsell += 20
            upsell_reasons.append("On entry-level plan — room to upgrade")

        if 0 < mrr < 2000 and status == "active":
            upsell += 15
            upsell_reasons.append(f"Low MRR (${mrr/100:.0f}/mo) with active subscription — upsell opportunity")
        elif mrr == 0 and status in ["active", "in_trial"]:
            upsell += 12
            upsell_reasons.append("Active with no MRR — conversion candidate")

    upsell = max(0, min(int(upsell), 100))

    # ── Health badge ─────────────────────────────────────────────────────────
    if status == "cancelled":
        health = "red"
    elif churn >= 50:
        health = "red"
    elif churn >= 25 or (has_activity and wow < -20):
        health = "yellow"
    else:
        health = "green"

    # ── Human-readable explanation ────────────────────────────────────────────
    plan_s = plan.replace("-", " ")[:40]
    mrr_s  = f"${mrr/100:.0f}/mo" if mrr > 0 else "free/no MRR"
    act_s  = f"{int(cur)} conversations this week" if has_activity else "no activity data"

    if health == "red":
        exp = (f"High churn risk. Billing: {status}. {act_s}. "
               f"Plan: {plan_s}, {mrr_s}. Action: urgent CSM call within 48h.")
    elif health == "yellow":
        exp = (f"Watch closely. Billing: {status}. {act_s} "
               f"({'WoW: ' + str(int(wow)) + '%' if has_activity else ''}). "
               f"Plan: {plan_s}, {mrr_s}. Action: product check-in or renewal nudge.")
    else:
        up = f" Upsell score {upsell} — strong upgrade candidate." if upsell >= 40 else ""
        exp = (f"Healthy. Billing: {status}. {act_s}. "
               f"Plan: {plan_s}, {mrr_s}.{up}")

    return {
        "churn_score":    churn,
        "upsell_score":   upsell,
        "health":         health,
        "explanation":    exp,
        "churn_reasons":  churn_reasons,
        "upsell_reasons": upsell_reasons,
        "sessions_7d":    cur,
        "wow_delta":      wow,
    }

def main():
    print("=== Gallabox Churn Scorer ===", flush=True)
    token = pb_auth()
    print("Auth OK", flush=True)

    # Load pre-fetched subscriptions (active + in_trial only)
    # Run: python3 fetch_subs.py first to get /tmp/subs_live.json
    try:
        subs = json.load(open("/tmp/subs_live.json"))
        print(f"Loaded {len(subs)} subscriptions from cache", flush=True)
    except FileNotFoundError:
        print("ERROR: /tmp/subs_live.json not found. Run fetch_subs.py first.", flush=True)
        return

    # Fetch Amplitude
    amp = fetch_amplitude()

    # Score all accounts in PB that have an active/in_trial subscription
    stats = {"green":0,"yellow":0,"red":0,"with_sub":0,"with_amp":0,"total":0,"skipped":0}
    page = 1
    scored_at = datetime.now().isoformat()

    ACTIVE_STATUSES = {"active", "in_trial", "non_renewing", "paused"}

    while True:
        res, _ = pb("GET", f"/api/collections/accounts/records?perPage=200&page={page}", token=token)
        if not res or not res.get("items"): break

        for acc in res["items"]:
            cb_id  = acc.get("chargebee_id", "")
            amp_id = acc.get("amplitude_id", "")
            sub    = subs.get(cb_id, {})

            # Skip accounts with no subscription or fully cancelled with no activity
            sub_status = sub.get("status", acc.get("status", "unknown"))
            if sub_status == "cancelled" and not amp.get(amp_id, {}):
                stats["skipped"] += 1
                continue

            if sub: stats["with_sub"] += 1
            sess = amp.get(amp_id, {}) if amp_id else {}
            if sess: stats["with_amp"] += 1

            mrr    = sub.get("mrr", acc.get("mrr",0)*100) / 100 if sub else acc.get("mrr",0)
            status = sub_status
            plan   = sub.get("plan", acc.get("plan","unknown"))
            cur    = sub.get("currency", acc.get("currency","INR"))

            # Update account billing data
            if sub:
                pb("PATCH", f"/api/collections/accounts/records/{acc['id']}",
                   {"plan": plan[:100], "status": status, "mrr": mrr, "currency": cur}, token=token)

            sc = compute_scores(mrr, status, plan, sess)
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
    print(f"  Total scored:      {stats['total']}")
    print(f"  Skipped (inactive):{stats['skipped']}")
    print(f"  With subscription: {stats['with_sub']}")
    print(f"  With Amplitude:    {stats['with_amp']}")
    print(f"  Green  (healthy):  {stats['green']}")
    print(f"  Yellow (at risk):  {stats['yellow']}")
    print(f"  Red    (churning): {stats['red']}")
    print(f"  churn_scores in DB:{res2['totalItems'] if res2 else '?'}")

if __name__ == "__main__":
    main()
