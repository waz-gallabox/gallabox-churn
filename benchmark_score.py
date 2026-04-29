#!/usr/bin/env python3
"""
Gallabox Churn scoring benchmark — evaluates compute_scores_v3 against canonical test cases.

Each test case is a hand-crafted scenario with expected outcomes derived from
SCORING.md. Score = fraction of checks that pass (1.0 = all pass, 0.0 = all fail).

The benchmark is pure: no DB calls, no network, no credentials needed.
"""
import os
import sys

# Satisfy config.py _require() so the module can be imported without .env
for _k in ("PB_EMAIL", "PB_PASSWORD", "CH_HOST", "CH_USER", "CH_PASS", "CB_SITE", "CB_KEY"):
    os.environ.setdefault(_k, "benchmark-dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clickhouse_score_v3 import compute_scores_v3

SDK_PATH = "/Users/gallabox/.claude/plugins/cache/evo-hq-evo/evo/0.1.0/sdk/python/src"
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)
from evo_agent import Run

# ── helpers ───────────────────────────────────────────────────────────────────

def billing(status="active", mrr_inr=10000, mrr=10000, currency="INR",
            plan="growth", age=365, renewal=60):
    return {"status": status, "mrr_inr": mrr_inr, "mrr": mrr, "currency": currency,
            "plan": plan, "account_age_days": age, "days_to_renewal": renewal}

def ch(c7=300, p7=300, c30=1200, c_prev30=1200, c90=3600, avg_msgs=5.0,
       bot_ratio=30.0, frt=120, agents=3, bots=1, channels=2, trend=80,
       ch_types=2, broadcasts=0, sequences=0, templates=0):
    return {"convos_7d": c7, "convos_prev_7d": p7, "convos_30d": c30,
            "convos_prev_30d": c_prev30, "convos_90d": c90,
            "avg_msgs_per_convo": avg_msgs, "bot_ratio": bot_ratio,
            "avg_frt_secs": frt, "active_agents": agents, "active_bots": bots,
            "total_channels": channels, "trend_consistency": trend,
            "channel_types": ch_types, "broadcasts_30d": broadcasts,
            "sequences_active": sequences, "template_sends_30d": templates}

def ch_neutral():
    """ClickHouse input that contributes ~0 net churn.

    Design: c30=500 gives soft -8 (at-baseline bonus).
    features=0 with c30>20 gives soft +8 (inbox-only penalty).
    Net soft = 0. No hard signals. Useful for isolating desk/CRM/billing signals.
    """
    return ch(c7=100, p7=100, c30=500, c_prev30=500, c90=1500,
              avg_msgs=5, bot_ratio=0, frt=120, agents=3, bots=0,
              channels=2, trend=80, ch_types=1, broadcasts=0, sequences=0, templates=0)

def desk(total=0, open_=0, churn=0, escalated=0, overdue=0):
    return {"total": total, "open": open_, "churn": churn,
            "escalated": escalated, "overdue": overdue}

def crm(icp="icp", expansion="no", upgrade=False, seg="smb", kam=""):
    return {"icp": icp, "expansion_scope": expansion, "upgrade_possible": upgrade,
            "segmentation": seg, "kam_status": kam}

NO_CH = {}  # represents zero ClickHouse data (account never used product)

def run_score(b, c, d, r):
    return compute_scores_v3(b, c, d, r)

def check(result, checks):
    """Return (passed_fraction, failed_details)."""
    total = len(checks)
    passed = 0
    details = []
    for label, op, expected, actual_key in checks:
        actual = result.get(actual_key)
        ok = False
        if   op == ">=": ok = actual >= expected
        elif op == "<=": ok = actual <= expected
        elif op == "==": ok = actual == expected
        elif op == "!=": ok = actual != expected
        elif op == ">":  ok = actual >  expected
        elif op == "<":  ok = actual <  expected
        if ok:
            passed += 1
        else:
            details.append(f"{label}: expected {actual_key}{op}{expected}, got {actual}")
    return passed / total, details


# ── test cases ────────────────────────────────────────────────────────────────
# ch_neutral() is used whenever the test focuses on billing/desk/CRM signals in
# isolation — it contributes ~0 net churn from ClickHouse so signals are additive.

TASKS = [
    # ── BILLING signals ───────────────────────────────────────────────────────
    {
        "id": "cancelled_red",
        "desc": "Cancelled subscription → churn≥35, health=red, upsell=0",
        "args": (billing("cancelled", mrr_inr=0), ch_neutral(), desk(), crm()),
        "checks": [
            ("churn≥35", ">=", 35, "churn_score"),
            ("health=red", "==", "red", "health"),
            ("upsell=0", "==", 0, "upsell_score"),
        ],
    },
    {
        "id": "non_renewing_high_churn",
        "desc": "Non-renewing status → churn≥28",
        "args": (billing("non_renewing"), ch_neutral(), desk(), crm()),
        "checks": [
            ("churn≥28", ">=", 28, "churn_score"),
        ],
    },
    {
        "id": "paused_churn_signal",
        "desc": "Paused subscription → churn≥20",
        "args": (billing("paused"), ch_neutral(), desk(), crm()),
        "checks": [
            ("churn≥20", ">=", 20, "churn_score"),
        ],
    },
    {
        "id": "trial_churn_signal",
        "desc": "In-trial account → churn includes +8 for trial, upsell still calculated",
        "args": (billing("in_trial", mrr_inr=0), ch_neutral(), desk(), crm()),
        "checks": [
            ("churn≥8", ">=", 8, "churn_score"),
            ("upsell>0", ">", 0, "upsell_score"),  # in_trial still gets upsell
        ],
    },
    {
        "id": "zero_mrr_penalty",
        "desc": "Active account with zero MRR (not credits plan) → churn > 0",
        "args": (billing("active", mrr_inr=0, plan="growth"), ch(), desk(), crm("non-icp")),
        "checks": [
            ("churn>0", ">", 0, "churn_score"),
        ],
    },
    {
        "id": "high_value_sticky",
        "desc": "MRR > ₹50k active account with good usage → churn low (sticky -8pts)",
        "args": (billing("active", mrr_inr=60000, plan="enterprise"), ch(), desk(), crm()),
        "checks": [
            ("churn<30", "<", 30, "churn_score"),
            ("health=green", "==", "green", "health"),
        ],
    },
    {
        "id": "credits_plan_zero_mrr_exempt",
        "desc": "Message-credits plan with zero MRR → NO zero-MRR penalty",
        "args": (billing("active", mrr_inr=0, plan="message-credits"), ch(), desk(), crm()),
        "checks": [
            ("churn<20", "<", 20, "churn_score"),
        ],
    },

    # ── ClickHouse HARD signals ───────────────────────────────────────────────
    {
        "id": "zero_usage_active_paying",
        "desc": "Active paying account with zero ClickHouse data → hard +35 pts, health=yellow",
        "args": (billing("active", mrr_inr=5000), NO_CH, desk(), crm()),
        "checks": [
            ("churn≥35", ">=", 35, "churn_score"),
            ("health=yellow", "==", "yellow", "health"),  # 35<50, status≠cancelled → yellow
        ],
    },
    {
        "id": "zero_usage_no_mrr",
        "desc": "Active account with zero usage and zero MRR → hard +25 pts",
        "args": (billing("active", mrr_inr=0, plan="growth"), NO_CH, desk(), crm()),
        "checks": [
            ("churn≥25", ">=", 25, "churn_score"),
        ],
    },
    {
        "id": "complete_dropout_hard",
        "desc": "c7=0 but p7=50 → complete dropout hard signal +28",
        "args": (billing("active"), ch(c7=0, p7=50, c30=200), desk(), crm()),
        "checks": [
            ("churn≥28", ">=", 28, "churn_score"),
            ("health!=green", "!=", "green", "health"),
        ],
    },
    {
        "id": "no_channels_hard",
        "desc": "Account has usage but zero channels configured → hard +8 pts",
        "args": (billing("active"),
                 # neutral soft + zero channels to isolate the hard signal
                 ch(c7=100, p7=100, c30=500, c_prev30=500, c90=1500, channels=0,
                    ch_types=1, bot_ratio=0, broadcasts=0, templates=0, sequences=0),
                 desk(), crm()),
        "checks": [
            ("churn≥8", ">=", 8, "churn_score"),
        ],
    },

    # ── ClickHouse SOFT signals ───────────────────────────────────────────────
    {
        "id": "wow_severe_drop_mature",
        "desc": "Mature account: 70% WoW drop → soft +20 fires, churn≥25",
        "args": (billing("active", age=365),
                 ch(c7=30, p7=100, c30=400, c_prev30=400, c90=1200,
                    ch_types=1, bot_ratio=0, broadcasts=0, templates=0, sequences=0),
                 desk(), crm()),
        "checks": [
            ("churn≥25", ">=", 25, "churn_score"),
        ],
    },
    {
        "id": "wow_recovery_bonus",
        "desc": "WoW > +20% with c7 > 10 → soft -8 pts recovery bonus, low churn",
        "args": (billing("active"), ch(c7=150, p7=100, c30=600), desk(), crm()),
        "checks": [
            ("churn<25", "<", 25, "churn_score"),
            ("health=green", "==", "green", "health"),
        ],
    },
    {
        "id": "mom_sharp_decline",
        "desc": "MoM > -50% drop → soft +18 pts",
        "args": (billing("active", age=365), ch(c30=100, c_prev30=250), desk(), crm()),
        "checks": [
            ("churn>15", ">", 15, "churn_score"),
        ],
    },
    {
        "id": "mom_recovery_bonus",
        "desc": "MoM > +30% with c30 > 50 → soft -8 pts bonus, low churn",
        "args": (billing("active"), ch(c30=600, c_prev30=400), desk(), crm()),
        "checks": [
            ("churn<20", "<", 20, "churn_score"),
        ],
    },
    {
        "id": "above_baseline_sticky",
        "desc": "c30 >= 500 → soft -8 pts baseline bonus, green",
        "args": (billing("active"), ch(c30=600), desk(), crm()),
        "checks": [
            ("churn<20", "<", 20, "churn_score"),
            ("health=green", "==", "green", "health"),
        ],
    },
    {
        "id": "critical_below_baseline",
        "desc": "c30=50 (< 125) → soft +18, 'Critical' in reasons",
        "args": (billing("active", age=365), ch(c7=10, p7=10, c30=50, c90=150), desk(), crm()),
        "checks": [
            ("churn>15", ">", 15, "churn_score"),
        ],
    },
    {
        "id": "zombie_90d_check",
        "desc": "c90 < 30 with c30 > 0 → zombie soft +12",
        "args": (billing("active", age=365), ch(c7=5, c30=20, c90=20), desk(), crm()),
        "checks": [
            ("churn>10", ">", 10, "churn_score"),
        ],
    },
    {
        "id": "feature_rich_sticky",
        "desc": "3+ features adopted → soft -8 pts sticky bonus, low churn",
        "args": (billing("active"), ch(c30=600, broadcasts=100, ch_types=3, templates=50, bot_ratio=15), desk(), crm()),
        "checks": [
            ("churn<20", "<", 20, "churn_score"),
        ],
    },
    {
        "id": "inbox_only_penalty",
        "desc": "c30 > 20 with zero features (inbox-only) → soft +8",
        "args": (billing("active", age=365),
                 ch(c30=200, c7=50, broadcasts=0, ch_types=1, templates=0, bot_ratio=0, sequences=0),
                 desk(), crm()),
        "checks": [
            ("churn>0", ">", 0, "churn_score"),
        ],
    },
    {
        "id": "shallow_engagement",
        "desc": "c7 > 0 with avg_msgs < 3 → soft +6",
        "args": (billing("active", age=365), ch(c7=50, avg_msgs=2.0, c30=200), desk(), crm()),
        "checks": [
            ("churn>5", ">", 5, "churn_score"),
        ],
    },
    {
        "id": "inconsistent_usage",
        "desc": "Trend consistency < 30% with c30 > 0 → soft +8",
        "args": (billing("active", age=365), ch(c7=50, c30=200, trend=20), desk(), crm()),
        "checks": [
            ("churn>10", ">", 10, "churn_score"),
        ],
    },
    {
        "id": "slow_frt",
        "desc": "FRT > 600s with c30 > 20 → soft +5",
        "args": (billing("active", age=365), ch(c30=200, frt=800), desk(), crm()),
        "checks": [
            ("churn>5", ">", 5, "churn_score"),
        ],
    },

    # ── Lifecycle scaling ─────────────────────────────────────────────────────
    {
        "id": "new_account_soft_scaled",
        "desc": "New account (30d) below baseline: soft signals at 40% → churn<50, health not red",
        "args": (billing("active", age=30), ch(c7=10, c30=50, c90=50), desk(), crm()),
        "checks": [
            ("churn<50", "<", 50, "churn_score"),
            ("health!=red", "!=", "red", "health"),
        ],
    },
    {
        "id": "mature_full_weight",
        "desc": "Mature account (400d) same low usage → soft signals at 100%, churn higher than new",
        "args": (billing("active", age=400), ch(c7=10, c30=50, c90=50), desk(), crm()),
        "checks": [
            ("churn>15", ">", 15, "churn_score"),
        ],
    },

    # ── Desk signals (use ch_neutral to isolate) ──────────────────────────────
    {
        "id": "churn_tickets_raised",
        "desc": "2 churn tickets → churn += min(16, 2*8) = 16",
        "args": (billing("active"), ch_neutral(), desk(total=2, churn=2), crm()),
        "checks": [
            ("churn≥16", ">=", 16, "churn_score"),
        ],
    },
    {
        "id": "escalated_tickets",
        "desc": "2 escalated tickets → churn += 8",
        "args": (billing("active"), ch_neutral(), desk(total=2, escalated=2), crm()),
        "checks": [
            ("churn≥8", ">=", 8, "churn_score"),
        ],
    },
    {
        "id": "high_open_ticket_load",
        "desc": "> 3 open tickets → churn += 6",
        "args": (billing("active"), ch_neutral(), desk(total=5, open_=5), crm()),
        "checks": [
            ("churn≥6", ">=", 6, "churn_score"),
        ],
    },
    {
        "id": "overdue_tickets",
        "desc": "2 overdue tickets → churn += min(6, 2*3) = 6",
        "args": (billing("active"), ch_neutral(), desk(total=2, overdue=2), crm()),
        "checks": [
            ("churn≥6", ">=", 6, "churn_score"),
        ],
    },

    # ── CRM signals (use ch_neutral to isolate) ───────────────────────────────
    {
        "id": "kam_at_risk",
        "desc": "KAM status = 'at risk' → churn += 10",
        "args": (billing("active"), ch_neutral(), desk(), crm(kam="at risk")),
        "checks": [
            ("churn≥10", ">=", 10, "churn_score"),
        ],
    },
    {
        "id": "non_icp_penalty",
        "desc": "Non-ICP account → churn += 5",
        "args": (billing("active"), ch_neutral(), desk(), crm(icp="non-icp")),
        "checks": [
            ("churn≥5", ">=", 5, "churn_score"),
        ],
    },

    # ── Renewal proximity ─────────────────────────────────────────────────────
    {
        "id": "renewal_urgency_30d",
        "desc": "Renewal ≤ 30 days AND churn ≥ 15 → +10 pts urgency",
        "args": (billing("active", age=365, renewal=20),
                 ch(c7=20, c30=80, c90=240), desk(), crm()),
        "checks": [
            ("churn>20", ">", 20, "churn_score"),
        ],
    },

    # ── Health label overrides ────────────────────────────────────────────────
    {
        "id": "critical_reason_forces_yellow",
        "desc": "'Critical' in churn reasons → health forced to min yellow even if score < 25",
        "args": (billing("active", age=365),
                 ch(c7=10, p7=10, c30=50, c90=150), desk(), crm()),
        "checks": [
            ("health!=green", "!=", "green", "health"),
        ],
    },
    {
        "id": "red_when_churn_ge_50",
        "desc": "churn_score ≥ 50 → health = red",
        "args": (billing("cancelled", mrr_inr=0),
                 ch(c7=0, p7=50, c30=0), desk(churn=2), crm(kam="at risk")),
        "checks": [
            ("health=red", "==", "red", "health"),
            ("churn≥50", ">=", 50, "churn_score"),
        ],
    },

    # ── Upsell signals ────────────────────────────────────────────────────────
    {
        "id": "upsell_high_volume_entry_plan",
        "desc": "Entry-tier plan + c7 > 100 → upsell +18 from billing alone",
        "args": (billing("active", plan="starter"), ch(c7=200, c30=800), desk(), crm()),
        "checks": [
            ("upsell≥18", ">=", 18, "upsell_score"),
        ],
    },
    {
        "id": "upsell_explosive_growth",
        "desc": "c7 > 1000 and WoW > 50% → upsell +40 from ClickHouse alone",
        "args": (billing("active", plan="enterprise"), ch(c7=1500, p7=900, c30=5000), desk(), crm()),
        "checks": [
            ("upsell≥40", ">=", 40, "upsell_score"),
        ],
    },
    {
        "id": "upsell_kam_expansion",
        "desc": "KAM expansion='yes' + ICP → upsell +23 from CRM",
        "args": (billing("active"), ch(), desk(), crm(expansion="yes", icp="icp")),
        "checks": [
            ("upsell≥23", ">=", 23, "upsell_score"),
        ],
    },
    {
        "id": "upsell_zero_non_active",
        "desc": "Paused account → upsell = 0",
        "args": (billing("paused"), ch(), desk(), crm()),
        "checks": [
            ("upsell=0", "==", 0, "upsell_score"),
        ],
    },
    {
        "id": "upsell_churn_tickets_dampen",
        "desc": "Churn tickets present → upsell damped (not inflated)",
        "args": (billing("active", plan="starter"), ch(c7=200), desk(churn=1), crm()),
        "checks": [
            ("upsell≥0", ">=", 0, "upsell_score"),
        ],
    },

    # ── Model floor checks (currently failing — improvement targets) ─────────
    # These expose a known weakness: CH sticky bonuses can reduce churn to 0
    # for non-renewing/paused accounts, making them appear Healthy to CS teams.
    {
        "id": "non_renewing_floor_warning",
        "desc": "Non-renewing with stellar CH usage must still warn (churn>=15, health!=green)",
        "args": (billing("non_renewing", mrr_inr=5000),
                 ch(c30=2000, c_prev30=1200, ch_types=3, broadcasts=200, bot_ratio=40, templates=100),
                 desk(), crm()),
        "checks": [
            ("churn≥15", ">=", 15, "churn_score"),
            ("health!=green", "!=", "green", "health"),
        ],
    },
    {
        "id": "paused_floor_churn",
        "desc": "Paused account with great CH usage should still have churn>0 (not zeroed by bonuses)",
        "args": (billing("paused", mrr_inr=5000),
                 ch(c30=2000, c_prev30=1200, ch_types=3, broadcasts=200, bot_ratio=40, templates=100),
                 desk(), crm()),
        "checks": [
            ("churn>0", ">", 0, "churn_score"),
        ],
    },

    # ── Healthy baseline (smoke test) ─────────────────────────────────────────
    {
        "id": "healthy_account_green",
        "desc": "Active, mature, high usage, ICP, good signals → health green, low churn",
        "args": (billing("active", mrr_inr=25000, plan="pro", age=400),
                 ch(c7=400, p7=350, c30=1600, c90=4800, channels=3, ch_types=3,
                    broadcasts=200, templates=100, trend=85),
                 desk(), crm(icp="icp", expansion="no")),
        "checks": [
            ("health=green", "==", "green", "health"),
            ("churn<25", "<", 25, "churn_score"),
        ],
    },
]


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    with Run() as run:
        for task in TASKS:
            tid = task["id"]
            b, c, d, r = task["args"]

            run.log(tid, {"desc": task["desc"]})
            result = run_score(b, c, d, r)
            run.log(tid, {
                "churn_score": result["churn_score"],
                "upsell_score": result["upsell_score"],
                "health": result["health"],
                "churn_reasons": result["churn_reasons"],
            })

            fraction, failures = check(result, task["checks"])
            failure_reason = "; ".join(failures) if failures else None

            run.report(
                tid,
                score=fraction,
                summary=(f"{task['desc']} | "
                         f"churn={result['churn_score']} "
                         f"upsell={result['upsell_score']} "
                         f"health={result['health']}"),
                failure_reason=failure_reason,
            )


if __name__ == "__main__":
    main()
