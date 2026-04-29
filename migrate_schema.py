#!/usr/bin/env python3
"""
Migrate PocketBase schema to support enhanced scoring fields.
Run this once before running clickhouse_score_v2.py
"""
import json, os, sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD

def pb_auth():
    body = json.dumps({"identity": PB_EMAIL, "password": PB_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/_superusers/auth-with-password",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["token"]

def get_collection(name, token):
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/{name}",
        headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"Error getting collection {name}: {e.read().decode()}")
        return None

def update_collection(name, data, token):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/{name}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        },
        method="PATCH"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

def main():
    print("Migrating PocketBase schema for Gallabox Churn v2...\n")
    
    token = pb_auth()
    print("✓ Authenticated\n")
    
    # Get current churn_scores collection
    coll = get_collection("churn_scores", token)
    if not coll:
        print("✗ Could not find churn_scores collection")
        return
    
    existing_fields = {f["name"] for f in coll.get("fields", coll.get("schema", []))}
    print(f"Existing fields: {existing_fields}\n")
    
    # New fields to add
    new_fields = [
        {"name": "convos_7d", "type": "number"},
        {"name": "convos_30d", "type": "number"},
        {"name": "messages_7d", "type": "number"},
        {"name": "avg_msgs_per_convo", "type": "number"},
        {"name": "bot_ratio", "type": "number"},
        {"name": "resolution_rate", "type": "number"},
        {"name": "avg_frt_secs", "type": "number"},
        {"name": "active_agents", "type": "number"},
        {"name": "active_bots", "type": "number"},
        {"name": "total_channels", "type": "number"},
        {"name": "trend_consistency", "type": "number"},
    ]
    
    # Filter to only fields that don't exist
    fields_to_add = [f for f in new_fields if f["name"] not in existing_fields]
    
    if not fields_to_add:
        print("✓ All fields already exist, nothing to migrate")
        return
    
    print(f"Adding {len(fields_to_add)} new fields:")
    for f in fields_to_add:
        print(f"  + {f['name']} ({f['type']})")
    
    # Build updated fields list
    current_fields = coll.get("fields", coll.get("schema", []))
    updated_fields = current_fields + fields_to_add
    
    # Update collection
    result, err = update_collection("churn_scores", {"fields": updated_fields}, token)
    
    if err:
        print(f"\n✗ Migration failed: {err}")
    else:
        print(f"\n✓ Migration successful!")
        print(f"  churn_scores now has {len(updated_fields)} fields")

if __name__ == "__main__":
    main()
