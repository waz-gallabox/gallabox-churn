# Gallabox Churn Scoring Model

> **Source of truth** for how churn score, upsell score, and health labels are calculated.
> Script: `clickhouse_score_v3.py`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| **v2** | Apr 2026 | Lifecycle stages, two-bucket penalty system, MoM trend, feature adoption depth, renewal proximity, WoW double-count fix, baseline lowered to 500 |
| v1 | Apr 2026 | Initial 4-source model (Chargebee + ClickHouse + Zoho Desk + Zoho CRM) |

---

## Health Labels

| Label | Color | Condition |
|-------|-------|-----------|
| **Healthy** | 🟢 Green | Churn score < 25 AND no "Critical" churn reason |
| **Warning** | 🟡 Yellow | Churn score ≥ 25, OR any churn/cancellation ticket with WoW decline > 20% |
| **At Risk** | 🔴 Red | Churn score ≥ 50, OR subscription status = `cancelled` |

**Override rules:**
- If any churn reason contains "Critical", health is forced to minimum Warning — a Critical signal can never show as Healthy.
- If renewal is within 30 days and churn score ≥ 15, health is forced to minimum Warning.

---

## Churn Score (0–100)

Built from 4 sources. Final score is clamped to 0–100.

---

### Source 1 — Chargebee / Billing (max ~35 pts)

#### Subscription status
| Status | Points | Reason shown |
|--------|--------|--------------|
| `cancelled` | +35 | Subscription cancelled |
| `non_renewing` | +28 | Set to non-renew — churning at period end |
| `paused` | +20 | Subscription paused |
| `in_trial` | +8 | In trial — conversion not confirmed |

#### MRR signals
| Condition | Points | Reason shown |
|-----------|--------|--------------|
| MRR (INR) = 0, status not trial/cancelled, not Message-Credits plan | +8 | Zero MRR — no financial commitment |
| MRR (INR) > ₹50,000/mo | −8 | (sticky high-value — no label) |
| MRR (INR) > ₹20,000/mo | −5 | (no label) |

> **Message-Credits plans** are exempt from the zero-MRR penalty — Chargebee reports ₹0 for usage-based billing but these are paying customers.

---

### Source 2 — ClickHouse / Product Usage (v2)

#### Two-bucket system (new in v2)

Signals are split into **hard** and **soft** buckets before lifecycle scaling is applied.

| Bucket | What goes in | Lifecycle scaling |
|--------|-------------|-------------------|
| **Hard** | Zero usage, complete dropout, no channels configured | Always 100% — no grace |
| **Soft** | Below-baseline, engagement quality, MoM trend, WoW decline | Scaled by lifecycle stage |

> **Rationale:** A new account with zero usage or that suddenly drops out is a real problem regardless of age. But a new account being below the 500 conv/month baseline is expected — they haven't had time to ramp up yet.

#### Account lifecycle stages (new in v2)

Lifecycle is determined from `cb_created_at` (Chargebee creation timestamp).

| Stage | Age | Soft signal scaling |
|-------|-----|---------------------|
| **New** | < 60 days | 40% — deep onboarding grace |
| **Ramping** | 60–180 days | 70% — still growing |
| **Mature** | 180+ days | 100% — full weight |

When scaling applies, a label is prepended to churn reasons:
- `New account (Nd old) — ramp signals at 40%`
- `Growing account (Nd old) — ramp signals at 70%`

---

#### HARD signals (always full weight)

##### Zero usage entirely (no ClickHouse data)
| Condition | Points | Reason shown |
|-----------|--------|--------------|
| `status = active` AND `mrr > 0` | +35 | Active paying account with zero product usage |
| All other zero-usage cases | +25 | No product usage recorded |

##### Complete dropout
| Condition | Points | Reason shown |
|-----------|--------|--------------|
| `c7 = 0` AND previous week had > 10 convos | +28 | Complete dropout — 0 convos this week (had N last week) |

##### No channels configured
| Condition | Points | Reason shown |
|-----------|--------|--------------|
| Zero channels set up | +8 | No channels configured |

---

#### SOFT signals (lifecycle-scaled)

##### Weekly activity
| Condition | Points | Reason shown |
|-----------|--------|--------------|
| `c7 = 0` AND `c30 > 0` | +18 | No activity this week (was active this month) |
| `c7 = 0` AND `c30 = 0` | +10 | No conversations this week |

##### Week-on-week trend (only when `c7 > 0`)
WoW% = `(convos_7d − convos_prev_7d) / convos_prev_7d × 100`

> WoW signals only fire when `c7 > 0`. When `c7 = 0` the drop is always −100% by definition — firing it on top of the "no activity" penalty would double-count the same fact. *(Fixed in v2)*

| WoW % | Points | Reason shown |
|-------|--------|--------------|
| < −60% | +20 | Severe usage drop — N% WoW decline |
| −40% to −60% | +14 | Major usage drop — N% WoW |
| −20% to −40% | +8 | Usage declining — N% WoW |
| > +20% (and c7 > 10) | −8 | (recovery bonus — no label) |

##### Month-over-month trend (new in v2)
Compares this month's conversations (`c30`) to last month's (`convos_prev_30d`).
This gives an **account-relative** signal — a 40% drop from the account's own last month is more meaningful than an absolute number.

| MoM % | Points | Reason shown |
|-------|--------|--------------|
| < −50% | +18 | Sharp MoM decline — N% drop vs last month |
| −25% to −50% | +10 | Month-over-month decline — N% drop vs last month |
| > +30% (and c30 > 50) | −8 | (recovering — no label) |

##### 30-day global baseline (baseline = 500 convos/month)
| `c30` range | Points | Reason shown |
|-------------|--------|--------------|
| ≥ 500 | −8 | (at or above baseline — sticky, no label) |
| 375–499 | +3 | Slightly below 30d baseline — N convos (target 500) |
| 250–374 | +8 | Below 30d baseline — N convos (target 500) |
| 125–249 | +14 | Significantly below baseline — N/500 convos in 30d |
| 1–124 | +18 | Critical — only N convos in 30d (baseline: 500) |

##### 90-day zombie check (new in v2)
Catches accounts that look okay on weekly/monthly view but have been dormant for 3 months straight.

| `c90` | Condition | Points | Reason shown |
|-------|-----------|--------|--------------|
| < 30 | `c30 > 0` | +12 | Sustained low usage — only N convos in 90d |
| 30–74 | `c30 > 0` | +6 | Chronically below baseline — N convos in 90d |

##### Feature adoption depth (new in v2)
Counts distinct product capabilities in active use: bot, broadcasts, sequences, multi-channel, templates.
More features = more embedded = stickier customer.

| Features used | Points | Reason shown |
|---------------|--------|--------------|
| 0 (inbox only) and `c30 > 20` | +8 | Inbox-only usage — no automation or outbound features adopted |
| 2 features | −4 | (no label) |
| 3+ features | −8 | (no label) |

##### Engagement quality
| Condition | Points | Reason shown |
|-----------|--------|--------------|
| `c7 > 0` AND avg msgs/convo < 3 | +6 | Shallow engagement — N msgs/convo avg |
| Active < 30% of days in period | +8 | Inconsistent usage — active only N% of days |
| Avg FRT > 10 min AND `c30 > 20` | +5 | Slow response time — N min avg FRT |

---

#### Renewal proximity urgency (new in v2)

Applied after all other signals, before the final clamp to 0–100.
Uses `next_billing_at` from Chargebee (requires `fetch_subs.py` to have been run).

| Condition | Points | Reason shown |
|-----------|--------|--------------|
| Renewal ≤ 30 days AND churn ≥ 15 | +10 | Renewal in N days — elevated risk window |
| Renewal ≤ 60 days AND churn ≥ 20 | +5 | Renewal approaching in N days |

---

### Source 3 — Zoho Desk / Support Tickets (max 20 pts)

| Signal | Points | Reason shown |
|--------|--------|--------------|
| Churn/cancellation tickets | +8 per ticket, max +16 | N churn/cancellation ticket(s) raised |
| Escalated tickets | +4 per ticket, max +8 | N escalated ticket(s) |
| > 3 open tickets | +6 | N open tickets — high support load |
| 1–3 open tickets | +3 | (no label) |
| Overdue tickets | +3 per ticket, max +6 | N overdue ticket(s) |

---

### Source 4 — Zoho CRM / KAM Signals (max 10 pts)

| Signal | Points | Reason shown |
|--------|--------|--------------|
| KAM status = "at risk" or "churned" | +10 | KAM flagged account status: [status] |
| KAM status = "churning" | +8 | KAM status: churning |
| ICP = "non-icp" | +5 | Non-ICP account — lower retention likelihood |

---

## Upsell Score (0–100)

Only calculated for `status = active` or `in_trial`. All others = 0.

### Source 1 — Chargebee / Plan & MRR (max 20 pts)

| Condition | Points | Reason shown |
|-----------|--------|--------------|
| Entry-tier plan (free/trial/starter/basic/growth/zone/credit/lite) | +10 | Entry-tier plan — upgrade path available |
| Above + `c7 > 100` | +8 more | High usage on low plan — likely hitting limits |
| MRR (INR) ₹1–₹5,000, not low plan | +6 | Low MRR with room to expand |

### Source 2 — ClickHouse / Volume & Growth (max 50 pts)

| `c7` | Points | | WoW % | Points |
|------|--------|-|-------|--------|
| > 1,000/week | +25 | | > +50% | +15 |
| 500–1,000 | +18 | | +25–50% | +10 |
| 200–500 | +12 | | +10–25% | +5 |
| 50–200 | +6 | | | |

| Feature signal | Points | Reason shown |
|----------------|--------|--------------|
| Bot ratio > 60% AND `c7 > 50` | +8 | High bot adoption — automation buyer |
| Bot ratio 30–60% | +4 | (no label) |
| 3+ channel types | +8 | Multi-channel power user |
| 2 channel types | +4 | (no label) |
| > 5 active agents | +6 | Large team — N active agents |
| 2–5 active agents | +3 | (no label) |

### Source 3 — Zoho Desk (max 5 pts)

| Signal | Points |
|--------|--------|
| > 5 tickets AND no churn tickets | +3 |
| Has churn tickets | −5 |

### Source 4 — Zoho CRM / KAM Signals (max 25 pts)

| Signal | Points | Reason shown |
|--------|--------|--------------|
| KAM expansion = "yes" | +15 | KAM confirmed expansion scope |
| KAM expansion = "maybe" | +8 | KAM flagged potential expansion |
| KAM upgrade possible | +10 | KAM marked upgrade possibility |
| ICP = "icp" | +8 | ICP account — ideal expansion candidate |
| Segment = enterprise/large | +5 | Enterprise segment — higher ACV potential |
| Segment = mid/SMB | +2 | (no label) |
| KAM status = churning/at risk | −10 | (don't upsell at-risk accounts) |

---

## Score Ranges

| Churn Score | Meaning | CS Action |
|-------------|---------|-----------|
| 0–15 | Very healthy | No action needed |
| 16–24 | Healthy, minor signals | Monitor |
| 25–39 | Warning | Proactive check-in |
| 40–49 | Elevated risk | CSM intervention |
| 50–100 | At Risk / High churn probability | Urgent — escalate |

| Upsell Score | Meaning |
|--------------|---------|
| 0–15 | No signal |
| 16–30 | Mild opportunity |
| 31–55 | Good candidate |
| 56–100 | Prioritize |

---

## Data Sources & Refresh

| Source | What it provides | How to refresh |
|--------|-----------------|----------------|
| **Chargebee** | Status, MRR, plan, renewal date | `python3 fetch_subs.py` |
| **ClickHouse** | Conversations (7d/30d/60d/90d), WoW, FRT, bot ratio, channels, agents | Queried live at score time |
| **Zoho Desk** | Ticket signals | `python3 sync_zoho_tickets.py` |
| **Zoho CRM** | KAM status, ICP, expansion scope | `python3 sync_zoho_crm.py` |

Run order for a full refresh:
```bash
python3 fetch_subs.py          # Chargebee subscriptions + renewal dates
python3 sync_zoho_tickets.py   # Zoho Desk tickets
python3 sync_zoho_crm.py       # KAM signals
python3 clickhouse_score_v3.py # Score all accounts
```

---

## Known Limitations

- **`convos_7d` counts new conversations created**, not agent activity on existing ones. An account resolving old backlog will show `c7 = 0` even if agents are actively working — scores may understate engagement in high-backlog accounts.
- **WoW requires prior-week data**: If `p7 = 0` (no prior week data — e.g. brand new account), WoW defaults to 0 and no WoW signal fires.
- **MoM requires prior-month data**: If `convos_prev_30d = 0`, no MoM signal fires. New accounts in their first month won't have this.
- **CRM coverage gap**: ~50% of active accounts have no KAM assigned in Zoho CRM — Source 4 contributes 0 for these. Run `sync_zoho_crm.py` to improve coverage.
- **Renewal dates**: Only available after `fetch_subs.py` is run. Without it, `days_to_renewal` defaults to 999 and the renewal proximity signal never fires.
- **Trend consistency**: Measures % of days with any conversation activity. An account with bursts (500 convos Monday, nothing rest of week) scores low on consistency but isn't necessarily at risk.
