#!/usr/bin/env python3
"""
Gallabox Churn v3 — 4-Source Scoring Model
════════════════════════════════════
Sources:
  1. Chargebee  — billing status, MRR, plan tier
  2. ClickHouse — product usage (convos, FRT, bot ratio, channels, team)
  3. Zoho Desk  — support tickets (open count, churn tickets, escalations)
  4. Zoho CRM   — KAM signals (ICP, expansion scope, upgrade possibility, segmentation)

Churn Score (0–100):  likelihood of churning
Upsell Score (0–100): expansion/upgrade potential

Weight allocation:
  Chargebee  → 35% of churn,  20% of upsell
  ClickHouse → 35% of churn,  50% of upsell
  Zoho Desk  → 20% of churn,   5% of upsell
  Zoho CRM   → 10% of churn,  25% of upsell
"""
import json, urllib.request, urllib.parse, base64, ssl, time, os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from zoho_auth import get_token
from config import PB_BASE, PB_EMAIL, PB_PASSWORD, CH_HOST, CH_USER, CH_PASS

CURRENCY_RATES = {
    'INR': 1.0, 'USD': 83.5, 'AED': 22.7,
    'EUR': 90.0, 'GBP': 105.0, 'SGD': 62.0, 'SAR': 22.3,
}

def to_inr(amount, currency):
    return amount * CURRENCY_RATES.get(currency, 1.0)

# ── PocketBase ────────────────────────────────────────────────────────────────
_pb_token = None

def pb_auth():
    global _pb_token
    if _pb_token: return _pb_token
    body = json.dumps({"identity": PB_EMAIL, "password": PB_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{PB_BASE}/api/collections/_superusers/auth-with-password",
        data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as r:
        _pb_token = json.loads(r.read())["token"]
    return _pb_token

def pb(method, path, data=None):
    token = pb_auth()
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    req = urllib.request.Request(f"{PB_BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return (json.loads(raw) if raw.strip() else {}), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

# ── ClickHouse ────────────────────────────────────────────────────────────────
def ch_query(sql, retries=3, delay=5):
    # curl used on macOS — Python TLS stack (urllib/httpx) fails to ClickHouse Cloud SSL handshake
    import subprocess, time
    cmd = [
        "/usr/bin/curl", "-s", "--connect-timeout", "30", "--max-time", "120",
        "-u", f"{CH_USER}:{CH_PASS}",
        "-d", sql,
        f"{CH_HOST}?default_format=JSON"
    ]
    last_err = None
    for attempt in range(retries):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)
        last_err = f"rc={result.returncode}: {result.stderr} | stdout={result.stdout[:200]}"
        if attempt < retries - 1:
            time.sleep(delay)
    raise RuntimeError(f"ClickHouse query failed after {retries} attempts: {last_err}")
    return json.loads(result.stdout)

def fetch_ch_metrics():
    print("  [CH] Fetching ClickHouse metrics...")
    sql = """
    SELECT
        accountId AS account_id,
        COUNT() AS total_convos,
        COUNTIf(createdAt >= now() - INTERVAL 7 DAY) AS convos_7d,
        COUNTIf(createdAt >= now() - INTERVAL 14 DAY AND createdAt < now() - INTERVAL 7 DAY) AS convos_prev_7d,
        COUNTIf(createdAt >= now() - INTERVAL 30 DAY) AS convos_30d,
        COUNTIf(createdAt >= now() - INTERVAL 60 DAY AND createdAt < now() - INTERVAL 30 DAY) AS convos_prev_30d,
        COUNTIf(createdAt >= now() - INTERVAL 90 DAY) AS convos_90d,
        -- message counts from conversations table are unreliable (often 0)
        -- real message metrics computed from messages table below
        0 AS messages_7d,
        0 AS bot_msgs,
        0 AS agent_msgs,
        COUNTIf(resolvedAt IS NOT NULL AND createdAt >= now() - INTERVAL 7 DAY)  AS resolved_7d,
        COUNTIf(resolvedAt IS NOT NULL AND createdAt >= now() - INTERVAL 30 DAY) AS resolved_30d,
        AVGIf(firstRespondedInMilliSeconds, firstRespondedAt IS NOT NULL AND createdAt >= now() - INTERVAL 30 DAY) / 1000 AS avg_frt_secs,
        MAX(createdAt) AS last_convo_at,
        COUNT(DISTINCT channelType) AS channel_types_used
    FROM default.conversations
    WHERE accountId != ''
    GROUP BY accountId
    """
    rows = ch_query(sql).get("data", [])

    sql2 = """
    SELECT accountId AS account_id,
        COUNT(DISTINCT assigneeId) AS active_agents,
        COUNT(DISTINCT botId) AS active_bots
    FROM default.conversations
    WHERE createdAt >= now() - INTERVAL 30 DAY AND accountId != ''
    GROUP BY accountId
    """
    team_rows = ch_query(sql2).get("data", [])
    team_map = {r["account_id"]: r for r in team_rows}

    sql3 = """
    SELECT accountId AS account_id,
        COUNTIf(isDeleted = 'false' OR isDeleted = '') AS total_channels,
        COUNTIf(channelType = 'whatsapp' AND (isDeleted = 'false' OR isDeleted = '')) AS whatsapp_channels
    FROM default.channels WHERE accountId != ''
    GROUP BY accountId
    """
    ch_rows = ch_query(sql3).get("data", [])
    ch_map = {r["account_id"]: r for r in ch_rows}

    # Bot ratio + message counts from messages table (accurate — conversations.messageCount_* unreliable)
    sql_msgs = """
    SELECT
        accountId,
        COUNTIf(createdAt >= now() - INTERVAL 7 DAY)  AS messages_7d,
        COUNTIf(createdAt >= now() - INTERVAL 30 DAY) AS messages_30d,
        COUNTIf(botId != '' AND createdAt >= now() - INTERVAL 30 DAY) AS bot_messages_30d,
        COUNTIf(botId  = '' AND sender NOT IN ('', 'system') AND createdAt >= now() - INTERVAL 30 DAY) AS agent_messages_30d
    FROM default.messages
    WHERE accountId != ''
      AND createdAt >= now() - INTERVAL 30 DAY
    GROUP BY accountId
    """
    msg_rows = ch_query(sql_msgs).get("data", [])
    msg_map = {r["accountId"]: r for r in msg_rows}
    print(f"      {len(msg_map)} accounts with message data")

    # Unique new contacts reached — DISTINCT contactId where isNewContactConversation = true
    sql_contacts = """
    SELECT
        accountId,
        COUNTDistinctIf(contactId, createdAt >= now() - INTERVAL 7 DAY  AND isNewContactConversation = true AND contactId != '') AS new_contacts_7d,
        COUNTDistinctIf(contactId, createdAt >= now() - INTERVAL 30 DAY AND isNewContactConversation = true AND contactId != '') AS new_contacts_30d,
        COUNTDistinctIf(contactId, createdAt >= now() - INTERVAL 90 DAY AND isNewContactConversation = true AND contactId != '') AS new_contacts_90d
    FROM default.conversations
    WHERE accountId != ''
      AND createdAt >= now() - INTERVAL 90 DAY
    GROUP BY accountId
    """
    contact_rows = ch_query(sql_contacts).get("data", [])
    contact_map = {r["accountId"]: r for r in contact_rows}

    # Total unique contacts ever reached — uses uniq() (HyperLogLog, ~2% error, all-time, fast)
    sql_total = """
    SELECT accountId, uniq(contactId) AS total_contacts
    FROM default.conversations
    WHERE accountId != '' AND contactId != ''
    GROUP BY accountId
    """
    total_rows = ch_query(sql_total).get("data", [])
    total_map = {r["accountId"]: int(r["total_contacts"]) for r in total_rows}

    # Open backlog % — OPEN convos / total convos (30d). High = team overwhelmed
    sql_backlog = """
    SELECT accountId,
        round(COUNTIf(status = 'OPEN') / COUNT() * 100, 1) AS open_backlog_pct,
        COUNT() AS total_c
    FROM default.conversations
    WHERE createdAt >= now() - INTERVAL 30 DAY AND accountId != ''
    GROUP BY accountId
    """
    # suppress backlog % for accounts with < 10 convos (noise)
    _backlog_raw = {r["accountId"]: (float(r["open_backlog_pct"] or 0), int(r.get("total_c", 0) or 0))
                    for r in ch_query(sql_backlog).get("data", [])}
    backlog_map = {aid: pct if cnt >= 10 else None for aid, (pct, cnt) in _backlog_raw.items()}

    # Contact-initiated ratio — real inbound demand vs one-way broadcast
    sql_ci = """
    SELECT accountId,
        round(COUNTIf(isContactInitiated = true) / COUNT() * 100, 1) AS contact_initiated_pct
    FROM default.conversations
    WHERE createdAt >= now() - INTERVAL 30 DAY AND accountId != ''
    GROUP BY accountId
    """
    ci_map = {r["accountId"]: float(r["contact_initiated_pct"] or 0)
              for r in ch_query(sql_ci).get("data", [])}

    # Marketing / Utility / Service message mix + template sends + new outbound metrics (30d)
    sql_mix = """
    SELECT accountId,
        COUNTIf(whatsapp_conversation_origin_type = 'marketing')  AS marketing_msgs,
        COUNTIf(whatsapp_conversation_origin_type = 'utility')    AS utility_msgs,
        COUNTIf(whatsapp_conversation_origin_type = 'service')    AS service_msgs,
        COUNTIf(whatsapp_template_templateId != '')               AS template_sends,
        COUNT()                                                   AS total_msgs_30d,
        COUNTIf(whatsapp_conversation_origin_type IN ('marketing','utility')) AS proactive_msgs_30d,
        -- broadcasts = marketing + utility (proactive outbound), same as proactive_msgs_30d
        COUNTIf(whatsapp_conversation_origin_type IN ('marketing','utility')) AS broadcasts_30d,
        0                                                         AS sequences_active
    FROM default.messages
    WHERE createdAt >= now() - INTERVAL 30 DAY AND accountId != ''
    GROUP BY accountId
    """
    mix_map = {r["accountId"]: r for r in ch_query(sql_mix).get("data", [])}
    print(f"      {len(backlog_map)} accounts with backlog data, {len(mix_map)} with message mix data")

    # Daily trend for consistency
    sql4 = """
    SELECT accountId AS account_id, toDate(createdAt) AS day, COUNT() AS convos
    FROM default.conversations
    WHERE createdAt >= now() - INTERVAL 30 DAY AND accountId != ''
    GROUP BY accountId, day
    """
    daily_rows = ch_query(sql4).get("data", [])
    daily_map = {}
    for r in daily_rows:
        daily_map.setdefault(r["account_id"], []).append(int(r["convos"]))

    result = {}
    for r in rows:
        aid = r["account_id"]
        team = team_map.get(aid, {})
        chan = ch_map.get(aid, {})
        daily = daily_map.get(aid, [])
        contacts = contact_map.get(aid, {})
        total_contacts = total_map.get(aid, 0)
        msgs = msg_map.get(aid, {})
        mix = mix_map.get(aid, {})
        c7 = int(r.get("convos_7d", 0) or 0)
        active_days = sum(1 for c in daily[-14:] if c > 0)
        trend = round(active_days / min(len(daily[-14:]), 14) * 100) if daily else 0
        # Use messages table for accurate bot/agent counts
        bot   = int(msgs.get("bot_messages_30d", 0) or 0)
        agent = int(msgs.get("agent_messages_30d", 0) or 0)
        msg7d = int(msgs.get("messages_7d", 0) or 0)
        msg30d= int(msgs.get("messages_30d", 0) or 0)
        c30   = int(r.get("convos_30d", 0) or 0)
        result[aid] = {
            "convos_7d":          c7,
            "convos_prev_7d":     int(r.get("convos_prev_7d", 0) or 0),
            "convos_30d":         c30,
            "convos_prev_30d":    int(r.get("convos_prev_30d", 0) or 0),
            "convos_90d":         int(r.get("convos_90d", 0) or 0),
            "total_convos":       int(r.get("total_convos", 0) or 0),
            "new_contacts_7d":    int(contacts.get("new_contacts_7d", 0) or 0),
            "new_contacts_30d":   int(contacts.get("new_contacts_30d", 0) or 0),
            "new_contacts_90d":   int(contacts.get("new_contacts_90d", 0) or 0),
            "total_contacts":     total_contacts,
            "messages_7d":        msg7d,
            "avg_msgs_per_convo": round(msg30d / c30, 1) if c30 > 0 else 0,
            "bot_ratio":          round(bot / (bot + agent) * 100, 1) if (bot + agent) > 0 else 0,
            "resolved_7d":        int(r.get("resolved_7d", 0) or 0),
            # resolution_rate: use 30d window to match open_backlog_pct (both 30d)
            # suppress if < 10 convos (noise)
            "resolution_rate":    round(int(r.get("resolved_30d", 0) or 0) / c30 * 100, 1) if c30 >= 10 else None,
            "avg_frt_secs":       round(float(r.get("avg_frt_secs", 0) or 0), 0),
            "channel_types":      int(r.get("channel_types_used", 0) or 0),
            "active_agents":      int(team.get("active_agents", 0) or 0),
            "active_bots":        int(team.get("active_bots", 0) or 0),
            "total_channels":     int(chan.get("total_channels", 0) or 0),
            "whatsapp_channels":  int(chan.get("whatsapp_channels", 0) or 0),
            "trend_consistency":  trend,
            "open_backlog_pct":   backlog_map.get(aid, 0),
            "contact_initiated_pct": ci_map.get(aid, 0),
            "marketing_msgs_30d": int(mix.get("marketing_msgs", 0) or 0),
            "utility_msgs_30d":   int(mix.get("utility_msgs", 0) or 0),
            "service_msgs_30d":   int(mix.get("service_msgs", 0) or 0),
            "template_sends_30d": int(mix.get("template_sends", 0) or 0),
            "broadcasts_30d":     int(mix.get("broadcasts_30d", 0) or 0),
            "sequences_active":   int(mix.get("sequences_active", 0) or 0),
            # total_msgs_30d: prefer msg_map (messages table, more accurate) fallback to mix_map
            "total_msgs_30d":     msg30d if msg30d > 0 else int(mix.get("total_msgs_30d", 0) or 0),
            "proactive_msgs_30d": int(mix.get("proactive_msgs_30d", 0) or 0),
            "last_convo_at":      r.get("last_convo_at", ""),
        }
    print(f"      {len(result)} accounts with CH data")
    return result

# ── Zoho Desk signals from PocketBase ─────────────────────────────────────────
def fetch_desk_signals():
    """Load aggregated ticket signals from zoho_tickets table in PocketBase."""
    print("  [Desk] Fetching ticket signals from PocketBase...")
    signals = {}
    page = 1
    while True:
        res, _ = pb("GET", f"/api/collections/zoho_tickets/records?perPage=500&page={page}&fields=account_id,status_type,is_churn_ticket,is_escalated,is_overdue,created_time,priority")
        if not res: break
        for t in res.get("items", []):
            aid = t.get("account_id")
            if not aid: continue
            if aid not in signals:
                signals[aid] = {
                    "total": 0, "open": 0, "churn": 0,
                    "escalated": 0, "overdue": 0, "latest": ""
                }
            s = signals[aid]
            s["total"] += 1
            if t.get("status_type") in ("Open", "On Hold"):
                s["open"] += 1
            if t.get("is_churn_ticket"):
                s["churn"] += 1
            if t.get("is_escalated"):
                s["escalated"] += 1
            if t.get("is_overdue"):
                s["overdue"] += 1
            ct = t.get("created_time", "")
            if ct > s["latest"]:
                s["latest"] = ct
        if page >= res.get("totalPages", 1): break
        page += 1
    print(f"      {len(signals)} accounts with Desk signals")
    return signals

# ── Zoho CRM KAM signals from PocketBase ──────────────────────────────────────
def fetch_crm_signals():
    """Load KAM/CRM signals already synced into PocketBase accounts table."""
    print("  [CRM] Loading CRM signals from PocketBase accounts...")
    # We'll load these per-account during scoring
    # But also fetch KAM module for richer signals
    crm = {}
    token = get_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    fields = "Gallabox_Account_Id,Owner,KAM_Status,Segmentation,ICP_Non_ICP,Expansion_Scope,Upgrade_Possibility2,Account_Status,Email_1"
    page = 1
    while True:
        url = f"https://www.zohoapis.in/crm/v3/KAM?per_page=200&page={page}&fields={fields}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 400:
                print(f"      Zoho API limit reached at page {page} (max 2000 records per module)")
            else:
                print(f"      Zoho CRM fetch error at page {page}: HTTP {e.code}")
            break
        except Exception as e:
            print(f"      Zoho CRM fetch error at page {page}: {e}")
            break
        records = data.get("data", [])
        if not records: break
        for rec in records:
            gb_id = (rec.get("Gallabox_Account_Id") or "").lower().strip()
            if not gb_id: continue
            crm[gb_id] = {
                "kam_owner":          (rec.get("Owner") or {}).get("name", ""),
                "kam_status":         rec.get("KAM_Status") or "",
                "segmentation":       rec.get("Segmentation") or "",
                "icp":                rec.get("ICP_Non_ICP") or "",
                "expansion_scope":    rec.get("Expansion_Scope") or "",
                "upgrade_possible":   bool(rec.get("Upgrade_Possibility2")),
                "account_status":     rec.get("Account_Status") or "",
            }
        if not data.get("info", {}).get("more_records", False): break
        page += 1
        time.sleep(0.2)
    print(f"      {len(crm)} accounts with CRM/KAM signals")
    return crm

# ── SCORING MODEL v3 ──────────────────────────────────────────────────────────
def compute_scores_v3(billing, ch, desk, crm):
    """
    4-source churn + upsell scoring.

    CHURN (0-100):
      Chargebee  35pts — status, MRR zero, non-renewing
      ClickHouse 35pts — usage drop, inactivity, low engagement
      Desk       20pts — open tickets, churn tickets, escalations
      CRM        10pts — ICP fit, KAM status flags

    UPSELL (0-100):
      Chargebee  20pts — plan tier, MRR room
      ClickHouse 50pts — volume growth, bot adoption, multi-channel
      Desk        5pts — engagement through support (negative signal if many churn tickets)
      CRM        25pts — expansion scope, upgrade possibility, segmentation, ICP
    """
    status    = billing.get("status", "unknown")
    mrr_inr   = billing.get("mrr_inr", 0)
    mrr       = billing.get("mrr", 0)
    currency  = billing.get("currency", "INR")
    plan      = (billing.get("plan") or "").lower()

    # Lifecycle & renewal
    account_age_days = billing.get("account_age_days", 999)
    days_to_renewal  = billing.get("days_to_renewal", 999)
    if account_age_days < 60:
        lifecycle = "new"       # < 2 months: onboarding grace
    elif account_age_days < 180:
        lifecycle = "ramping"   # 2–6 months: still growing
    else:
        lifecycle = "mature"    # 6+ months: established pattern

    c7        = ch.get("convos_7d", 0)
    p7        = ch.get("convos_prev_7d", 0)
    c30       = ch.get("convos_30d", 0)
    c_prev30  = ch.get("convos_prev_30d", 0)
    c90       = ch.get("convos_90d", 0)
    avg_msgs  = ch.get("avg_msgs_per_convo", 0)
    bot_ratio = ch.get("bot_ratio", 0)
    frt       = ch.get("avg_frt_secs", 0)
    res_rate  = ch.get("resolution_rate", 0)
    agents    = ch.get("active_agents", 0)
    bots      = ch.get("active_bots", 0)
    channels  = ch.get("total_channels", 0)
    trend     = ch.get("trend_consistency", 0)
    ch_types  = ch.get("channel_types", 0)
    has_ch    = c30 > 0

    wow = round((c7 - p7) / p7 * 100, 1) if p7 > 0 else 0

    # Feature adoption depth — how many distinct product capabilities are in use
    features_used = sum([
        1 if bot_ratio > 5 else 0,
        1 if ch.get("broadcasts_30d", 0) > 0 else 0,
        1 if ch.get("sequences_active", 0) > 0 else 0,
        1 if ch_types >= 2 else 0,
        1 if ch.get("template_sends_30d", 0) > 0 else 0,
    ])

    d_open      = desk.get("open", 0)
    d_churn     = desk.get("churn", 0)
    d_escalated = desk.get("escalated", 0)
    d_overdue   = desk.get("overdue", 0)
    d_total     = desk.get("total", 0)

    icp             = (crm.get("icp") or "").lower()
    expansion       = (crm.get("expansion_scope") or "").lower()
    upgrade_poss    = crm.get("upgrade_possible", False)
    segmentation    = (crm.get("segmentation") or "").lower()
    kam_status      = (crm.get("kam_status") or "").lower()

    churn_reasons  = []
    upsell_reasons = []
    churn  = 0
    upsell = 0

    # ════════════════════════════════════════════════════
    # CHURN SCORE
    # ════════════════════════════════════════════════════

    # ── Source 1: Chargebee (max 35) ──
    if status == "cancelled":
        churn += 35
        churn_reasons.append("Subscription cancelled")
    elif status == "non_renewing":
        churn += 28
        churn_reasons.append("Set to non-renew — churning at period end")
    elif status == "paused":
        churn += 20
        churn_reasons.append("Subscription paused")
    elif status == "in_trial":
        churn += 8
        churn_reasons.append("In trial — conversion not confirmed")

    is_credits_plan = "message-credits" in plan or "message credits" in plan
    if mrr_inr == 0 and status not in ("in_trial", "cancelled") and not is_credits_plan:
        churn += 8
        churn_reasons.append("Zero MRR — no financial commitment")
    elif mrr_inr > 50000:
        churn -= 8   # sticky high-value customer
    elif mrr_inr > 20000:
        churn -= 5

    # ── Source 2: ClickHouse — lifecycle-aware usage scoring ──
    #
    # Two buckets:
    #   ch_hard — absolute signals (zero usage, dropout, no channels): ALWAYS full weight
    #             A new account that never uses the product is a real problem regardless of age.
    #   ch_soft — relative signals (below baseline, engagement quality): lifecycle-scaled
    #             A new account genuinely needs time to ramp — don't penalise for not hitting 500/mo yet.
    ch_hard = 0; ch_hard_reasons = []
    ch_soft = 0; ch_soft_reasons = []

    if has_ch:
        # ── Weekly activity ──
        # Complete dropout (had real activity, now 0) → hard: real signal at any age
        if c7 == 0 and p7 > 10:
            ch_hard += 28
            ch_hard_reasons.append(f"Complete dropout — 0 convos this week (had {p7} last week)")
        elif c7 == 0 and c30 > 0:
            # Quiet this week but active this month → soft: could be normal week variation for new accounts
            ch_soft += 18
            ch_soft_reasons.append("No activity this week (was active this month)")
        elif c7 == 0:
            ch_soft += 10
            ch_soft_reasons.append("No conversations this week")

        # ── No channels configured → hard: onboarding blocker at any age ──
        if channels == 0:
            ch_hard += 8
            ch_hard_reasons.append("No channels configured")

        # ── WoW decline (only when c7 > 0) → soft ──
        if c7 > 0:
            if wow < -60:
                ch_soft += 20
                ch_soft_reasons.append(f"Severe usage drop — {abs(wow):.0f}% WoW decline")
            elif wow < -40:
                ch_soft += 14
                ch_soft_reasons.append(f"Major usage drop — {abs(wow):.0f}% WoW")
            elif wow < -20:
                ch_soft += 8
                ch_soft_reasons.append(f"Usage declining — {abs(wow):.0f}% WoW")
            elif wow > 20 and c7 > 10:
                ch_soft -= 8

        # ── Month-over-month trend → soft ──
        if c_prev30 > 0:
            mom_trend = round((c30 - c_prev30) / c_prev30 * 100, 1)
            if mom_trend < -50:
                ch_soft += 18
                ch_soft_reasons.append(f"Sharp MoM decline — {abs(mom_trend):.0f}% drop vs last month")
            elif mom_trend < -25:
                ch_soft += 10
                ch_soft_reasons.append(f"Month-over-month decline — {abs(mom_trend):.0f}% drop vs last month")
            elif mom_trend > 30 and c30 > 50:
                ch_soft -= 8

        # ── 30d global baseline → soft (new accounts need time to ramp) ──
        BASELINE_30D = 500
        if c30 >= BASELINE_30D:
            ch_soft -= 8
        elif c30 >= BASELINE_30D * 0.75:
            ch_soft += 3
            ch_soft_reasons.append(f"Slightly below 30d baseline — {c30} convos (target {BASELINE_30D})")
        elif c30 >= BASELINE_30D * 0.50:
            ch_soft += 8
            ch_soft_reasons.append(f"Below 30d baseline — {c30} convos (target {BASELINE_30D})")
        elif c30 >= BASELINE_30D * 0.25:
            ch_soft += 14
            ch_soft_reasons.append(f"Significantly below baseline — {c30}/{BASELINE_30D} convos in 30d")
        elif c30 > 0:
            ch_soft += 18
            ch_soft_reasons.append(f"Critical — only {c30} convos in 30d (baseline: {BASELINE_30D})")

        # ── 90-day zombie check → soft ──
        if c90 < 30 and c30 > 0:
            ch_soft += 12
            ch_soft_reasons.append(f"Sustained low usage — only {c90} convos in 90d")
        elif c90 < 75 and c30 > 0:
            ch_soft += 6
            ch_soft_reasons.append(f"Chronically below baseline — {c90} convos in 90d")

        # ── Feature adoption depth → soft ──
        if features_used == 0 and c30 > 20:
            ch_soft += 8
            ch_soft_reasons.append("Inbox-only usage — no automation or outbound features adopted")
        elif features_used >= 3:
            ch_soft -= 8
        elif features_used >= 2:
            ch_soft -= 4

        # ── Engagement quality → soft ──
        if c7 > 0 and avg_msgs < 3:
            ch_soft += 6
            ch_soft_reasons.append(f"Shallow engagement — {avg_msgs:.1f} msgs/convo avg")
        if trend < 30 and c30 > 0:
            ch_soft += 8
            ch_soft_reasons.append(f"Inconsistent usage — active only {trend}% of days")
        if frt > 600 and c30 > 20:
            ch_soft += 5
            ch_soft_reasons.append(f"Slow response time — {frt/60:.0f} min avg FRT")
    else:
        # Zero conversations — hard signal regardless of account age
        if status == "active" and mrr_inr > 0:
            ch_hard += 35
            ch_hard_reasons.append("Active paying account with zero product usage")
        else:
            ch_hard += 25
            ch_hard_reasons.append("No product usage recorded")

    # ── Lifecycle scaling (soft signals only) ──
    if lifecycle == "new":
        ch_soft_scale = 0.4
        if ch_soft > 0:
            ch_soft_reasons.insert(0, f"New account ({int(account_age_days)}d old) — ramp signals at 40%")
    elif lifecycle == "ramping":
        ch_soft_scale = 0.7
        if ch_soft > 0:
            ch_soft_reasons.insert(0, f"Growing account ({int(account_age_days)}d old) — ramp signals at 70%")
    else:
        ch_soft_scale = 1.0

    churn += ch_hard + round(ch_soft * ch_soft_scale)
    churn_reasons.extend(ch_hard_reasons)
    churn_reasons.extend(ch_soft_reasons)

    # ── Source 3: Zoho Desk (max 20) ──
    if d_churn > 0:
        pts = min(d_churn * 8, 16)
        churn += pts
        churn_reasons.append(f"{d_churn} churn/cancellation ticket{'s' if d_churn > 1 else ''} raised")
    if d_escalated > 0:
        churn += min(d_escalated * 4, 8)
        churn_reasons.append(f"{d_escalated} escalated ticket{'s' if d_escalated > 1 else ''}")
    if d_open > 3:
        churn += 6
        churn_reasons.append(f"{d_open} open tickets — high support load")
    elif d_open > 0:
        churn += 3
    if d_overdue > 0:
        churn += min(d_overdue * 3, 6)
        churn_reasons.append(f"{d_overdue} overdue ticket{'s' if d_overdue > 1 else ''}")

    # ── Source 4: Zoho CRM (max 10) ──
    if "at risk" in kam_status or "churned" in kam_status:
        churn += 10
        churn_reasons.append(f"KAM flagged account status: {crm.get('kam_status')}")
    elif "churning" in kam_status:
        churn += 8
        churn_reasons.append("KAM status: churning")
    if icp == "non-icp" or icp == "non icp":
        churn += 5
        churn_reasons.append("Non-ICP account — lower retention likelihood")

    # ── Renewal proximity urgency ──
    # An account going quiet close to renewal is the highest-risk window
    if days_to_renewal <= 30 and churn >= 15:
        churn += 10
        churn_reasons.append(f"Renewal in {int(days_to_renewal)} days — elevated risk window")
    elif days_to_renewal <= 60 and churn >= 20:
        churn += 5
        churn_reasons.append(f"Renewal approaching in {int(days_to_renewal)} days")

    # ── Billing status churn floor ──
    # Prevents CH sticky bonuses from zeroing out strong billing signals.
    # A non-renewing/paused account must always surface to the CS team,
    # regardless of how good the product usage looks.
    STATUS_FLOORS = {"non_renewing": 20, "paused": 12, "in_trial": 5}
    floor = STATUS_FLOORS.get(status, 0)
    if floor and churn < floor:
        churn_reasons.append(f"{status.replace('_', ' ').title()} — minimum risk floor applied ({floor} pts)")
        churn = floor

    churn = max(0, min(int(churn), 100))

    # ════════════════════════════════════════════════════
    # UPSELL SCORE
    # ════════════════════════════════════════════════════

    if status not in ("active", "in_trial"):
        upsell = 0
    else:
        # ── Source 1: Chargebee (max 20) ──
        is_low_plan = any(k in plan for k in ["free","trial","starter","basic","growth","zone","credit","lite"])
        if is_low_plan:
            upsell += 10
            upsell_reasons.append("Entry-tier plan — upgrade path available")
            if c7 > 100:
                upsell += 8
                upsell_reasons.append("High usage on low plan — likely hitting limits")
        elif 0 < mrr_inr < 5000:
            upsell += 6
            upsell_reasons.append("Low MRR with room to expand")

        # ── Source 2: ClickHouse (max 50) ──
        if c7 > 1000:
            upsell += 25
            upsell_reasons.append(f"Very high volume — {c7} convos/week")
        elif c7 > 500:
            upsell += 18
            upsell_reasons.append(f"High volume — {c7} convos/week")
        elif c7 > 200:
            upsell += 12
            upsell_reasons.append(f"Strong volume — {c7} convos/week")
        elif c7 > 50:
            upsell += 6
            upsell_reasons.append(f"Good volume — {c7} convos/week")

        if wow > 50:
            upsell += 15
            upsell_reasons.append(f"Explosive growth — +{wow:.0f}% WoW")
        elif wow > 25:
            upsell += 10
            upsell_reasons.append(f"Strong growth — +{wow:.0f}% WoW")
        elif wow > 10:
            upsell += 5
            upsell_reasons.append(f"Growing — +{wow:.0f}% WoW")

        if bot_ratio > 60 and c7 > 50:
            upsell += 8
            upsell_reasons.append(f"High bot adoption ({bot_ratio:.0f}%) — automation buyer")
        elif bot_ratio > 30:
            upsell += 4

        if ch_types >= 3:
            upsell += 8
            upsell_reasons.append(f"Multi-channel power user — {ch_types} channel types")
        elif ch_types == 2:
            upsell += 4

        if agents > 5:
            upsell += 6
            upsell_reasons.append(f"Large team — {agents} active agents")
        elif agents > 2:
            upsell += 3

        # ── Source 2 (cont): Gallabox-native growth signals ──
        new_c30   = int(ch.get("new_contacts_30d", 0) or 0)
        proactive = int(ch.get("proactive_msgs_30d", 0) or 0)

        if new_c30 > 500:
            upsell += 8
            upsell_reasons.append(f"Rapid contact reach — {new_c30:,} new contacts this month")
        elif new_c30 > 200:
            upsell += 4
            upsell_reasons.append(f"Growing contact reach — {new_c30:,} new contacts this month")

        if proactive > 5000:
            upsell += 10
            upsell_reasons.append(f"Heavy campaign user — {proactive:,} proactive messages in 30d")
        elif proactive > 1000:
            upsell += 5
            upsell_reasons.append(f"Active campaigns — {proactive:,} proactive messages in 30d")

        # ── Source 3: Desk (max 5) ──
        # Many support tickets = engaged but struggling — still an upsell signal if no churn tickets
        if d_total > 5 and d_churn == 0:
            upsell += 3
            upsell_reasons.append(f"High support engagement ({d_total} tickets) — invested customer")
        if d_churn > 0:
            upsell -= 5  # Churn tickets dampen upsell

        # ── Source 4: CRM/KAM (max 25) ──
        if expansion == "yes":
            upsell += 15
            upsell_reasons.append("KAM confirmed expansion scope — active upsell opportunity")
        elif expansion == "maybe":
            upsell += 8
            upsell_reasons.append("KAM flagged potential expansion")

        if upgrade_poss:
            upsell += 10
            upsell_reasons.append("KAM marked upgrade possibility")

        if icp == "icp":
            upsell += 8
            upsell_reasons.append("ICP account — ideal expansion candidate")

        if "enterprise" in segmentation or "large" in segmentation:
            upsell += 5
            upsell_reasons.append(f"Enterprise segment — higher ACV potential")
        elif "mid" in segmentation or "smb" in segmentation:
            upsell += 2

        if "churning" in kam_status or "at risk" in kam_status:
            upsell -= 10  # KAM flagged as at risk — don't upsell

    upsell = max(0, min(int(upsell), 100))

    # ── Health classification ──
    if status == "cancelled":
        health = "red"
    elif churn >= 50:
        health = "red"
    elif churn >= 25 or (d_churn > 0 and wow < -20):
        health = "yellow"
    else:
        health = "green"

    # Override: a "Critical" churn reason must never show as Healthy
    if health == "green" and any("Critical" in r for r in churn_reasons):
        health = "yellow"

    # Override: renewal within 30 days + any real churn signal → minimum Warning
    if health == "green" and days_to_renewal <= 30 and churn >= 15:
        health = "yellow"

    # Override: non_renewing is a definitive churn decision — must never show Healthy
    if health == "green" and status == "non_renewing":
        health = "yellow"

    # ── Explanation ──
    if mrr > 0:
        sym = {"INR": "₹", "USD": "$", "AED": "AED ", "EUR": "€", "GBP": "£"}.get(currency, f"{currency} ")
        mrr_s = f"{sym}{mrr:,.0f}/mo"
    else:
        mrr_s = "free"

    act = f"{c7} convos/wk" if c7 > 0 else "no activity"
    if wow != 0 and c7 > 0:
        act += f" ({wow:+.0f}% WoW)"

    desk_note = ""
    if d_churn > 0:
        desk_note = f" {d_churn} cancellation ticket(s)."
    elif d_open > 0:
        desk_note = f" {d_open} open ticket(s)."

    crm_note = ""
    if expansion == "yes":
        crm_note = " Expansion confirmed by KAM."
    elif upgrade_poss:
        crm_note = " Upgrade flagged by KAM."

    if health == "red":
        exp = f"HIGH RISK ({churn}%). {status.upper()} @ {mrr_s}. {act}.{desk_note} Urgent CSM action needed."
    elif health == "yellow":
        exp = f"AT RISK ({churn}%). {status} @ {mrr_s}. {act}.{desk_note} Proactive check-in recommended."
    else:
        up = f" Upsell: {upsell}%.{crm_note}" if upsell >= 30 else ""
        exp = f"Healthy ({churn}% churn risk). {status} @ {mrr_s}. {act}.{desk_note}{up}"

    return {
        "churn_score":       churn,
        "upsell_score":      upsell,
        "health":            health,
        "explanation":       exp,
        "churn_reasons":     churn_reasons,
        "upsell_reasons":    upsell_reasons,
        "convos_7d":         c7,
        "convos_30d":        c30,
        "wow_delta":         wow,
        "messages_7d":       ch.get("messages_7d", 0),
        "avg_msgs_per_convo":ch.get("avg_msgs_per_convo", 0),
        "bot_ratio":         bot_ratio,
        "resolution_rate":   res_rate,
        "avg_frt_secs":      frt,
        "active_agents":     agents,
        "active_bots":       bots,
        "total_channels":    channels,
        "trend_consistency": trend,
        "baseline_pct":      round(c30 / 500 * 100) if c30 > 0 else 0,
        "convos_90d":           ch.get("convos_90d", 0),
        "convos_prev_30d":      ch.get("convos_prev_30d", 0),
        "new_contacts_7d":      ch.get("new_contacts_7d", 0),
        "new_contacts_30d":     ch.get("new_contacts_30d", 0),
        "new_contacts_90d":     ch.get("new_contacts_90d", 0),
        "total_contacts":       ch.get("total_contacts", 0),
        "open_backlog_pct":     ch.get("open_backlog_pct", 0),
        "contact_initiated_pct":ch.get("contact_initiated_pct", 0),
            "marketing_msgs_30d":   ch.get("marketing_msgs_30d", 0),
            "utility_msgs_30d":     ch.get("utility_msgs_30d", 0),
            "service_msgs_30d":     ch.get("service_msgs_30d", 0),
            "template_sends_30d":   ch.get("template_sends_30d", 0),
            "broadcasts_30d":       ch.get("broadcasts_30d", 0),
            "sequences_active":     ch.get("sequences_active", 0),
            "total_msgs_30d":       ch.get("total_msgs_30d", 0),
            "proactive_msgs_30d":   ch.get("proactive_msgs_30d", 0),
    }

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Gallabox Churn v3 — 4-Source Scoring")
    print("  Sources: Chargebee + ClickHouse + Zoho Desk + Zoho CRM")
    print("=" * 60)

    pb_auth()
    print("✓ PocketBase auth OK")

    _subs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "subs_live.json")
    try:
        subs = json.load(open(_subs_path))
        print(f"✓ {len(subs)} Chargebee subscriptions loaded")
    except FileNotFoundError:
        print("⚠ No data/subs_live.json — run fetch_subs.py first")
        subs = {}
    except Exception as e:
        print(f"⚠ Failed to load subs_live.json: {e}")
        subs = {}

    print("\nFetching data from all 4 sources...")
    ch_data   = fetch_ch_metrics()
    desk_data = fetch_desk_signals()
    crm_data  = fetch_crm_signals()
    print()

    stats = {"green": 0, "yellow": 0, "red": 0, "total": 0, "skipped": 0}
    mrr_at_risk = 0
    mrr_total   = 0
    scored_at   = datetime.now().isoformat()
    page = 1

    print("Scoring accounts...")
    while True:
        res, _ = pb("GET", f"/api/collections/accounts/records?perPage=200&page={page}")
        if not res or not res.get("items"):
            break

        for acc in res["items"]:
            cb_id  = acc.get("chargebee_id", "")
            amp_id = (acc.get("amplitude_id") or "").lower()

            sub    = subs.get(cb_id, {})
            status = sub.get("status", acc.get("status", "unknown"))
            VALID  = {"active", "in_trial", "non_renewing", "paused"}
            if status not in VALID:
                stats["skipped"] += 1
                continue

            mrr_cents  = sub.get("mrr", 0)
            mrr_native = mrr_cents / 100 if sub else acc.get("mrr", 0)
            currency   = sub.get("currency", acc.get("currency", "INR"))
            mrr_inr    = to_inr(mrr_native, currency)
            mrr_total += mrr_inr

            # Account age from Chargebee creation timestamp
            try:
                cb_ts = int(acc.get("cb_created_at", 0) or 0)
                account_age_days = max(0, (time.time() - cb_ts) / 86400) if cb_ts > 0 else 999
            except Exception:
                account_age_days = 999

            # Days until next renewal/billing date
            try:
                nba = int(sub.get("next_billing_at", 0) or 0)
                days_to_renewal = max(0, (nba - time.time()) / 86400) if nba > 0 else 999
            except Exception:
                days_to_renewal = 999

            billing = {
                "mrr":              mrr_native,
                "mrr_inr":          mrr_inr,
                "currency":         currency,
                "status":           status,
                "plan":             sub.get("plan", acc.get("plan", "")),
                "account_age_days": account_age_days,
                "days_to_renewal":  days_to_renewal,
            }

            # Pull data from all 4 sources
            ch   = ch_data.get(amp_id, {})
            desk = desk_data.get(acc["id"], {})      # matched by PB account id
            crm  = crm_data.get(amp_id, {})          # matched by Gallabox_Account_Id = amplitude_id

            sc = compute_scores_v3(billing, ch, desk, crm)
            stats[sc["health"]] += 1
            stats["total"] += 1
            if sc["health"] in ("red", "yellow"):
                mrr_at_risk += mrr_inr

            # Update billing fields
            if sub:
                pb("PATCH", f"/api/collections/accounts/records/{acc['id']}", {
                    "plan": billing["plan"][:100],
                    "status": status,
                    "mrr": mrr_native,
                    "mrr_inr": mrr_inr,
                    "currency": currency,
                })

            # Upsert score record
            score_data = {
                "account_id":       acc["id"],
                "churn_score":      sc["churn_score"],
                "upsell_score":     sc["upsell_score"],
                "health":           sc["health"],
                "explanation":      sc["explanation"],
                "churn_reasons":    sc["churn_reasons"],
                "upsell_reasons":   sc["upsell_reasons"],
                "scored_at":        scored_at,
                "convos_7d":        sc["convos_7d"],
                "convos_30d":       sc["convos_30d"],
                "wow_delta":        sc["wow_delta"],
                "messages_7d":      sc["messages_7d"],
                "avg_msgs_per_convo": sc["avg_msgs_per_convo"],
                "bot_ratio":        sc["bot_ratio"],
                "resolution_rate":  sc["resolution_rate"],
                "avg_frt_secs":     sc["avg_frt_secs"],
                "active_agents":    sc["active_agents"],
                "active_bots":      sc["active_bots"],
                "total_channels":   sc["total_channels"],
                "trend_consistency":sc["trend_consistency"],
                "convos_90d":       sc["convos_90d"],
                "new_contacts_7d":  sc["new_contacts_7d"],
                "new_contacts_30d": sc["new_contacts_30d"],
                "new_contacts_90d": sc["new_contacts_90d"],
                "total_contacts":        sc["total_contacts"],
                "open_backlog_pct":      sc["open_backlog_pct"],
                "contact_initiated_pct": sc["contact_initiated_pct"],
                "marketing_msgs_30d":    sc["marketing_msgs_30d"],
                "utility_msgs_30d":      sc["utility_msgs_30d"],
                "service_msgs_30d":      sc["service_msgs_30d"],
                "broadcasts_30d":        sc.get("broadcasts_30d", 0),
                "sequences_active":      sc.get("sequences_active", 0),
                "template_sends_30d":    sc["template_sends_30d"],
                "total_msgs_30d":        sc.get("total_msgs_30d", 0),
                "proactive_msgs_30d":    sc.get("proactive_msgs_30d", 0),
            }
            existing, _ = pb("GET", f'/api/collections/churn_scores/records?filter=account_id%3D%22{acc["id"]}%22&perPage=1')
            if existing and existing.get("items"):
                pb("PATCH", f'/api/collections/churn_scores/records/{existing["items"][0]["id"]}', score_data)
            else:
                pb("POST", "/api/collections/churn_scores/records", score_data)

        print(f"  Page {page}: {len(res['items'])} accounts")
        page += 1

    print()
    print("=" * 60)
    print("SCORING COMPLETE — v3 (4-Source Model)")
    print("=" * 60)
    print(f"  Scored:  {stats['total']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  🟢 Healthy:  {stats['green']}")
    print(f"  🟡 At Risk:  {stats['yellow']}")
    print(f"  🔴 Churning: {stats['red']}")
    print(f"  Total MRR (INR):    ₹{mrr_total:,.0f}")
    print(f"  At-Risk MRR (INR):  ₹{mrr_at_risk:,.0f} ({mrr_at_risk/mrr_total*100:.1f}%)" if mrr_total else "")

if __name__ == "__main__":
    main()
