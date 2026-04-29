"""
Zoho Auth helper — shared by all Gallabox Churn sync scripts.
Credentials are read from env vars (ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN).
The access token is cached in .zoho_token.json to avoid redundant refresh calls.
"""
import json, time, os, urllib.request, urllib.parse
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN

TOKEN_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".zoho_token.json")

def _load_cache() -> dict:
    try:
        with open(TOKEN_CACHE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_cache(data: dict):
    with open(TOKEN_CACHE, "w") as f:
        json.dump(data, f, indent=2)

def get_token() -> str:
    """Returns a valid access token, refreshing silently if expired."""
    c = _load_cache()
    if c.get("access_token") and time.time() - c.get("fetched_at", 0) < 3500:
        return c["access_token"]

    params = urllib.parse.urlencode({
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id":     ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type":    "refresh_token",
    })
    req = urllib.request.Request(
        f"https://accounts.zoho.in/oauth/v2/token?{params}", method="POST"
    )
    with urllib.request.urlopen(req) as r:
        new_data = json.loads(r.read())

    if "access_token" not in new_data:
        raise RuntimeError(f"Token refresh failed: {new_data}")

    _save_cache({"access_token": new_data["access_token"], "fetched_at": time.time()})
    return new_data["access_token"]


def zoho_crm_get(path: str, params: dict = None) -> dict:
    token = get_token()
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request(
        f"https://www.zohoapis.in/crm/v3/{path}{qs}",
        headers={"Authorization": f"Zoho-oauthtoken {token}"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def zoho_desk_get(path: str, params: dict = None, org_id: str = "60019121503") -> dict:
    token = get_token()
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request(
        f"https://desk.zoho.in/api/v1/{path}{qs}",
        headers={
            "Authorization": f"Zoho-oauthtoken {token}",
            "orgId": org_id,
        }
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())
