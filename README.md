# fxdesk

A Python toolkit for forex/CFD **research, backtesting, signal generation and
paper trading**. It pulls historical data from free internet APIs, falls back
across providers, caches locally, and can use MetaTrader 5 (or an MT4 file
bridge) for live broker-consistent prices.

This is research software, not a guaranteed money machine. Read the risk
section at the bottom.

## What it does

1. **Backtester** - event-driven, spread/commission/slippage aware, ATR-based
   stops and targets, position sizing by account risk, equity curve, Sharpe,
   Sortino, drawdown, profit factor, expectancy and CSV/JSON reports.
2. **Validation tools** - walk-forward analysis with per-window parameter
   selection, Monte Carlo trade bootstrapping, and a buy-and-hold benchmark.
3. **Signal scanner** - ranks the best current trade plans with entry, stop,
   target, lot size, risk amount, reward/risk, spread and confidence.
4. **Paper trader** - live quote loop that opens/closes simulated positions,
   persists state to JSON, enforces risk limits and a daily loss cap.
5. **Data layer** - MT5, Twelve Data, Alpha Vantage, Yahoo Finance, Dukascopy
   tick data, Frankfurter/ECB and Stooq, with an on-disk CSV cache.
6. **Broker adapters** - paper broker (built in), native MT5 broker + feed, and
   an optional MT4 file bridge (client + MQL4 EA).

## Install

Python 3.10+ is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Optional extras:

```powershell
pip install -e ".[mt5,plot]"       # MetaTrader5 package + charts
```

`MetaTrader5` is Windows-only and may lag the newest Python releases. Without
it, fxdesk still works with REST data providers.

## Quick start

```powershell
# 1. See what works on this machine
fxdesk doctor --online

# 2. Download and inspect data
fxdesk data fetch --symbol EURUSD --timeframe 1h --start 2026-09-01 --output data/eurusd_1h.csv

# 3. Backtest
fxdesk backtest --symbol EURUSD --timeframe 1h --strategy trend_ma --plot

# 3b. Backtest with a Monte Carlo outcome distribution
fxdesk backtest --symbol EURUSD --timeframe 1h --strategy trend_ma --monte-carlo 1000

# 3c. Walk-forward validation (rolling train/test, per-window tuning)
fxdesk walkforward --symbol EURUSD --timeframe 1h --strategy trend_ma

# 4. Scan for the best current plans
fxdesk signals --symbol EURUSD,GBPUSD,USDJPY --timeframe 1h --strategy composite

# 5. Paper trade one cycle (no real orders)
fxdesk paper --symbol EURUSD,GBPUSD --timeframe 1h --strategy composite --once --reset

# 6. Run the paper loop
fxdesk paper --symbol EURUSD,GBPUSD --timeframe 1h --strategy composite --poll 30
```

Copy `config.example.yaml` to `config.yaml` to change risk, strategies, API keys
and broker settings. The CLI picks up `config.yaml` automatically.

## Data providers

No API key is needed for:

| Provider | Timeframes | Notes |
| --- | --- | --- |
| `yahoo` | 1m..1w | Direct Yahoo chart API. Good free default. Intraday history is limited (1m ~7 days, 5m..30m ~60 days, 1h ~730 days). |
| `dukascopy` | 1m..8h | Free tick data, resampled. One request per hour; capped at `dukascopy_max_days` (default 45). |
| `frankfurter` | 1d, 1w | ECB reference closes only; OHLC is synthesised. No metals/indices. |
| `stooq` | 1d, 1w | Sometimes blocked by a JavaScript challenge; kept as a last resort. |

Optional keys:

```powershell
$env:TWELVEDATA_API_KEY = "..."
$env:ALPHAVANTAGE_API_KEY = "..."
```

`MT5` is tried first when the package and terminal are available, so research
uses the same prices as your broker. Symbols with suffixes are supported via
`mt5.symbol_suffix` (for example `.a` or `m`).

Cached candles live in `data_cache/` and are merged incrementally. Use
`--refresh` / `--no-cache` on the backtest command when you want fresh data.

## Strategies

All strategies emit a continuous bias in `[-1, 1]`, an entry event, an ATR-based
stop and a reward/risk target. This makes them reusable by both the backtester
and the live scanner.

- `trend_ma` - EMA fast/slow spread, filtered by a long EMA trend.
- `breakout` - Donchian channel breakout with a trend filter.
- `mean_reversion` - Bollinger band extreme plus RSI exhaustion.
- `composite` - equal-weight vote of the three strategies; needs
  `min_score` agreement.

Tune them under `strategies:` in `config.yaml`. Position size is derived from
`risk.risk_per_trade` and the stop distance, rounded down to `lot_step`.
Cross-pair pip values use the approximate `pip_value_rates` table; update it if
your account currency is not USD or when conversion rates move materially.

### Regime gating

Trend-following signals can be filtered with ADX so they only fire in trending
markets, while mean reversion can be limited to quiet markets:

```yaml
strategies:
  trend_ma:    { adx_period: 14, adx_min: 20 }   # require ADX >= 20
  breakout:    { adx_period: 14, adx_min: 20 }
  mean_reversion: { adx_period: 14, adx_max: 25 } # require ADX <= 25
```

The defaults (`adx_min: 0`, `adx_max: 100`) disable the filter, preserving the
original behaviour. Gating zeroes the bias outside the allowed band, which also
suppresses entry events on those bars.

## Validation and realistic costs

The backtest report now includes a buy-and-hold comparison and, when enabled, a
Monte Carlo distribution of outcomes:

```powershell
fxdesk backtest --symbol EURUSD --timeframe 4h --strategy breakout --monte-carlo 1000
```

`monte_carlo_iterations` in `config.yaml` sets the default; `--monte-carlo`
overrides it. Percentiles, probability of profit and the median worst losing
streak are printed and saved in the summary JSON.

Walk-forward re-optimises parameters on each training window and evaluates them
on the following out-of-sample window, compounding the balance across windows:

```powershell
fxdesk walkforward --symbol EURUSD --timeframe 4h --strategy trend_ma `
  --train-bars 1000 --test-bars 250 --step-bars 250 --objective sharpe

# Custom parameter grid (JSON)
fxdesk walkforward --symbol EURUSD --strategy breakout `
  --grid '{"lookback": [10, 20, 30], "atr_mult": [1.5, 2.0], "rr": [1.5, 2.0]}'
```

Built-in grids exist for every strategy; override them with
`walkforward.param_grid.<strategy>` in `config.yaml`. Outputs include stitched
equity, out-of-sample trades, per-window parameters/returns and a summary JSON.

For more realistic fills, enable the session/volatility cost model. It scales
spread and slippage by UTC session and optionally by ATR:

```yaml
backtest:
  cost_model:
    enabled: true
    session_spread_multipliers: { "0-6": 1.5, "12-16": 0.9, "21-24": 1.3 }
    session_slippage_multipliers: { "22-2": 1.8 }
    volatility_spread_mult: 0.2     # spread += 0.2 * ATR/pip
    volatility_slippage_mult: 0.1
    max_spread_pips: 5.0
    max_slippage_pips: 2.0
```

Leaving the block out (or `enabled: false`) keeps the fixed
`spread_pips`/`slippage_pips` behaviour.

## MT5 setup

1. Install the official package: `pip install MetaTrader5`.
2. Start the MT5 terminal and log in.
3. Leave `mt5.login/password/server` empty to attach to the running terminal,
   or fill them in to let fxdesk start its own session.
4. Set `mt5.symbol_suffix` if your broker uses symbols like `EURUSD.a`.

`fxdesk signals` and `fxdesk paper` will then use live MT5 bid/ask quotes.

The native broker adapter (`fxdesk.brokers.mt5.MT5Broker`) implements the same
interface as the paper and MT4 brokers: account info, symbol metadata, quotes,
market orders with SL/TP, open positions and close-position. You can inspect a
running terminal without placing orders:

```powershell
fxdesk mt5 ping
fxdesk mt5 account
fxdesk mt5 quote --symbol EURUSD
fxdesk mt5 symbol --symbol EURUSD
fxdesk mt5 positions
```

Order placement is intentionally not triggered by the paper runner. Call
`MT5Broker.place_order()` / `.close_position()` from your own code only after
verifying behaviour on a demo account. Configure `mt5.deviation_points`,
`mt5.magic` and `mt5.filling` (`auto`, `fok`, `ioc`, `return`) in `config.yaml`.

## MT4 setup (optional file bridge)

MT4 has no official Python API, so fxdesk uses a small file bridge:

1. Copy `bridge/FxDeskBridge.mq4` to `<terminal_data>/MQL4/Experts/`.
2. Compile it in MetaEditor and attach it to one chart (any symbol).
3. Allow automated trading and enable "Allow DLL imports" is **not** required.
4. Find the terminal data folder (File > Open Data Folder) and set
   `mt4.bridge_dir` in `config.yaml` to:
   `<terminal_data>/MQL4/Files/fxdesk`
5. The EA creates the folder and polls for commands.

The Python client is `fxdesk.brokers.mt4.MT4FileBridgeBroker`. The EA supports
quote, account, symbol, market order, close and positions requests. `fxdesk
signals` and `fxdesk paper` automatically prefer MT5, then the MT4 bridge, then
the REST feed. Run `fxdesk doctor` to see whether the bridge directory is
detected. It is a template: test on a demo account first.

```powershell
fxdesk mt4 ping
fxdesk mt4 account
fxdesk mt4 quote --symbol EURUSD
fxdesk mt4 positions
```

The `mt4` command only reads state. Order placement and closing are available
through `MT4FileBridgeBroker.place_order()` and `.close_position()`, but the
paper runner intentionally keeps using the simulated broker. The MT4 bridge
supplies live quotes; candle history still comes from the MT5/REST data layer,
so use the same symbol mapping on both sides.

## Project layout

```
fxdesk/
  cli.py                 command line
  config.py              YAML + env config
  symbols.py             pip/contract metadata
  indicators.py          pandas/numpy indicators
  risk.py                sizing + validation
  data/                  providers, cache, fallback service
  strategies/            trend, breakout, mean reversion, composite
  signals/               ranked trade plans
  backtest/              engine, costs, metrics, analysis, walk-forward, reports
  brokers/               paper broker, MT5 broker, MT4 bridge client
  live/                  quote feeds, paper runner
bridge/FxDeskBridge.mq4  MT4 expert advisor
tests/                   unittest suite
```

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Risk and limitations

- CFDs and forex are leveraged products. You can lose more than you deposit
  with some brokers. Nothing here is financial advice.
- Backtests use simplified fills. Real spread, slippage, swaps, latency,
  requotes and weekend gaps will differ. Yahoo/Frankfurter data is indicative,
  not your broker's executable price.
- The paper broker fills at the latest quote and does not model margin calls,
  partial fills, order rejection, or broker-specific contract specifications.
- Live auto-execution is intentionally not wired into the paper runner. The MT5
  broker adapter can place real orders if you call it yourself; use the signal
  scanner and paper trader first, and add execution only after you have
  verified behaviour on a demo account.
- Check your broker's API terms and your local regulations before automating.
