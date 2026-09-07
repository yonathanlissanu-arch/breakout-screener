# LongRunner-2D Paper Trading Bot

Runs a single daily job (`paper_trader.py`) that paper-trades the LongRunner-2D
strategy on SPY. Research/forward-test tool only — no real orders are placed.

## Strategy summary

Each trading day, scan 5-min SPY bars from 10:30am ET onward for the first bar
where |z-score of price vs intraday VWAP| >= 1.5. If that first event is
oversold, buy at the open of the next bar and hold through the close of the 2nd
subsequent trading session. If overbought or no event, no trade. One position at
a time — a new signal is ignored while a trade is open.

Full provenance and the audit that fixed a capital-overlap bug in the original
backtest: `docs/AUDIT_SUMMARY.md`.

## Running it

```bash
cd paper_trading
python paper_trader.py
```

Run once per weekday after the US market close (4:00pm ET). Do not run intraday.

## Cloud scheduling

A scheduled trigger runs this job automatically every weekday at 9:15pm UTC
(= 4:15pm EST / 5:15pm EDT — always after market close). After each run, state
and log files are committed and pushed to git so they persist across ephemeral
container sessions.

The trigger prompt tells the fresh session to: add the repo, clone it, install
requirements, run paper_trader.py, then commit and push `paper_trading/state/`
and `paper_trading/logs/`.

## Modifying strategy parameters

Don't, without pushback. `config.py` params are frozen from the audited
backtest. Changing them based on a few days/weeks of live paper results defeats
the purpose of the forward test. Ask for confirmation first.

## Files

```
config.py                       frozen strategy parameters and paths
data_fetch.py                   live 5-min bar fetch via yfinance
signal_engine.py                LongRunner-2D signal logic (validated vs backtest)
paper_trader.py                 main daily job
tests/validate_against_backtest.py  re-run to confirm parity vs audited backtest
docs/AUDIT_SUMMARY.md           research/audit that produced these frozen params
state/                          runtime state: open_position.json, trade_ledger.csv, equity_curve.csv
logs/                           runtime logs: paper_trader.log
```
