"""
LongRunner-2D paper trading configuration.

Parameters are FROZEN from the audited strategy (see /docs/AUDIT_SUMMARY.md
in this bundle, and the frozen_strategy_audit.md from the research session
that produced this). Do not tune these against live results without going
back through a proper discovery/test split -- editing these after seeing
live paper-trading performance defeats the point of a forward test.
"""
from pathlib import Path

# ---- strategy parameters (frozen) ----
TICKER = "SPY"
Z_THRESHOLD = 1.5          # |z-score of price vs intraday VWAP| that triggers a signal
SIGMA_WINDOW = 12          # bars (12 x 5min = 60min) rolling window for z-score std
SLOPE_WINDOW = 6           # bars for VWAP slope calc
MIN_SIGNAL_BAR = 12        # earliest bar index eligible for a signal (bar 12 = 10:30am ET)
HOLD_SESSIONS_AHEAD = 2    # exit at the close of the 2nd subsequent trading session
BARS_PER_DAY_RTH = 78      # 9:30am-4:00pm ET, 5-min bars

# ---- cost model (matches the audited backtest) ----
ROUND_TRIP_COST = 0.0002   # 2 bp round trip, applied to net_return at exit

# ---- paper account ----
STARTING_EQUITY = 100_000.0
SINGLE_POSITION_ONLY = True   # validated constraint: skip new signals while a trade is open

# ---- data ----
YFINANCE_INTERVAL = "5m"
YFINANCE_LOOKBACK = "15d"   # enough buffer to always have the entry day + hold window

# ---- paths ----
ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
POSITION_FILE = STATE_DIR / "open_position.json"
LEDGER_FILE = STATE_DIR / "trade_ledger.csv"
EQUITY_FILE = STATE_DIR / "equity_curve.csv"
BENCHMARK_FILE = STATE_DIR / "benchmark.json"   # SPY buy-and-hold anchor (set on first run)
LOG_FILE = LOG_DIR / "paper_trader.log"

STATE_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
