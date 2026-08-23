"""
portfolio.py — Paper trading portfolio tracker.

Each week's top-10 breakout picks form a "cohort" held for 52 weeks.
Weekly P&L is tracked against SPY as benchmark.

Usage
-----
    python portfolio.py add    [--csv results/breakout_scan_*.csv]
    python portfolio.py update
    python portfolio.py report
    python portfolio.py status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from fetcher_yahoo import fetch_price_data_yahoo

logger = logging.getLogger(__name__)

PORTFOLIO_DIR = Path("portfolio")
COHORTS_DIR   = PORTFOLIO_DIR / "cohorts"
NOTIONAL_PER_STOCK = 10_000.0   # $10,000 per position
TOP_N          = 10
HOLD_WEEKS     = 52
SPY_TICKER     = "SPY"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _next_monday(ref: datetime | None = None) -> str:
    ref = ref or datetime.today()
    days_ahead = (7 - ref.weekday()) % 7 or 7   # days until next Monday
    return (ref + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def _load_cohort(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _save_cohort(cohort: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cohort, f, indent=2, default=str)


def _cohort_path(cohort_id: str) -> Path:
    return COHORTS_DIR / f"{cohort_id}.json"


def _all_cohort_paths() -> list[Path]:
    if not COHORTS_DIR.exists():
        return []
    return sorted(COHORTS_DIR.glob("*.json"))


# --------------------------------------------------------------------------- #
# Add a new cohort from the latest scan CSV
# --------------------------------------------------------------------------- #

def cmd_add(csv_path: str | None = None) -> None:
    """
    Create a new cohort from the latest (or specified) scan CSV.
    Entry price = price at time of scan (Friday close ≈ Monday open proxy).
    """
    if csv_path is None:
        results_dir = Path("results")
        csvs = sorted(results_dir.glob("breakout_scan_*.csv"))
        if not csvs:
            raise FileNotFoundError("No scan results found. Run `python main.py` first.")
        csv_path = str(csvs[-1])

    df = pd.read_csv(csv_path)
    if df.empty:
        print("No candidates in the scan CSV.")
        return

    top10 = df.head(TOP_N)
    entry_week = _next_monday()          # the Monday they'd be purchased
    cohort_id  = entry_week
    path = _cohort_path(cohort_id)

    if path.exists():
        print(f"Cohort {cohort_id} already exists — skipping. Delete {path} to re-add.")
        return

    # Fetch SPY entry price
    spy_data = fetch_price_data_yahoo(
        [SPY_TICKER], history_years=1,
        cache_dir=str(PORTFOLIO_DIR / "cache"),
        cache_max_age_hours=1,
    )
    spy_price = float(spy_data[SPY_TICKER]["Close"].iloc[-1]) if SPY_TICKER in spy_data else None

    positions = []
    for _, row in top10.iterrows():
        price = float(row["price"])
        positions.append({
            "ticker":        str(row["ticker"]),
            "name":          str(row.get("name", "")),
            "indices":       str(row.get("indices", "")),
            "entry_price":   price,
            "shares":        round(NOTIONAL_PER_STOCK / price, 4),
            "notional":      NOTIONAL_PER_STOCK,
            "breakout_date": str(row.get("breakout_date", ""))[:10],
            "volume_ratio":  round(float(row.get("volume_ratio", 0)), 2),
            "rsi14":         round(float(row.get("rsi14", 0)), 1),
            "pct_above_resistance": round(float(row.get("pct_above_resistance", 0)), 2),
            "score":         round(float(row.get("score", 0)), 4),
        })

    scan_date = datetime.now().strftime("%Y-%m-%d")
    total_notional = NOTIONAL_PER_STOCK * len(positions)

    cohort = {
        "cohort_id":     cohort_id,
        "scan_date":     scan_date,
        "entry_week":    entry_week,
        "source_csv":    csv_path,
        "positions":     positions,
        "spy_entry":     spy_price,
        "total_notional": total_notional,
        "hold_weeks":    HOLD_WEEKS,
        "status":        "active",
        "snapshots":     [],     # filled in by cmd_update
    }

    _save_cohort(cohort, path)
    print(f"\nCohort {cohort_id} created → {path}")
    print(f"  {len(positions)} positions, ${total_notional:,.0f} notional")
    print(f"  SPY entry: ${spy_price:.2f}" if spy_price else "  SPY entry: N/A")
    for p in positions:
        print(f"  {p['ticker']:6s}  {p['name'][:30]:30s}  entry ${p['entry_price']:.2f}")


# --------------------------------------------------------------------------- #
# Update all active cohorts with current prices
# --------------------------------------------------------------------------- #

def cmd_update() -> None:
    """Fetch current prices for every active cohort and record a weekly snapshot."""
    paths = _all_cohort_paths()
    if not paths:
        print("No cohorts found. Run `python portfolio.py add` first.")
        return

    # Collect all unique tickers across active cohorts + SPY
    active, graduated = [], []
    for p in paths:
        c = _load_cohort(p)
        (active if c["status"] == "active" else graduated).append(c)

    if not active:
        print("No active cohorts to update.")
        return

    all_tickers = list({t["ticker"] for c in active for t in c["positions"]}) + [SPY_TICKER]
    price_data = fetch_price_data_yahoo(
        all_tickers, history_years=1,
        cache_dir=str(PORTFOLIO_DIR / "cache"),
        cache_max_age_hours=1,
    )

    today = datetime.today().strftime("%Y-%m-%d")

    for cohort in active:
        snapshot = {"date": today, "positions": {}, "portfolio_value": 0.0, "spy_value": None}

        for pos in cohort["positions"]:
            t = pos["ticker"]
            if t in price_data and not price_data[t].empty:
                current = float(price_data[t]["Close"].iloc[-1])
                pnl_pct = (current - pos["entry_price"]) / pos["entry_price"] * 100
                pos_value = pos["shares"] * current
                snapshot["positions"][t] = {
                    "current_price": round(current, 2),
                    "pnl_pct":       round(pnl_pct, 2),
                    "value":         round(pos_value, 2),
                }
                snapshot["portfolio_value"] += pos_value

        # SPY benchmark
        if SPY_TICKER in price_data and cohort.get("spy_entry"):
            spy_cur = float(price_data[SPY_TICKER]["Close"].iloc[-1])
            spy_ret = (spy_cur - cohort["spy_entry"]) / cohort["spy_entry"] * 100
            snapshot["spy_value"] = round(spy_ret, 2)

        snapshot["portfolio_value"] = round(snapshot["portfolio_value"], 2)
        portfolio_ret = (snapshot["portfolio_value"] - cohort["total_notional"]) / cohort["total_notional"] * 100
        snapshot["portfolio_return_pct"] = round(portfolio_ret, 2)
        snapshot["alpha"] = round(portfolio_ret - (snapshot["spy_value"] or 0), 2)

        # Check if graduated (52 weeks elapsed)
        entry = datetime.strptime(cohort["entry_week"], "%Y-%m-%d")
        weeks_elapsed = (datetime.today() - entry).days // 7
        cohort["weeks_elapsed"] = weeks_elapsed
        if weeks_elapsed >= HOLD_WEEKS:
            cohort["status"] = "graduated"
            cohort["final_snapshot"] = snapshot

        # Avoid duplicate snapshots for the same date
        if not cohort["snapshots"] or cohort["snapshots"][-1]["date"] != today:
            cohort["snapshots"].append(snapshot)

        _save_cohort(cohort, _cohort_path(cohort["cohort_id"]))
        arrow = "▲" if portfolio_ret >= 0 else "▼"
        print(
            f"  {cohort['cohort_id']}  "
            f"port {arrow}{abs(portfolio_ret):.1f}%  "
            f"SPY {snapshot['spy_value']:+.1f}%  "
            f"alpha {snapshot['alpha']:+.1f}%  "
            f"(week {weeks_elapsed}/{HOLD_WEEKS})"
        )

    print(f"\nUpdated {len(active)} active cohorts.")


# --------------------------------------------------------------------------- #
# Status summary
# --------------------------------------------------------------------------- #

def cmd_status() -> None:
    paths = _all_cohort_paths()
    if not paths:
        print("No cohorts. Run `python portfolio.py add` first.")
        return

    rows = []
    for p in paths:
        c = _load_cohort(p)
        last = c["snapshots"][-1] if c["snapshots"] else {}
        rows.append({
            "cohort":    c["cohort_id"],
            "status":    c["status"],
            "tickers":   " ".join(pos["ticker"] for pos in c["positions"]),
            "port_ret":  last.get("portfolio_return_pct", 0.0),
            "spy_ret":   last.get("spy_value", 0.0),
            "alpha":     last.get("alpha", 0.0),
            "weeks":     c.get("weeks_elapsed", 0),
        })

    df = pd.DataFrame(rows)
    print("\n" + df.to_string(index=False))


# --------------------------------------------------------------------------- #
# Report generation (saves HTML to portfolio/report.html)
# --------------------------------------------------------------------------- #

def cmd_report() -> str:
    """
    Generate a full HTML performance report.
    Returns the HTML string (also saves to portfolio/report.html).
    """
    paths = _all_cohort_paths()
    cohorts = [_load_cohort(p) for p in paths]
    if not cohorts:
        return "<p>No cohorts yet.</p>"

    active    = [c for c in cohorts if c["status"] == "active"]
    graduated = [c for c in cohorts if c["status"] == "graduated"]

    def _ret_str(v):
        if v is None: return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.1f}%"

    def _cohort_rows(cohort_list):
        rows = []
        for c in sorted(cohort_list, key=lambda x: x["cohort_id"]):
            last = c["snapshots"][-1] if c["snapshots"] else {}
            port_ret = last.get("portfolio_return_pct")
            spy_ret  = last.get("spy_value")
            alpha    = last.get("alpha")
            weeks    = c.get("weeks_elapsed", 0)
            tickers  = ", ".join(p["ticker"] for p in c["positions"])
            color    = "#22c55e" if (alpha or 0) >= 0 else "#ef4444"
            rows.append(
                f"<tr>"
                f"<td>{c['cohort_id']}</td>"
                f"<td style='font-size:0.8em;color:#9ca3af'>{tickers}</td>"
                f"<td>{_ret_str(port_ret)}</td>"
                f"<td>{_ret_str(spy_ret)}</td>"
                f"<td style='color:{color};font-weight:600'>{_ret_str(alpha)}</td>"
                f"<td>{weeks}/{c['hold_weeks']}</td>"
                f"</tr>"
            )
        return "\n".join(rows)

    # Current week's picks
    current_rows = ""
    if active:
        latest = sorted(active, key=lambda x: x["cohort_id"])[-1]
        last_snap = latest["snapshots"][-1] if latest["snapshots"] else {}
        pos_snaps = last_snap.get("positions", {})
        for pos in latest["positions"]:
            t = pos["ticker"]
            snap = pos_snaps.get(t, {})
            cur  = snap.get("current_price", pos["entry_price"])
            ret  = snap.get("pnl_pct", 0.0)
            color = "#22c55e" if ret >= 0 else "#ef4444"
            current_rows += (
                f"<tr>"
                f"<td><strong>{t}</strong></td>"
                f"<td style='color:#9ca3af'>{pos['name'][:28]}</td>"
                f"<td>{pos['indices']}</td>"
                f"<td>${pos['entry_price']:.2f}</td>"
                f"<td>${cur:.2f}</td>"
                f"<td style='color:{color}'>{_ret_str(ret)}</td>"
                f"<td>{pos['volume_ratio']}×</td>"
                f"<td>{pos['rsi14']}</td>"
                f"</tr>"
            )

    avg_alpha = None
    win_rate  = None
    if graduated:
        alphas = [c["snapshots"][-1].get("alpha", 0) for c in graduated if c["snapshots"]]
        if alphas:
            avg_alpha = sum(alphas) / len(alphas)
            win_rate  = sum(1 for a in alphas if a > 0) / len(alphas) * 100

    generated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    alpha_class   = "green" if (avg_alpha or 0) >= 0 else "red"
    alpha_str     = (f"+{avg_alpha:.1f}%" if avg_alpha is not None else "—")
    winrate_str   = (f"{win_rate:.0f}%" if win_rate is not None else "—")
    picks_section = ""
    if active:
        latest_entry  = sorted(active, key=lambda x: x["cohort_id"])[-1]["entry_week"]
        week_label    = f"This Week's Picks — entry {latest_entry}"
        picks_section = (
            f'<div class="card"><h2>{week_label}</h2>'
            f'<table><tr><th>Ticker</th><th>Name</th><th>Index</th>'
            f'<th>Entry</th><th>Current</th><th>Return</th>'
            f'<th>Vol Ratio</th><th>RSI</th></tr>'
            f'{current_rows}</table></div>'
        )
    active_table = ""
    if active:
        active_table = (
            f'<table><tr><th>Cohort</th><th>Tickers</th><th>Portfolio</th>'
            f'<th>SPY</th><th>Alpha</th><th>Week</th></tr>'
            f'{_cohort_rows(active)}</table>'
        )
    else:
        active_table = '<p style="color:var(--muted)">No active cohorts yet.</p>'
    grad_table = ""
    if graduated:
        grad_table = (
            f'<table><tr><th>Cohort</th><th>Tickers</th><th>Final Return</th>'
            f'<th>SPY Return</th><th>Alpha</th><th>Week</th></tr>'
            f'{_cohort_rows(graduated)}</table>'
        )
    else:
        grad_table = '<p style="color:var(--muted)">No cohorts have graduated yet. First graduation in ~52 weeks.</p>'

    html = f"""<title>Breakout Portfolio</title>
<style>
  :root {{
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #f1f5f9; --muted: #94a3b8; --accent: #38bdf8;
  }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
          margin: 0; padding: 24px; }}
  h1 {{ color: var(--accent); font-size: 1.5rem; margin-bottom: 4px; }}
  .sub {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 28px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 16px; margin-bottom: 28px; }}
  .stat {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
           padding: 18px; }}
  .stat-label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase;
                 letter-spacing: .05em; margin-bottom: 6px; }}
  .stat-value {{ font-size: 1.6rem; font-weight: 700; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
           padding: 20px; margin-bottom: 24px; }}
  h2 {{ font-size: 1rem; color: var(--accent); margin: 0 0 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  th {{ text-align: left; padding: 8px 10px; color: var(--muted); font-weight: 500;
        border-bottom: 1px solid var(--border); }}
  td {{ padding: 9px 10px; border-bottom: 1px solid #1e293b; }}
  tr:last-child td {{ border-bottom: none; }}
  .green {{ color: #22c55e; }} .red {{ color: #ef4444; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 20px;
            font-size: 0.75rem; background: #0c4a6e; color: var(--accent); }}
</style>

<h1>Breakout Portfolio Tracker</h1>
<p class="sub">Weekly top-10 breakout picks · Hold 52 weeks · Benchmark: SPY · Generated {generated}</p>

<div class="grid">
  <div class="stat">
    <div class="stat-label">Active Cohorts</div>
    <div class="stat-value">{len(active)}</div>
  </div>
  <div class="stat">
    <div class="stat-label">Graduated Cohorts</div>
    <div class="stat-value">{len(graduated)}</div>
  </div>
  <div class="stat">
    <div class="stat-label">Avg Alpha (graduated)</div>
    <div class="stat-value {alpha_class}">{alpha_str}</div>
  </div>
  <div class="stat">
    <div class="stat-label">Win Rate vs SPY</div>
    <div class="stat-value">{winrate_str}</div>
  </div>
</div>

{picks_section}

<div class="card">
  <h2>Active Cohorts</h2>
  {active_table}
</div>

<div class="card">
  <h2>Graduated Cohorts (52 weeks complete)</h2>
  {grad_table}
</div>

<p style="color:var(--muted);font-size:0.75rem;margin-top:20px">
  Paper trading only — not financial advice. Entry price = Friday close at scan time.
  Equal-weight $10,000 per position. SPY is total-return benchmark.
</p>"""

    out = PORTFOLIO_DIR / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"Report saved → {out}")
    return html


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="Paper trading portfolio tracker")
    p.add_argument("command", choices=["add", "update", "report", "status"])
    p.add_argument("--csv", help="Scan CSV to use for 'add' (default: latest)")
    args = p.parse_args()

    if args.command == "add":
        cmd_add(args.csv)
    elif args.command == "update":
        cmd_update()
    elif args.command == "report":
        cmd_report()
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()
