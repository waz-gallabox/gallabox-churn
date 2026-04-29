"""
Shared config — loads credentials from .env in the project root.
All scripts import from here instead of hardcoding credentials.
"""
import os
from pathlib import Path

def _load_env():
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

_load_env()

def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}  (set it in .env)")
    return val

# ── PocketBase ────────────────────────────────────────────
PB_BASE     = os.environ.get("PB_BASE",  "http://127.0.0.1:8090")
PB_EMAIL    = _require("PB_EMAIL")
PB_PASSWORD = _require("PB_PASSWORD")

# ── ClickHouse ────────────────────────────────────────────
CH_HOST = _require("CH_HOST")
CH_USER = _require("CH_USER")
CH_PASS = _require("CH_PASS")

# ── Chargebee ─────────────────────────────────────────────
CB_SITE = _require("CB_SITE")
CB_KEY  = _require("CB_KEY")

# ── Zoho ──────────────────────────────────────────────────
ZOHO_DESK_ORG_ID    = os.environ.get("ZOHO_DESK_ORG_ID", "60019121503")
ZOHO_CLIENT_ID      = os.environ.get("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET  = os.environ.get("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN  = os.environ.get("ZOHO_REFRESH_TOKEN", "")
