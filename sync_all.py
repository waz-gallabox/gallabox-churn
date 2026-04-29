#!/usr/bin/env python3
"""
Gallabox Churn full-sync pipeline.

Runs all 4 data-source sync steps in the correct order, then scores all accounts.

Usage:
  python3 sync_all.py                # full sync
  python3 sync_all.py --quick        # quick ticket fetch (200 instead of 2000)
  python3 sync_all.py --skip-tickets # skip Zoho Desk sync
  python3 sync_all.py --skip-crm     # skip Zoho CRM sync
  python3 sync_all.py --skip-score   # sync data sources only, no re-score
"""

import os
import subprocess
import sys
import time
from datetime import datetime

REPO = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(REPO, "sync_all.log")

# ── CLI flags ─────────────────────────────────────────────────────────────────
args = set(sys.argv[1:])
QUICK        = "--quick"        in args
SKIP_TICKETS = "--skip-tickets" in args
SKIP_CRM     = "--skip-crm"     in args
SKIP_SCORE   = "--skip-score"   in args


# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Step runner ───────────────────────────────────────────────────────────────
def run_step(name, cmd):
    """Run a subprocess step, stream output, return (ok, elapsed_secs)."""
    log(f"── {name} ──────────────────────────────")
    t0 = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in proc.stdout:
        line = line.rstrip()
        print(f"  {line}")
        with open(LOG_FILE, "a") as f:
            f.write(f"  {line}\n")
    proc.wait()
    elapsed = round(time.time() - t0)
    ok = proc.returncode == 0
    status = "✓" if ok else f"✗ (exit {proc.returncode})"
    log(f"  → {name} {status}  {elapsed}s")
    return ok, elapsed


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"=== Gallabox Churn Sync started — {started} ===")
    if QUICK:        log("  mode: --quick (200 tickets)")
    if SKIP_TICKETS: log("  skipping: sync_zoho_tickets")
    if SKIP_CRM:     log("  skipping: sync_zoho_crm")
    if SKIP_SCORE:   log("  skipping: clickhouse_score_v3")

    results = []  # list of (name, ok, elapsed)

    # Step 1 — Chargebee subscriptions (required by scorer)
    ok, t = run_step("fetch_subs", ["python3", "fetch_subs.py"])
    results.append(("fetch_subs", ok, t))
    if not ok:
        log("FATAL: fetch_subs failed — aborting pipeline")
        sys.exit(1)

    # Step 2 — Zoho Desk tickets
    if not SKIP_TICKETS:
        cmd = ["python3", "sync_zoho_tickets.py"]
        if QUICK:
            cmd.append("--quick")
        ok, t = run_step("sync_tickets", cmd)
        results.append(("sync_tickets", ok, t))
        if not ok:
            log("FATAL: sync_zoho_tickets failed — aborting pipeline")
            sys.exit(1)
    else:
        results.append(("sync_tickets", None, 0))

    # Step 3 — Zoho CRM / KAM signals
    if not SKIP_CRM:
        ok, t = run_step("sync_crm", ["python3", "sync_zoho_crm.py"])
        results.append(("sync_crm", ok, t))
        if not ok:
            log("FATAL: sync_zoho_crm failed — aborting pipeline")
            sys.exit(1)
    else:
        results.append(("sync_crm", None, 0))

    # Step 4 — Score all accounts
    if not SKIP_SCORE:
        ok, t = run_step("score_v3", ["python3", "clickhouse_score_v3.py"])
        results.append(("score_v3", ok, t))
        if not ok:
            log("FATAL: clickhouse_score_v3 failed")
            sys.exit(1)
    else:
        results.append(("score_v3", None, 0))

    # Summary
    total = sum(t for _, _, t in results)
    log(f"\n=== Gallabox Churn Sync complete — {datetime.now().strftime('%H:%M:%S')} ===")
    for name, ok, t in results:
        if ok is None:
            log(f"  {name:<18} –  (skipped)")
        else:
            log(f"  {name:<18} {'✓' if ok else '✗'}  {t}s")
    log(f"  Total: {total}s")


if __name__ == "__main__":
    main()
