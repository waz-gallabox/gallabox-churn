#!/usr/bin/env python3
"""
Gallabox Churn v2 — Enhanced ClickHouse Scoring
Pulls deeper metrics: FRT, resolution, bot usage, channels, team size, message depth
Properly handles multi-currency MRR with INR conversion
"""
import json, urllib.request, urllib.parse, base64, ssl, os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import PB_BASE, PB_EMAIL, PB_PASSWORD, CH_HOST, CH_USER, CH_PASS

# Currency conversion rates to INR
CURRENCY_RATES = {
    'INR': 1.0,
    'USD': 83.5,   # 1 USD = 83.5 INR
    'AED': 22.7,   # 1 AED = 22.7 INR
    'EUR': 90.0,   # 1 EUR = 90 INR
    'GBP': 105.0,  # 1 GBP = 105 INR
    'SGD': 62.0,   # 1 SGD = 62 INR
    'SAR': 22.3,   # 1 SAR = 22.3 INR
}

def convert_to_inr(amount, currency):
    """Convert amount to INR using exchange rates"""
    rate = CURRENCY_RATES.get(currency, 1.0)
    return amount * rate

# ─────────────────────────────────────────────────────────────────────────────
# PocketBase helpers
# ─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
# ClickHouse helpers
# ─────────────────────────────────────────────────────────────────────────────
def ch_query(sql):
    creds = base64.b64encode(f"{CH_USER}:{CH_PASS}".encode()).decode()
    ctx = ssl.create_default_context()
    req = urllib.request.Request(CH_HOST,
        data=(sql + " FORMAT JSON").encode(),
        headers={"Authorization": f"Basic {creds}", "Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        return json.loads(r.read())

# ─────────────────────────────────────────────────────────────────────────────
# ENHANCED ClickHouse data fetch
# ─────────────────────────────────────────────────────────────────────────────
def fetch_conversation_metrics():
    """Core conversation activity + message depth"""
    print("  [1/5] Fetching conversation metrics...")
    sql = """
    SELECT
        accountId AS account_id,
        
        -- Volume metrics
        COUNT() AS total_convos,
        COUNTIf(createdAt >= now() - INTERVAL 7 DAY) AS convos_7d,
        COUNTIf(createdAt >= now() - INTERVAL 14 DAY AND createdAt < now() - INTERVAL 7 DAY) AS convos_prev_7d,
        COUNTIf(createdAt >= now() - INTERVAL 30 DAY) AS convos_30d,
        
        -- Message depth
        SUM(messageCount_total) AS total_messages,
        SUMIf(messageCount_total, createdAt >= now() - INTERVAL 7 DAY) AS messages_7d,
        AVGIf(messageCount_total, createdAt >= now() - INTERVAL 7 DAY) AS avg_msgs_per_convo_7d,
        
        -- Bot vs human
        SUM(messageCount_bot) AS bot_messages,
        SUM(messageCount_agent) AS agent_messages,
        SUM(messageCount_contact) AS contact_messages,
        
        -- Resolution metrics
        COUNTIf(resolvedAt IS NOT NULL) AS resolved_convos,
        COUNTIf(resolvedAt IS NOT NULL AND createdAt >= now() - INTERVAL 7 DAY) AS resolved_7d,
        AVGIf(timeToResolveInMilliSeconds, resolvedAt IS NOT NULL AND createdAt >= now() - INTERVAL 30 DAY) / 1000 / 60 AS avg_resolution_mins_30d,
        
        -- FRT (First Response Time)
        AVGIf(firstRespondedInMilliSeconds, firstRespondedAt IS NOT NULL AND createdAt >= now() - INTERVAL 30 DAY) / 1000 AS avg_frt_secs_30d,
        
        -- Recency
        MAX(createdAt) AS last_convo_at,
        MAX(updatedAt) AS last_activity_at,
        
        -- Channel diversity
        COUNTIf(channelType = 'whatsapp') AS whatsapp_convos,
        COUNTIf(channelType = 'web') AS web_convos,
        COUNTIf(channelType = 'instagram') AS instagram_convos,
        COUNT(DISTINCT channelType) AS channel_types_used
        
    FROM default.conversations
    WHERE accountId != ''
    GROUP BY accountId
    """
    d = ch_query(sql)
    rows = d.get("data", [])
    print(f"      Got {len(rows)} accounts with conversation data")
    return {r["account_id"]: r for r in rows}

def fetch_team_metrics():
    """Team size and engagement"""
    print("  [2/5] Fetching team/user metrics...")
    sql = """
    SELECT
        c.accountId AS account_id,
        COUNT(DISTINCT c.assigneeId) AS active_agents_30d,
        COUNT(DISTINCT c.userId) AS active_users_30d,
        COUNT(DISTINCT c.botId) AS active_bots_30d
    FROM default.conversations c
    WHERE c.createdAt >= now() - INTERVAL 30 DAY
      AND c.accountId != ''
    GROUP BY c.accountId
    """
    d = ch_query(sql)
    rows = d.get("data", [])
    print(f"      Got {len(rows)} accounts with team data")
    return {r["account_id"]: r for r in rows}

def fetch_channel_metrics():
    """Channel adoption"""
    print("  [3/5] Fetching channel adoption...")
    sql = """
    SELECT
        accountId AS account_id,
        COUNT() AS total_channels,
        COUNTIf(channelType = 'whatsapp') AS whatsapp_channels,
        COUNTIf(channelType = 'web') AS web_channels,
        COUNTIf(channelType = 'instagram') AS instagram_channels,
        COUNTIf(channelType = 'telegram') AS telegram_channels,
        COUNTIf(isDeleted = 'true') AS deleted_channels
    FROM default.channels
    WHERE accountId != ''
    GROUP BY accountId
    """
    d = ch_query(sql)
    rows = d.get("data", [])
    print(f"      Got {len(rows)} accounts with channel data")
    return {r["account_id"]: r for r in rows}

def fetch_account_info():
    """Account metadata from ClickHouse accounts table"""
    print("  [4/5] Fetching account metadata...")
    sql = """
    SELECT
        _id AS account_id,
        name,
        email,
        status AS ch_status,
        onboardingState,
        additionalInfo_employeesCount AS employee_count,
        additionalInfo_jobRole AS job_role,
        tzCode AS timezone
    FROM default.accounts
    WHERE _id != ''
    """
    d = ch_query(sql)
    rows = d.get("data", [])
    print(f"      Got {len(rows)} accounts with metadata")
    return {r["account_id"]: r for r in rows}

def fetch_daily_activity():
    """Daily activity for sparkline (last 30 days)"""
    print("  [5/5] Fetching daily activity trends...")
    sql = """
    SELECT
        accountId AS account_id,
        toDate(createdAt) AS day,
        COUNT() AS convos
    FROM default.conversations
    WHERE createdAt >= now() - INTERVAL 30 DAY
      AND accountId != ''
    GROUP BY accountId, day
    ORDER BY accountId, day
    """
    d = ch_query(sql)
    rows = d.get("data", [])
    
    # Group by account -> list of daily counts
    daily = {}
    for r in rows:
        aid = r["account_id"]
        if aid not in daily:
            daily[aid] = []
        daily[aid].append({"day": r["day"], "count": int(r["convos"])})
    
    print(f"      Got daily trends for {len(daily)} accounts")
    return daily

# ─────────────────────────────────────────────────────────────────────────────
# ENHANCED SCORING MODEL
# ─────────────────────────────────────────────────────────────────────────────
def compute_scores_v2(billing, ch_convos, ch_team, ch_channels, ch_account, daily_trend):
    """
    Enhanced scoring with deeper signals
    """
    # Extract billing data
    mrr = billing.get("mrr", 0)  # Native currency
    mrr_inr = billing.get("mrr_inr", 0)  # INR equivalent
    currency = billing.get("currency", "INR")
    status = billing.get("status", "unknown")
    plan = billing.get("plan", "unknown")
    
    # Extract conversation metrics (with safe defaults)
    c7 = int(ch_convos.get("convos_7d", 0) or 0)
    p7 = int(ch_convos.get("convos_prev_7d", 0) or 0)
    c30 = int(ch_convos.get("convos_30d", 0) or 0)
    total_convos = int(ch_convos.get("total_convos", 0) or 0)
    msgs_7d = int(ch_convos.get("messages_7d", 0) or 0)
    avg_msgs = float(ch_convos.get("avg_msgs_per_convo_7d", 0) or 0)
    bot_msgs = int(ch_convos.get("bot_messages", 0) or 0)
    agent_msgs = int(ch_convos.get("agent_messages", 0) or 0)
    contact_msgs = int(ch_convos.get("contact_messages", 0) or 0)
    resolved_7d = int(ch_convos.get("resolved_7d", 0) or 0)
    avg_frt = float(ch_convos.get("avg_frt_secs_30d", 0) or 0)
    avg_resolution = float(ch_convos.get("avg_resolution_mins_30d", 0) or 0)
    channel_types = int(ch_convos.get("channel_types_used", 0) or 0)
    
    # Team metrics
    active_agents = int(ch_team.get("active_agents_30d", 0) or 0)
    active_users = int(ch_team.get("active_users_30d", 0) or 0)
    active_bots = int(ch_team.get("active_bots_30d", 0) or 0)
    
    # Channel adoption
    total_channels = int(ch_channels.get("total_channels", 0) or 0)
    whatsapp_channels = int(ch_channels.get("whatsapp_channels", 0) or 0)
    
    # Calculated metrics
    wow = round((c7 - p7) / p7 * 100, 1) if p7 > 0 else 0
    resolution_rate = round(resolved_7d / c7 * 100, 1) if c7 > 0 else 0
    bot_ratio = round(bot_msgs / (bot_msgs + agent_msgs) * 100, 1) if (bot_msgs + agent_msgs) > 0 else 0
    has_activity = total_convos > 0
    
    # Calculate trend consistency from daily data
    trend_score = 0
    if daily_trend:
        counts = [d["count"] for d in daily_trend[-14:]]
        if len(counts) >= 7:
            active_days = sum(1 for c in counts if c > 0)
            trend_score = round(active_days / len(counts) * 100)
    
    churn_reasons = []
    upsell_reasons = []
    
    # ── CHURN SCORING ──────────────────────────────────────────────────────────
    churn = 0
    
    # 1. Billing status (strongest signal)
    if status == "cancelled":
        churn += 60
        churn_reasons.append("Subscription cancelled")
    elif status == "non_renewing":
        churn += 45
        churn_reasons.append("Set to non-renew — will churn at period end")
    elif status == "paused":
        churn += 35
        churn_reasons.append("Subscription paused")
    elif status == "in_trial":
        churn += 12
        churn_reasons.append("Still in trial — conversion uncertain")
    
    # 2. Activity signals
    if has_activity:
        if c7 == 0 and p7 > 10:
            churn += 30
            churn_reasons.append(f"Complete dropout — 0 convos this week vs {p7} last week")
        elif c7 == 0 and c30 > 0:
            churn += 22
            churn_reasons.append("No activity this week (was active this month)")
        elif c7 == 0:
            churn += 15
            churn_reasons.append("No conversations recorded this week")
        
        # WoW decline
        if wow < -60:
            churn += 25
            churn_reasons.append(f"Severe usage drop — {abs(wow):.0f}% WoW decline")
        elif wow < -40:
            churn += 18
            churn_reasons.append(f"Major usage drop — {abs(wow):.0f}% WoW decline")
        elif wow < -20:
            churn += 10
            churn_reasons.append(f"Usage declining — {abs(wow):.0f}% WoW")
        
        # Low engagement depth
        if c7 > 0 and avg_msgs < 3:
            churn += 8
            churn_reasons.append(f"Shallow engagement — avg {avg_msgs:.1f} msgs/convo")
        
        # Inconsistent usage pattern
        if trend_score < 30 and c30 > 0:
            churn += 10
            churn_reasons.append(f"Inconsistent usage — active only {trend_score}% of days")
    else:
        churn += 20
        churn_reasons.append("Never activated — no conversation history")
    
    # 3. Product adoption signals
    if total_channels == 0:
        churn += 12
        churn_reasons.append("No channels configured")
    elif whatsapp_channels == 0 and total_channels > 0:
        churn += 5
        churn_reasons.append("No WhatsApp channel (primary use case)")
    
    if active_bots == 0 and c30 > 50:
        churn += 5
        churn_reasons.append("Not using bots despite high volume")
    
    if active_agents <= 1 and c30 > 100:
        churn += 5
        churn_reasons.append("Single agent bottleneck on high volume")
    
    # 4. Support quality degradation
    if avg_frt > 300 and c30 > 20:
        churn += 8
        churn_reasons.append(f"Slow response times — avg {avg_frt/60:.1f} min FRT")
    
    if resolution_rate < 30 and c7 > 10:
        churn += 6
        churn_reasons.append(f"Low resolution rate — only {resolution_rate:.0f}%")
    
    # 5. MRR factor (use INR equivalent for comparison) - high value = stickier
    if mrr_inr > 50000:
        churn -= 15
    elif mrr_inr > 20000:
        churn -= 10
    elif mrr_inr > 5000:
        churn -= 5
    elif mrr_inr == 0 and status not in ["in_trial"]:
        churn += 10
        churn_reasons.append("Zero MRR — no financial commitment")
    
    # Growth reduces churn
    if wow > 30 and c7 > 20:
        churn -= 12
    elif wow > 15 and c7 > 10:
        churn -= 6
    
    churn = max(0, min(int(churn), 100))
    
    # ── UPSELL SCORING ─────────────────────────────────────────────────────────
    upsell = 0
    
    if status in ["active", "in_trial"]:
        # High usage = upsell candidate
        if c7 > 1000:
            upsell += 30
            upsell_reasons.append(f"Very high volume — {c7} convos/week")
        elif c7 > 500:
            upsell += 22
            upsell_reasons.append(f"High volume — {c7} convos/week")
        elif c7 > 200:
            upsell += 15
            upsell_reasons.append(f"Strong volume — {c7} convos/week")
        elif c7 > 50:
            upsell += 8
            upsell_reasons.append(f"Good volume — {c7} convos/week")
        
        # Growth = expanding
        if wow > 50:
            upsell += 20
            upsell_reasons.append(f"Explosive growth — up {wow:.0f}% WoW")
        elif wow > 25:
            upsell += 12
            upsell_reasons.append(f"Strong growth — up {wow:.0f}% WoW")
        elif wow > 10:
            upsell += 6
            upsell_reasons.append(f"Growing — up {wow:.0f}% WoW")
        
        # Low plan + high usage
        plan_l = plan.lower()
        is_low_tier = any(k in plan_l for k in ["free", "trial", "trail", "starter", "basic", "growth", "zone", "credit"])
        
        if is_low_tier:
            upsell += 10
            upsell_reasons.append("On entry-tier plan — upgrade path available")
            if c7 > 100:
                upsell += 12
                upsell_reasons.append("High usage on low plan — likely hitting limits")
        
        # Team expansion signal
        if active_agents > 3:
            upsell += 8
            upsell_reasons.append(f"Growing team — {active_agents} active agents")
        
        # Multi-channel = power user
        if channel_types >= 2:
            upsell += 6
            upsell_reasons.append(f"Multi-channel user — {channel_types} channel types")
        
        # High bot adoption = automation-ready
        if bot_ratio > 50 and c7 > 50:
            upsell += 8
            upsell_reasons.append(f"High bot usage ({bot_ratio:.0f}%) — automation buyer")
        
        # Low MRR + engagement = room to grow (use INR for comparison)
        if 0 < mrr_inr < 5000 and c7 > 30:
            upsell += 8
            upsell_reasons.append("Low MRR with good engagement — revenue expansion opportunity")
        elif mrr_inr == 0 and c7 > 20:
            upsell += 15
            upsell_reasons.append("Active free user — conversion candidate")
    
    upsell = max(0, min(int(upsell), 100))
    
    # ── HEALTH CLASSIFICATION ──────────────────────────────────────────────────
    if status == "cancelled":
        health = "red"
    elif churn >= 50:
        health = "red"
    elif churn >= 25 or (wow < -30 and c7 < 20):
        health = "yellow"
    else:
        health = "green"
    
    # ── EXPLANATION ────────────────────────────────────────────────────────────
    plan_s = (plan or "unknown").replace("-", " ")[:35]
    
    # Format MRR in native currency
    if mrr > 0:
        if currency == "INR":
            mrr_s = f"₹{mrr:,.0f}/mo"
        elif currency == "USD":
            mrr_s = f"${mrr:,.0f}/mo"
        elif currency == "AED":
            mrr_s = f"AED {mrr:,.0f}/mo"
        else:
            mrr_s = f"{mrr:,.0f} {currency}/mo"
    else:
        mrr_s = "free"
    
    activity_parts = []
    if c7 > 0:
        activity_parts.append(f"{c7} convos this week")
        if wow != 0:
            activity_parts.append(f"{wow:+.0f}% WoW")
    else:
        activity_parts.append("no activity this week")
    
    if active_agents > 0:
        activity_parts.append(f"{active_agents} agents")
    if active_bots > 0:
        activity_parts.append(f"{active_bots} bots")
    
    act_s = ", ".join(activity_parts)
    
    if health == "red":
        exp = f"HIGH RISK. {status.upper()} @ {mrr_s}. {act_s}. Action: urgent CSM outreach within 24h."
    elif health == "yellow":
        exp = f"MONITOR. {status} @ {mrr_s}. {act_s}. Action: proactive check-in recommended."
    else:
        up_note = f" Strong upsell candidate ({upsell}%)." if upsell >= 40 else ""
        exp = f"Healthy. {status} @ {mrr_s}. {act_s}.{up_note}"
    
    return {
        "churn_score": churn,
        "upsell_score": upsell,
        "health": health,
        "explanation": exp,
        "churn_reasons": churn_reasons,
        "upsell_reasons": upsell_reasons,
        # Extended metrics for dashboard
        "convos_7d": c7,
        "convos_30d": c30,
        "wow_delta": wow,
        "messages_7d": msgs_7d,
        "avg_msgs_per_convo": round(avg_msgs, 1),
        "bot_ratio": bot_ratio,
        "resolution_rate": resolution_rate,
        "avg_frt_secs": round(avg_frt, 0),
        "active_agents": active_agents,
        "active_bots": active_bots,
        "total_channels": total_channels,
        "trend_consistency": trend_score,
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Gallabox Churn v2 — Enhanced Scoring (Multi-Currency)")
    print("=" * 60)
    print()
    
    # Auth
    token = pb_auth()
    print("✓ PocketBase auth OK\n")
    
    # Load Chargebee billing data
    try:
        subs = json.load(open("/tmp/subs_live.json"))
        print(f"✓ Loaded {len(subs)} Chargebee subscriptions\n")
    except:
        print("⚠ No subs_live.json found — run fetch_subs.py first")
        subs = {}
    
    # Fetch all ClickHouse data
    print("Fetching ClickHouse data...")
    ch_convos = fetch_conversation_metrics()
    ch_teams = fetch_team_metrics()
    ch_channels = fetch_channel_metrics()
    ch_accounts = fetch_account_info()
    ch_daily = fetch_daily_activity()
    print()
    
    # Score all accounts
    stats = {"green": 0, "yellow": 0, "red": 0, "total": 0, "skipped": 0}
    mrr_stats = {"total_inr": 0, "at_risk_inr": 0, "by_currency": {}}
    scored_at = datetime.now().isoformat()
    page = 1
    
    print("Scoring accounts...")
    while True:
        res, err = pb("GET", f"/api/collections/accounts/records?perPage=200&page={page}", token=token)
        if not res or not res.get("items"):
            break
        
        for acc in res["items"]:
            cb_id = acc.get("chargebee_id", "")
            amp_id = acc.get("amplitude_id", "")  # = ClickHouse accountId
            
            sub = subs.get(cb_id, {})
            billing_status = sub.get("status", acc.get("status", "unknown"))
            
            # Only score active/in_trial/non_renewing/paused
            VALID = {"active", "in_trial", "non_renewing", "paused"}
            if billing_status not in VALID:
                stats["skipped"] += 1
                continue
            
            # Get MRR in native currency (Chargebee stores in cents)
            mrr_cents = sub.get("mrr", 0)
            mrr_native = mrr_cents / 100 if sub else acc.get("mrr", 0)
            currency = sub.get("currency", acc.get("currency", "INR"))
            
            # Convert to INR for aggregation and comparison
            mrr_inr = convert_to_inr(mrr_native, currency)
            
            # Track MRR stats
            mrr_stats["total_inr"] += mrr_inr
            if currency not in mrr_stats["by_currency"]:
                mrr_stats["by_currency"][currency] = {"native": 0, "inr": 0, "count": 0}
            mrr_stats["by_currency"][currency]["native"] += mrr_native
            mrr_stats["by_currency"][currency]["inr"] += mrr_inr
            mrr_stats["by_currency"][currency]["count"] += 1
            
            # Build billing dict
            billing = {
                "mrr": mrr_native,      # Native currency amount
                "mrr_inr": mrr_inr,     # INR equivalent for scoring
                "currency": currency,
                "status": billing_status,
                "plan": sub.get("plan", acc.get("plan", "unknown")),
            }
            
            # Get ClickHouse data for this account
            convos = ch_convos.get(amp_id, {})
            team = ch_teams.get(amp_id, {})
            channels = ch_channels.get(amp_id, {})
            account_meta = ch_accounts.get(amp_id, {})
            daily = ch_daily.get(amp_id, [])
            
            # Update account billing fields (store native MRR + INR equivalent)
            if sub:
                pb("PATCH", f"/api/collections/accounts/records/{acc['id']}", {
                    "plan": billing["plan"][:100],
                    "status": billing_status,
                    "mrr": mrr_native,       # Native currency
                    "mrr_inr": mrr_inr,      # INR equivalent
                    "currency": currency,
                }, token=token)
            
            # Compute scores
            sc = compute_scores_v2(billing, convos, team, channels, account_meta, daily)
            stats[sc["health"]] += 1
            stats["total"] += 1
            
            # Track at-risk MRR
            if sc["health"] in ["red", "yellow"]:
                mrr_stats["at_risk_inr"] += mrr_inr
            
            # Store score record
            score_data = {
                "account_id": acc["id"],
                "churn_score": sc["churn_score"],
                "upsell_score": sc["upsell_score"],
                "health": sc["health"],
                "explanation": sc["explanation"],
                "churn_reasons": sc["churn_reasons"],
                "upsell_reasons": sc["upsell_reasons"],
                "scored_at": scored_at,
                # Extended fields
                "convos_7d": sc["convos_7d"],
                "convos_30d": sc["convos_30d"],
                "wow_delta": sc["wow_delta"],
                "messages_7d": sc["messages_7d"],
                "avg_msgs_per_convo": sc["avg_msgs_per_convo"],
                "bot_ratio": sc["bot_ratio"],
                "resolution_rate": sc["resolution_rate"],
                "avg_frt_secs": sc["avg_frt_secs"],
                "active_agents": sc["active_agents"],
                "active_bots": sc["active_bots"],
                "total_channels": sc["total_channels"],
                "trend_consistency": sc["trend_consistency"],
            }
            
            # Check if score record exists
            existing, _ = pb("GET", f"/api/collections/churn_scores/records?filter=account_id=\"{acc['id']}\"&perPage=1", token=token)
            if existing and existing.get("items"):
                pb("PATCH", f"/api/collections/churn_scores/records/{existing['items'][0]['id']}", score_data, token=token)
            else:
                pb("POST", "/api/collections/churn_scores/records", score_data, token=token)
        
        print(f"  Page {page}: {len(res['items'])} accounts processed")
        page += 1
    
    print()
    print("=" * 60)
    print("SCORING COMPLETE")
    print("=" * 60)
    print(f"  Total scored: {stats['total']}")
    print(f"  Skipped (inactive): {stats['skipped']}")
    print()
    print(f"  🟢 Healthy:  {stats['green']}")
    print(f"  🟡 At Risk:  {stats['yellow']}")
    print(f"  🔴 Churning: {stats['red']}")
    print()
    print("MRR BREAKDOWN:")
    print(f"  Total MRR (INR): ₹{mrr_stats['total_inr']:,.0f}")
    print(f"  At-Risk MRR (INR): ₹{mrr_stats['at_risk_inr']:,.0f}")
    print()
    print("  By Currency:")
    for cur, data in sorted(mrr_stats["by_currency"].items(), key=lambda x: -x[1]["inr"]):
        symbol = "₹" if cur == "INR" else "$" if cur == "USD" else cur + " "
        print(f"    {cur}: {data['count']} accounts, {symbol}{data['native']:,.0f} native, ₹{data['inr']:,.0f} INR equiv")
    
    print()
    
    # Show high risk accounts
    high_risk, _ = pb("GET", "/api/collections/churn_scores/records?filter=health=\"red\"&sort=-churn_score&perPage=10&expand=account_id", token=token)
    if high_risk and high_risk.get("items"):
        print("TOP HIGH-RISK ACCOUNTS:")
        for s in high_risk["items"][:10]:
            acc_data = s.get("expand", {}).get("account_id", {})
            name = acc_data.get("company", "Unknown")
            mrr = acc_data.get("mrr", 0)
            cur = acc_data.get("currency", "INR")
            print(f"  • {name}: {s['churn_score']}% risk, {cur} {mrr:,.0f}/mo")
    
    print()
    print(f"Scored at: {scored_at}")

if __name__ == "__main__":
    main()
