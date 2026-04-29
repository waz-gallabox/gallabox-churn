
#!/usr/bin/env python3
"""Fetch all Chargebee subscriptions and save to file"""
import json, urllib.request, urllib.parse, base64, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from config import CB_SITE, CB_KEY

CB_CREDS = base64.b64encode(f"{CB_KEY}:".encode()).decode()

def cb_get(path):
    url = f"https://{CB_SITE}/api/v2/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {CB_CREDS}"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())

subs = {}
offset = None
page = 0

while True:
    # Only fetch active + in_trial subscriptions (skip cancelled)
    path = "subscriptions?limit=100&status[is_not]=cancelled"
    if offset:
        path += f"&offset={urllib.parse.quote(str(offset))}"
    try:
        data = cb_get(path)
    except Exception as e:
        print(f"Error on page {page+1}: {e}", flush=True)
        break
    batch = data.get("list", [])
    for item in batch:
        s = item["subscription"]
        cid = s.get("customer_id")
        if cid not in subs or s.get("status") == "active":
            items_list = s.get("subscription_items", [])
            plan = items_list[0].get("item_price_id", "N/A") if items_list else s.get("plan_id", "N/A")
            subs[cid] = {
                "plan":             plan,
                "status":           s.get("status", "unknown"),
                "mrr":              s.get("mrr", 0),
                "currency":         s.get("currency_code", "INR"),
                "next_billing_at":  s.get("next_billing_at") or s.get("current_term_end") or 0,
            }
    page += 1
    print(f"Page {page}: {len(batch)} | unique customers: {len(subs)}", flush=True)
    sys.stdout.flush()
    next_offset = data.get("next_offset")
    if not next_offset:
        break
    offset = next_offset

_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(_data_dir, exist_ok=True)
json.dump(subs, open(os.path.join(_data_dir, "subs_live.json"), "w"))
statuses = {}
for v in subs.values():
    statuses[v["status"]] = statuses.get(v["status"], 0) + 1
print(f"\nDone. Total unique customers with subs: {len(subs)}")
print(f"Status breakdown: {statuses}")
print(f"With MRR > 0: {sum(1 for v in subs.values() if v['mrr'] > 0)}")
