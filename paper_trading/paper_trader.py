"""
LongRunner-2D paper trader -- daily job.

Intended to run ONCE per day, after the US market close (see README for
scheduling this via Claude Code cloud scheduled tasks). Each run:

  1. Fetches recent 5-min SPY bars.
  2. If a paper position is open and today is (or is past) its planned exit
     date, closes it at today's close and logs the trade.
  3. If no position is open (after step 2), scans TODAY for a LongRunner-2D
     long signal and opens a paper position if one fired.
  4. Marks the account to market, records today's equity, the SPY buy-and-hold
     benchmark equity, and the cumulative alpha vs that benchmark.

Single-position constraint: a new signal is ignored while a position is
open. This matches the constraint validated in the audited backtest
(taking every overlapping signal without it implicitly assumed leverage).

Benchmark: on the first run, the SPY close is recorded as the anchor.
Every subsequent run computes what a passive $100k SPY buy-and-hold would
be worth today, and logs the alpha (strategy equity minus benchmark equity,
expressed as a percentage of starting capital).

This is a PAPER TRADING research tool. It does not place real orders and
is not connected to a broker. It is not financial advice.
"""
import json
import logging
import sys
from datetime import date

import pandas as pd

import config as C
from data_fetch import fetch_recent_bars
from signal_engine import compute_features, find_signal_for_date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(C.LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("longrunner")


def load_position():
    if C.POSITION_FILE.exists():
        return json.loads(C.POSITION_FILE.read_text())
    return None


def save_position(pos):
    if pos is None:
        if C.POSITION_FILE.exists():
            C.POSITION_FILE.unlink()
    else:
        C.POSITION_FILE.write_text(json.dumps(pos, indent=2, default=str))


def get_equity():
    if C.EQUITY_FILE.exists():
        eq = pd.read_csv(C.EQUITY_FILE)
        if len(eq):
            return float(eq.iloc[-1]["equity"])
    return C.STARTING_EQUITY


def load_benchmark():
    if C.BENCHMARK_FILE.exists():
        return json.loads(C.BENCHMARK_FILE.read_text())
    return None


def save_benchmark(b):
    C.BENCHMARK_FILE.write_text(json.dumps(b, indent=2, default=str))


def append_csv_row(path, row: dict):
    df_row = pd.DataFrame([row])
    if path.exists():
        df_row.to_csv(path, mode="a", header=False, index=False)
    else:
        df_row.to_csv(path, mode="w", header=True, index=False)


def already_ran_today(trading_day) -> bool:
    """Return True if equity_curve.csv already has a row for this trading day."""
    if not C.EQUITY_FILE.exists():
        return False
    eq = pd.read_csv(C.EQUITY_FILE)
    return str(trading_day) in eq["date"].astype(str).values


def run():
    log.info("=" * 60)
    log.info("LongRunner-2D daily paper trading run starting")

    try:
        bars = fetch_recent_bars()
    except Exception as e:
        log.error(f"Data fetch failed: {e}")
        return

    trading_dates = sorted(bars["date"].unique())
    today = trading_dates[-1]
    log.info(f"Latest trading day in data: {today} ({len(trading_dates)} days fetched)")

    if already_ran_today(today):
        log.info(f"Already processed {today} in a previous run -- skipping (weekend/holiday re-run guard).")
        log.info("=" * 60)
        return

    feat = compute_features(bars)
    position = load_position()
    equity = get_equity()

    # ---- Benchmark: record SPY anchor on first run ----
    benchmark = load_benchmark()
    today_spy_close = float(bars[bars["date"] == today].iloc[-1]["close"])
    if benchmark is None:
        benchmark = {"start_date": str(today), "spy_start_price": today_spy_close}
        save_benchmark(benchmark)
        log.info(f"Benchmark anchor set: SPY @ {today_spy_close:.2f} on {today} "
                 f"(${C.STARTING_EQUITY:,.2f} buy-and-hold reference)")

    spy_benchmark_equity = C.STARTING_EQUITY * (today_spy_close / benchmark["spy_start_price"])

    # ---- Step 1: check for exit ----
    if position is not None:
        entry_date = date.fromisoformat(position["entry_date"])
        idx_entry = trading_dates.index(entry_date) if entry_date in trading_dates else None
        if idx_entry is not None:
            sessions_elapsed = len(trading_dates) - 1 - idx_entry
            target_idx = idx_entry + C.HOLD_SESSIONS_AHEAD
            if today == trading_dates[min(target_idx, len(trading_dates) - 1)] and sessions_elapsed >= C.HOLD_SESSIONS_AHEAD:
                exit_price = today_spy_close
                entry_price = position["entry_price"]
                gross = exit_price / entry_price - 1.0
                net = gross - C.ROUND_TRIP_COST
                pnl_dollars = position["notional"] * net
                new_equity = equity + pnl_dollars

                log.info(f"EXIT LongRunner-2D trade: entry {position['entry_date']} @ {entry_price:.2f} "
                         f"-> exit {today} @ {exit_price:.2f} | net_return={net:.4%} | "
                         f"P&L=${pnl_dollars:,.2f} | new equity=${new_equity:,.2f}")

                append_csv_row(C.LEDGER_FILE, {
                    "entry_date": position["entry_date"], "entry_time_et": position["entry_time_et"],
                    "entry_price": entry_price, "exit_date": str(today), "exit_price": exit_price,
                    "notional": position["notional"], "gross_return": gross, "net_return": net,
                    "pnl_dollars": pnl_dollars, "equity_after": new_equity,
                })
                equity = new_equity
                position = None
                save_position(position)
            else:
                log.info(f"Position open since {position['entry_date']} "
                         f"({sessions_elapsed}/{C.HOLD_SESSIONS_AHEAD} sessions elapsed) -- holding.")
        else:
            log.warning(f"Open position's entry_date {entry_date} not found in fetched window "
                        f"(state file may be stale or lookback too short) -- holding, will retry next run.")

    # ---- Step 2: check for new entry ----
    if position is None:
        sig = find_signal_for_date(feat, today)
        if sig is not None:
            notional = equity  # 100% of current paper equity, single position
            position = {
                "entry_date": str(sig["signal_date"]),
                "entry_time_et": str(sig["entry_time_et"]),
                "entry_price": sig["entry_price"],
                "signal_z": sig["z"],
                "notional": notional,
            }
            save_position(position)
            log.info(f"NEW ENTRY: LongRunner-2D long signal at {sig['signal_time_et']} "
                     f"(z={sig['z']:.2f}) -> entered at {sig['entry_time_et']} @ {sig['entry_price']:.2f}, "
                     f"notional=${notional:,.2f}")
        else:
            log.info(f"No LongRunner-2D signal on {today}. Flat.")

    # ---- Step 3: mark to market and record equity + benchmark ----
    if position is not None:
        unrealized = position["notional"] * (today_spy_close / position["entry_price"] - 1.0)
        mtm_equity = equity + unrealized
    else:
        mtm_equity = equity

    alpha_pct = (mtm_equity - spy_benchmark_equity) / C.STARTING_EQUITY * 100
    alpha_sign = "+" if alpha_pct >= 0 else ""

    append_csv_row(C.EQUITY_FILE, {
        "date": str(today),
        "equity": mtm_equity,
        "spy_equity": spy_benchmark_equity,
        "alpha_pct": alpha_pct,
        "position_open": position is not None,
    })

    log.info(
        f"End of run {today}: "
        f"strategy=${mtm_equity:,.2f} | "
        f"SPY buy-hold=${spy_benchmark_equity:,.2f} | "
        f"alpha={alpha_sign}{alpha_pct:.2f}% | "
        f"position_open={position is not None}"
    )
    log.info("=" * 60)


if __name__ == "__main__":
    run()
