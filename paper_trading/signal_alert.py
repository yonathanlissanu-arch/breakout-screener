"""
LongRunner-2D intraday signal alert -- read-only, informational only.

Run this during market hours to get early notification when a LongRunner-2D
signal fires intraday. This script never touches state files or the equity
curve. The end-of-day paper_trader.py run books the actual paper trade.

Exits 0 = no signal yet today.
Exits 1 = signal found (details printed to stdout).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_fetch import fetch_recent_bars
from signal_engine import compute_features, find_signal_for_date


def check():
    try:
        bars = fetch_recent_bars()
    except Exception as e:
        print(f"Data fetch failed: {e}", file=sys.stderr)
        return False

    trading_dates = sorted(bars["date"].unique())
    today = trading_dates[-1]
    today_bars = bars[bars["date"] == today]

    feat = compute_features(bars)
    sig = find_signal_for_date(feat, today)

    if sig is None:
        print(f"No LongRunner-2D signal on {today} yet "
              f"({len(today_bars)} of ~78 bars complete).")
        return False

    print("=" * 55)
    print(f"  LONGRUNNER-2D SIGNAL FIRED -- {today}")
    print("=" * 55)
    print(f"  Signal time : {sig['signal_time_et']}  (z = {sig['z']:.2f})")
    print(f"  Entry time  : {sig['entry_time_et']}")
    print(f"  Entry price : ${sig['entry_price']:.2f}")
    print(f"  Hold target : close of 2nd subsequent trading session")
    print(f"  Action      : review chart manually, then tonight's")
    print(f"                paper_trader.py run will book the entry.")
    print("=" * 55)
    return True


if __name__ == "__main__":
    sys.exit(1 if check() else 0)
