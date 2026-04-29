
#!/usr/bin/env python3
"""
Gallabox Churn Re-scorer — fetches Amplitude data and updates churn scores in PocketBase
"""
import json, urllib.request, urllib.parse, base64, subprocess, time, os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD

def pb_auth():
    body = json.dumps({"identity": PB_EMAIL, "password": PB_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/_superusers/auth-with-password",
        data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["token"]

def pb_request(method, path, data=None, token=None):
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{PB_BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

def fetch_amplitude():
    print("Fetching Amplitude data...")
    today = datetime.now()
    end   = today.strftime("%Y%m%d")
    start = (today - timedelta(days=14)).strftime("%Y%m%d")

    result = subprocess.run(
        f'composio tools execute AMPLITUDE_GET_EVENT_SEGMENTATION -d \'{json.dumps({"e": json.dumps({"event_type": "session_start"}), "start": start, "end": end, "m": "totals", "g": "user_id", "i": "7"})}\' > /tmp/amp_rescore.json 2>/dev/null && echo ok',
        shell=True, capture_output=True, text=True
    )

    sessions_map = {}
    try:
        d = json.load(open("/tmp/amp_rescore.json"))
        if d.get("successful"):
            data   = d["data"]["data"]["data"]
            labels = data.get("seriesLabels", [])
            series = data.get("series", [])
            xvalues= data.get("xValues", [])
            for label, s in zip(labels, series):
                if not label or label == 0: continue
                current  = s[1] if len(s) > 1 else s[0]
                previous = s[0] if len(s) > 0 else 0
                wow = ((current - previous) / previous * 100) if previous > 0 else 0
                sessions_map[str(label)] = {
                    "current": current, "previous": previous,
                    "wow_delta": round(wow, 2),
                    "period_start": xvalues[0] if xvalues else "",
                    "period_end": xvalues[1] if len(xvalues) > 1 else end,
                }
            print(f"  Got {len(sessions_map)} accounts from Amplitude")
        else:
            print(f"  Amplitude error: {d.get('error')}")
    except Exception as e:
        print(f"  Parse error: {e}")
    return sessions_map

def compute_scores(mrr, status, plan, sessions):
    wow_delta = sessions.get("wow_delta", 0)
    current   = sessions.get("current", 0)
    previous  = sessions.get("previous", 0)

    churn = 0
    if current == 0 and previous > 0:   churn += 40
    elif current == 0 and previous == 0: churn += 25
    if wow_delta < -50:   churn += 30
    elif wow_delta < -30: churn += 20
    elif wow_delta < -10: churn += 10
    if mrr == 0:    churn += 15
    elif mrr < 500: churn += 5
    if status in ["cancelled", "paused"]:  churn += 30
    elif status == "non_renewing":          churn += 20
    churn = min(churn, 100)

    upsell = 0
    if current > 500:   upsell += 35
    elif current > 200: upsell += 25
    elif current > 100: upsell += 15
    if wow_delta > 20:  upsell += 20
    elif wow_delta > 10: upsell += 10
    free_indicators = ["free", "trial", "zone"]
    if any(f in plan.lower() for f in free_indicators) and current > 100: upsell += 25
    if mrr < 500 and current > 200: upsell += 20
    upsell = min(upsell, 100)

    if churn >= 60:   health = "red"
    elif churn >= 30 or wow_delta < -20: health = "yellow"
    else:             health = "green"

    plan_short = plan.replace("-", " ")[:40]
    if health == "red":
        exp = (f"High churn risk. Sessions this week: {current} "
               f"({'down '+str(abs(int(wow_delta)))+'%' if wow_delta < 0 else 'no prior data'}). "
               f"On {plan_short} at ${mrr:.0f}/mo. Recommend: CSM call within 48h.")
    elif health == "yellow":
        exp = (f"Watch this account. Sessions {'dropped '+str(abs(int(wow_delta)))+'% WoW' if wow_delta < 0 else 'stable'}. "
               f"({previous} -> {current}). On {plan_short}. Recommend: product tip or nudge.")
    else:
        exp = (f"Healthy. {current} sessions this week "
               f"({'up '+str(int(wow_delta))+'%' if wow_delta > 0 else 'stable'}). "
               f"On {plan_short} at ${mrr:.0f}/mo. "
               + ("Strong upsell candidate." if upsell > 50 else "Keep nurturing."))

    return {"churn_score": round(churn,1), "upsell_score": round(upsell,1),
            "health": health, "explanation": exp,
            "sessions_7d": current, "wow_delta": wow_delta}

def main():
    print("\n=== Gallabox Churn Re-scorer ===\n")
    token = pb_auth()
    print("PocketBase auth OK")

    amp = fetch_amplitude()
    if not amp:
        print("No Amplitude data — aborting")
        return

    # Get all accounts with amplitude_id
    page, total_updated = 1, 0
    stats = {"green": 0, "yellow": 0, "red": 0, "matched": 0}

    while True:
        res, err = pb_request("GET",
            f"/api/collections/accounts/records?perPage=200&page={page}&filter=amplitude_id!=\"\"",
            token=token)
        if err or not res: break
        items = res.get("items", [])
        if not items: break

        for acc in items:
            amp_id = acc.get("amplitude_id", "")
            sessions = amp.get(amp_id, {})
            if not sessions: continue

            stats["matched"] += 1
            scores = compute_scores(acc.get("mrr",0), acc.get("status",""), acc.get("plan",""), sessions)
            stats[scores["health"]] += 1

            # Update churn score record
            score_data = {
                "account_id":   acc["id"],
                "churn_score":  scores["churn_score"],
                "upsell_score": scores["upsell_score"],
                "health":       scores["health"],
                "explanation":  scores["explanation"],
                "sessions_7d":  scores["sessions_7d"],
                "wow_delta":    scores["wow_delta"],
                "scored_at":    datetime.now().isoformat(),
            }
            # Check existing score record
            existing, _ = pb_request("GET",
                f"/api/collections/churn_scores/records?filter=account_id=\"{acc['id']}\"&perPage=1",
                token=token)
            if existing and existing.get("items"):
                sid = existing["items"][0]["id"]
                pb_request("PATCH", f"/api/collections/churn_scores/records/{sid}", score_data, token)
            else:
                pb_request("POST", "/api/collections/churn_scores/records", score_data, token)

            total_updated += 1

        page += 1
        if page > res.get("totalPages", 1): break
        print(f"  Updated page {page-1}/{res['totalPages']} ({total_updated} scored so far)")

    print(f"\n=== Done ===")
    print(f"  Amplitude matches: {stats['matched']}")
    print(f"  Green:  {stats['green']}")
    print(f"  Yellow: {stats['yellow']}")
    print(f"  Red:    {stats['red']}")

if __name__ == "__main__":
    main()
