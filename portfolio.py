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


def _cohort_path(cohort_id: str, direction: str = "long") -> Path:
    prefix = "" if direction == "long" else "short_"
    return COHORTS_DIR / f"{prefix}{cohort_id}.json"


def _all_cohort_paths(direction: str | None = None) -> list[Path]:
    """Return sorted cohort paths. direction='long'|'short'|None (both)."""
    if not COHORTS_DIR.exists():
        return []
    if direction == "long":
        # long cohorts: files that DON'T start with short_
        return sorted(p for p in COHORTS_DIR.glob("*.json") if not p.name.startswith("short_"))
    if direction == "short":
        return sorted(COHORTS_DIR.glob("short_*.json"))
    return sorted(COHORTS_DIR.glob("*.json"))


# --------------------------------------------------------------------------- #
# Shared cohort creation helper
# --------------------------------------------------------------------------- #

def _build_cohort(
    csv_path: str,
    direction: str,
    spy_price: float | None,
    entry_col: str = "pct_above_resistance",
) -> dict | None:
    df = pd.read_csv(csv_path)
    if df.empty:
        return None

    top = df.head(TOP_N)
    entry_week = _next_monday()

    positions = []
    for _, row in top.iterrows():
        price = float(row["price"])
        ext_col = entry_col if entry_col in row.index else (
            "pct_above_resistance" if "pct_above_resistance" in row.index else
            "pct_below_support"
        )
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
            "extension_pct": round(float(row.get(ext_col, 0)), 2),
            "score":         round(float(row.get("score", 0)), 4),
        })

    return {
        "cohort_id":      entry_week,
        "direction":      direction,
        "scan_date":      datetime.now().strftime("%Y-%m-%d"),
        "entry_week":     entry_week,
        "source_csv":     csv_path,
        "positions":      positions,
        "spy_entry":      spy_price,
        "total_notional": NOTIONAL_PER_STOCK * len(positions),
        "hold_weeks":     HOLD_WEEKS,
        "status":         "active",
        "snapshots":      [],
    }


def _fetch_spy_price() -> float | None:
    spy_data = fetch_price_data_yahoo(
        [SPY_TICKER], history_years=1,
        cache_dir=str(PORTFOLIO_DIR / "cache"),
        cache_max_age_hours=1,
    )
    return float(spy_data[SPY_TICKER]["Close"].iloc[-1]) if SPY_TICKER in spy_data else None


# --------------------------------------------------------------------------- #
# Add a new LONG cohort from the latest breakout scan CSV
# --------------------------------------------------------------------------- #

def cmd_add(csv_path: str | None = None) -> None:
    """Create a new long cohort from the latest (or specified) breakout scan CSV."""
    if csv_path is None:
        csvs = sorted(Path("results").glob("breakout_scan_*.csv"))
        if not csvs:
            raise FileNotFoundError("No scan results found. Run `python main.py` first.")
        csv_path = str(csvs[-1])

    entry_week = _next_monday()
    path = _cohort_path(entry_week, "long")
    if path.exists():
        print(f"Long cohort {entry_week} already exists — skipping. Delete {path} to re-add.")
        return

    spy_price = _fetch_spy_price()
    cohort = _build_cohort(csv_path, "long", spy_price)
    if cohort is None:
        print("No candidates in the scan CSV.")
        return

    _save_cohort(cohort, path)
    _print_cohort_summary(cohort, path)


# --------------------------------------------------------------------------- #
# Add a new SHORT cohort from the latest breakdown scan CSV
# --------------------------------------------------------------------------- #

def cmd_add_short(csv_path: str | None = None) -> None:
    """Create a new short cohort from the latest (or specified) breakdown scan CSV."""
    if csv_path is None:
        csvs = sorted(Path("results").glob("breakdown_scan_*.csv"))
        if not csvs:
            raise FileNotFoundError("No breakdown scan results found. Run `python main.py --direction short` first.")
        csv_path = str(csvs[-1])

    entry_week = _next_monday()
    path = _cohort_path(entry_week, "short")
    if path.exists():
        print(f"Short cohort {entry_week} already exists — skipping. Delete {path} to re-add.")
        return

    spy_price = _fetch_spy_price()
    cohort = _build_cohort(csv_path, "short", spy_price, entry_col="pct_below_support")
    if cohort is None:
        print("No candidates in the breakdown scan CSV.")
        return

    _save_cohort(cohort, path)
    _print_cohort_summary(cohort, path)


def _print_cohort_summary(cohort: dict, path: Path) -> None:
    direction = cohort.get("direction", "long")
    spy = cohort.get("spy_entry")
    print(f"\n{direction.upper()} Cohort {cohort['cohort_id']} created → {path}")
    print(f"  {len(cohort['positions'])} positions, ${cohort['total_notional']:,.0f} notional")
    print(f"  SPY entry: ${spy:.2f}" if spy else "  SPY entry: N/A")
    for p in cohort["positions"]:
        print(f"  {p['ticker']:6s}  {p['name'][:30]:30s}  entry ${p['entry_price']:.2f}")


# --------------------------------------------------------------------------- #
# Update all active cohorts with current prices
# --------------------------------------------------------------------------- #

def cmd_update() -> None:
    """Fetch current prices for every active cohort (long + short) and record snapshots."""
    paths = _all_cohort_paths()   # all directions
    if not paths:
        print("No cohorts found. Run `python portfolio.py add` first.")
        return

    active = [_load_cohort(p) for p in paths if _load_cohort(p)["status"] == "active"]
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
        direction = cohort.get("direction", "long")
        snapshot = {"date": today, "positions": {}, "portfolio_value": 0.0, "spy_value": None}

        for pos in cohort["positions"]:
            t = pos["ticker"]
            if t in price_data and not price_data[t].empty:
                current = float(price_data[t]["Close"].iloc[-1])
                entry   = pos["entry_price"]
                # Long: profit when price rises; Short: profit when price falls
                if direction == "short":
                    pnl_pct = (entry - current) / entry * 100
                else:
                    pnl_pct = (current - entry) / entry * 100
                pos_value = pos["notional"] * (1 + pnl_pct / 100)
                snapshot["positions"][t] = {
                    "current_price": round(current, 2),
                    "pnl_pct":       round(pnl_pct, 2),
                    "value":         round(pos_value, 2),
                }
                snapshot["portfolio_value"] += pos_value

        if SPY_TICKER in price_data and cohort.get("spy_entry"):
            spy_cur = float(price_data[SPY_TICKER]["Close"].iloc[-1])
            spy_ret = (spy_cur - cohort["spy_entry"]) / cohort["spy_entry"] * 100
            snapshot["spy_value"] = round(spy_ret, 2)

        snapshot["portfolio_value"] = round(snapshot["portfolio_value"], 2)
        portfolio_ret = (snapshot["portfolio_value"] - cohort["total_notional"]) / cohort["total_notional"] * 100
        snapshot["portfolio_return_pct"] = round(portfolio_ret, 2)
        snapshot["alpha"] = round(portfolio_ret - (snapshot["spy_value"] or 0), 2)

        entry_dt = datetime.strptime(cohort["entry_week"], "%Y-%m-%d")
        weeks_elapsed = (datetime.today() - entry_dt).days // 7
        cohort["weeks_elapsed"] = weeks_elapsed
        if weeks_elapsed >= HOLD_WEEKS:
            cohort["status"] = "graduated"
            cohort["final_snapshot"] = snapshot

        if not cohort["snapshots"] or cohort["snapshots"][-1]["date"] != today:
            cohort["snapshots"].append(snapshot)

        _save_cohort(cohort, _cohort_path(cohort["cohort_id"], direction))
        arrow = "▲" if portfolio_ret >= 0 else "▼"
        print(
            f"  [{direction:5s}] {cohort['cohort_id']}  "
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
            "direction": c.get("direction", "long"),
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
    """Generate combined long/short/SPY HTML performance report."""
    all_cohorts = [_load_cohort(p) for p in _all_cohort_paths()]
    if not all_cohorts:
        return "<p>No cohorts yet.</p>"

    long_cohorts  = [c for c in all_cohorts if c.get("direction", "long") == "long"]
    short_cohorts = [c for c in all_cohorts if c.get("direction", "long") == "short"]

    long_active  = [c for c in long_cohorts  if c["status"] == "active"]
    short_active = [c for c in short_cohorts if c["status"] == "active"]
    long_grad    = [c for c in long_cohorts  if c["status"] == "graduated"]
    short_grad   = [c for c in short_cohorts if c["status"] == "graduated"]

    generated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    def _rs(v, color_sign=True):
        if v is None: return "<span style='color:#4d718a'>—</span>"
        col = ("#2edda0" if v >= 0 else "#f87171") if color_sign else "inherit"
        sign = "+" if v >= 0 else ""
        return f"<span style='color:{col}'>{sign}{v:.1f}%</span>"

    def _cohort_row(c):
        last     = c["snapshots"][-1] if c["snapshots"] else {}
        port_ret = last.get("portfolio_return_pct")
        spy_ret  = last.get("spy_value")
        alpha    = last.get("alpha")
        weeks    = c.get("weeks_elapsed", 0)
        tickers  = " ".join(p["ticker"] for p in c["positions"])
        badge    = "LONG" if c.get("direction","long") == "long" else "SHORT"
        bcol     = "#00c5a5" if badge == "LONG" else "#f87171"
        prog_w   = min(weeks / c["hold_weeks"] * 100, 100)
        return (
            f"<tr>"
            f"<td><span style='font-size:10px;padding:1px 5px;border:1px solid {bcol};"
            f"color:{bcol};font-weight:600'>{badge}</span> {c['cohort_id']}</td>"
            f"<td style='font-size:11px;color:#4d718a'>{tickers}</td>"
            f"<td style='text-align:right'>{_rs(port_ret)}</td>"
            f"<td style='text-align:right'>{_rs(spy_ret)}</td>"
            f"<td style='text-align:right'>{_rs(alpha)}</td>"
            f"<td><div style='display:flex;align-items:center;gap:6px'>"
            f"<div style='flex:1;height:3px;background:#1c3150;min-width:50px'>"
            f"<div style='width:{prog_w:.0f}%;height:100%;background:#00c5a5'></div></div>"
            f"<span style='font-size:10px;color:#4d718a;white-space:nowrap'>{weeks}/{c['hold_weeks']}</span>"
            f"</div></td>"
            f"</tr>"
        )

    def _picks_rows(cohort):
        last_snap = cohort["snapshots"][-1] if cohort["snapshots"] else {}
        pos_snaps = last_snap.get("positions", {})
        rows = ""
        for pos in cohort["positions"]:
            t    = pos["ticker"]
            snap = pos_snaps.get(t, {})
            cur  = snap.get("current_price", pos["entry_price"])
            ret  = snap.get("pnl_pct", 0.0)
            rows += (
                f"<tr>"
                f"<td><strong style='font-family:monospace'>{t}</strong></td>"
                f"<td style='color:#4d718a;font-size:12px'>{pos['name'][:26]}</td>"
                f"<td style='font-size:11px'>{pos['indices']}</td>"
                f"<td style='text-align:right;font-family:monospace'>${pos['entry_price']:.2f}</td>"
                f"<td style='text-align:right;font-family:monospace'>${cur:.2f}</td>"
                f"<td style='text-align:right'>{_rs(ret)}</td>"
                f"<td style='text-align:right;font-family:monospace'>{pos['volume_ratio']}×</td>"
                f"<td style='text-align:right;font-family:monospace'>{pos['rsi14']}</td>"
                f"</tr>"
            )
        return rows

    # Build comparison table (weeks where both long + short cohorts exist)
    long_by_week  = {c["cohort_id"]: c for c in long_cohorts}
    short_by_week = {c["cohort_id"]: c for c in short_cohorts}
    all_weeks     = sorted(set(long_by_week) | set(short_by_week))
    comparison_rows = ""
    for wk in all_weeks:
        lc = long_by_week.get(wk)
        sc = short_by_week.get(wk)
        lsnap = (lc["snapshots"][-1] if lc and lc["snapshots"] else {})
        ssnap = (sc["snapshots"][-1] if sc and sc["snapshots"] else {})
        spy_ret = lsnap.get("spy_value") or ssnap.get("spy_value")
        l_ret   = lsnap.get("portfolio_return_pct")
        s_ret   = ssnap.get("portfolio_return_pct")
        comparison_rows += (
            f"<tr>"
            f"<td style='font-family:monospace;font-size:12px'>{wk}</td>"
            f"<td style='text-align:right'>{_rs(l_ret) if lc else '<span style=color:#4d718a>—</span>'}</td>"
            f"<td style='text-align:right'>{_rs(s_ret) if sc else '<span style=color:#4d718a>—</span>'}</td>"
            f"<td style='text-align:right'>{_rs(spy_ret, color_sign=False)}</td>"
            f"</tr>"
        )
    if not comparison_rows:
        comparison_rows = "<tr><td colspan='4' style='color:#4d718a;text-align:center'>No data yet — runs weekly.</td></tr>"

    # Stat calculations
    def _avg_alpha_winrate(cohort_list):
        alphas = [c["snapshots"][-1].get("alpha", 0) for c in cohort_list if c["snapshots"]]
        if not alphas:
            return None, None
        return sum(alphas)/len(alphas), sum(1 for a in alphas if a > 0)/len(alphas)*100

    la_alpha, la_wr = _avg_alpha_winrate(long_grad)
    sa_alpha, sa_wr = _avg_alpha_winrate(short_grad)

    def _stat_val(v, pct=False):
        if v is None: return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.1f}%"

    # Latest picks sections
    picks_html = ""
    if long_active:
        lc = sorted(long_active, key=lambda x: x["cohort_id"])[-1]
        picks_html += (
            f'<div class="card">'
            f'<h2>Long Picks — entry {lc["entry_week"]}</h2>'
            f'<div style="overflow-x:auto"><table>'
            f'<tr><th>Ticker</th><th>Name</th><th>Index</th>'
            f'<th style="text-align:right">Entry</th><th style="text-align:right">Current</th>'
            f'<th style="text-align:right">Return</th><th style="text-align:right">Vol</th>'
            f'<th style="text-align:right">RSI</th></tr>'
            f'{_picks_rows(lc)}</table></div></div>'
        )
    if short_active:
        sc = sorted(short_active, key=lambda x: x["cohort_id"])[-1]
        picks_html += (
            f'<div class="card">'
            f'<h2>Short Picks — entry {sc["entry_week"]}</h2>'
            f'<div style="overflow-x:auto"><table>'
            f'<tr><th>Ticker</th><th>Name</th><th>Index</th>'
            f'<th style="text-align:right">Entry</th><th style="text-align:right">Current</th>'
            f'<th style="text-align:right">Return</th><th style="text-align:right">Vol</th>'
            f'<th style="text-align:right">RSI</th></tr>'
            f'{_picks_rows(sc)}</table></div></div>'
        )

    active_rows = "".join(_cohort_row(c) for c in sorted(
        long_active + short_active, key=lambda x: x["cohort_id"]))
    grad_rows = "".join(_cohort_row(c) for c in sorted(
        long_grad + short_grad, key=lambda x: x["cohort_id"]))

    table_head = ("<tr><th>Cohort</th><th>Tickers</th>"
                  "<th style='text-align:right'>Portfolio</th>"
                  "<th style='text-align:right'>SPY</th>"
                  "<th style='text-align:right'>Alpha</th>"
                  "<th>Progress</th></tr>")

    html = f"""<title>Breakout Portfolio</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
  :root {{
    --bg:#081322;--surface:#0f1e32;--surface2:#142538;--border:#1c3150;
    --accent:#00c5a5;--text:#d4e5f7;--muted:#4d718a;--gain:#2edda0;--loss:#f87171;
  }}
  @media(prefers-color-scheme:light){{
    :root:not([data-theme="dark"]){{
      --bg:#edf1f8;--surface:#fff;--surface2:#f5f8fc;--border:#cad5e8;
      --accent:#007d6a;--text:#0c1c2e;--muted:#527091;--gain:#0fad74;--loss:#dc4444;
    }}
  }}
  :root[data-theme="dark"]{{
    --bg:#081322;--surface:#0f1e32;--surface2:#142538;--border:#1c3150;
    --accent:#00c5a5;--text:#d4e5f7;--muted:#4d718a;--gain:#2edda0;--loss:#f87171;
  }}
  :root[data-theme="light"]{{
    --bg:#edf1f8;--surface:#fff;--surface2:#f5f8fc;--border:#cad5e8;
    --accent:#007d6a;--text:#0c1c2e;--muted:#527091;--gain:#0fad74;--loss:#dc4444;
  }}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'Figtree',system-ui,sans-serif;
        font-size:14px;line-height:1.5;padding:24px;}}
  .wrap{{max-width:1100px;margin:0 auto}}
  .header{{padding:28px 0 24px;border-bottom:1px solid var(--border);margin-bottom:24px}}
  .eyebrow{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);
            font-weight:600;margin-bottom:8px}}
  h1{{font-size:clamp(22px,4vw,34px);font-weight:700;color:var(--text);line-height:1.1}}
  h1 span{{color:var(--accent)}}
  .sub{{font-size:12px;color:var(--muted);margin-top:6px}}
  .stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:var(--border);
          border:1px solid var(--border);margin-bottom:24px}}
  @media(max-width:700px){{.stats{{grid-template-columns:repeat(2,1fr)}}}}
  .stat{{background:var(--surface);padding:16px 18px}}
  .stat-label{{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
               font-weight:600;margin-bottom:6px}}
  .stat-value{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500;
               line-height:1;font-variant-numeric:tabular-nums}}
  .stat-sub{{font-size:10px;color:var(--muted);margin-top:4px}}
  .card{{background:var(--surface);border:1px solid var(--border);padding:20px;margin-bottom:20px}}
  h2{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
      font-weight:600;margin-bottom:14px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{text-align:left;padding:8px 12px;font-size:10px;letter-spacing:.06em;
      text-transform:uppercase;color:var(--muted);font-weight:600;border-bottom:1px solid var(--border)}}
  td{{padding:11px 12px;border-bottom:1px solid var(--border);vertical-align:middle;
      font-variant-numeric:tabular-nums}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:var(--surface2)}}
  .gain{{color:var(--gain)}} .loss{{color:var(--loss)}}
  .foot{{margin-top:32px;padding-top:16px;border-top:1px solid var(--border);
         font-size:11px;color:var(--muted);line-height:1.7}}
</style>

<div class="wrap">
  <div class="header">
    <div class="eyebrow">Paper Trading · Breakout / Breakdown Monitor</div>
    <h1>Long <span>&amp;</span> Short Portfolio</h1>
    <div class="sub">Weekly top-10 breakouts (long) + top-10 breakdowns (short) · 52-week hold · Benchmark: SPY · {generated}</div>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="stat-label">Long Active</div>
      <div class="stat-value">{len(long_active)}</div>
      <div class="stat-sub">cohorts</div>
    </div>
    <div class="stat">
      <div class="stat-label">Short Active</div>
      <div class="stat-value">{len(short_active)}</div>
      <div class="stat-sub">cohorts</div>
    </div>
    <div class="stat">
      <div class="stat-label">Long Alpha</div>
      <div class="stat-value" style="color:var(--gain)">{_stat_val(la_alpha)}</div>
      <div class="stat-sub">graduated avg</div>
    </div>
    <div class="stat">
      <div class="stat-label">Short Alpha</div>
      <div class="stat-value" style="color:var(--gain)">{_stat_val(sa_alpha)}</div>
      <div class="stat-sub">graduated avg</div>
    </div>
    <div class="stat">
      <div class="stat-label">Long Win Rate</div>
      <div class="stat-value">{_stat_val(la_wr)}</div>
      <div class="stat-sub">vs SPY</div>
    </div>
    <div class="stat">
      <div class="stat-label">Short Win Rate</div>
      <div class="stat-value">{_stat_val(sa_wr)}</div>
      <div class="stat-sub">vs SPY</div>
    </div>
  </div>

  <div class="card">
    <h2>Long vs Short vs SPY — Weekly Comparison</h2>
    <div style="overflow-x:auto"><table>
      <tr><th>Entry Week</th>
          <th style="text-align:right">Long Portfolio</th>
          <th style="text-align:right">Short Portfolio</th>
          <th style="text-align:right">SPY</th></tr>
      {comparison_rows}
    </table></div>
  </div>

  {picks_html}

  <div class="card">
    <h2>All Active Cohorts</h2>
    {"<div style='overflow-x:auto'><table>" + table_head + active_rows + "</table></div>" if active_rows else "<p style='color:var(--muted)'>No active cohorts.</p>"}
  </div>

  <div class="card">
    <h2>Graduated Cohorts (52 weeks)</h2>
    {"<div style='overflow-x:auto'><table>" + table_head + grad_rows + "</table></div>" if grad_rows else "<p style='color:var(--muted)'>No graduated cohorts yet — first in ~52 weeks.</p>"}
  </div>

  <div class="foot">
    Paper trading only — not financial advice. Entry = Friday close at scan time (Monday open proxy).
    $10,000 per position, equal-weight. Short P&amp;L = (entry − current) / entry.
    SPY total-return benchmark. Screener runs every Sunday 22:00 UTC.
  </div>
</div>"""

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
    p.add_argument("command", choices=["add", "add-short", "update", "report", "status"])
    p.add_argument("--csv", help="Scan CSV to use for 'add' or 'add-short' (default: latest)")
    args = p.parse_args()

    if args.command == "add":
        cmd_add(args.csv)
    elif args.command == "add-short":
        cmd_add_short(args.csv)
    elif args.command == "update":
        cmd_update()
    elif args.command == "report":
        cmd_report()
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()
