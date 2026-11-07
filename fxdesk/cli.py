"""Command-line interface for fxdesk."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from fxdesk.backtest.analysis import analyze_result
from fxdesk.backtest.engine import Backtester
from fxdesk.backtest.report import save_outputs
from fxdesk.backtest.walkforward import WalkForward, save_walkforward_outputs
from fxdesk.brokers.mt4 import MT4FileBridgeBroker
from fxdesk.brokers.mt5 import MT5Broker
from fxdesk.brokers.paper import PaperBroker
from fxdesk.config import load_config
from fxdesk.data import DataService
from fxdesk.data.providers import provider_names
from fxdesk.errors import ConfigError, FxDeskError
from fxdesk.live.feed import build_feed
from fxdesk.live.runner import PaperRunner
from fxdesk.signals.engine import SignalEngine, format_plans
from fxdesk.strategies.registry import build_strategy, strategy_names
from fxdesk.symbols import KNOWN, known_symbols, spec_for
from fxdesk.timeframes import normalize_timeframe, supported_timeframes
from fxdesk.utils.logging import setup_logging

_DEFAULT_LOOKBACK_DAYS = {
    "1m": 3,
    "5m": 14,
    "15m": 21,
    "30m": 30,
    "1h": 45,
    "2h": 60,
    "4h": 90,
    "8h": 180,
    "1d": 3650,
    "1w": 7300,
}


def _hoist_common(argv: list[str] | None) -> list[str]:
    """Allow --config/-v before or after the subcommand."""
    if argv is None:
        argv = sys.argv[1:]
    common: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--config" and index + 1 < len(argv):
            common.extend([arg, argv[index + 1]])
            index += 2
            continue
        if arg.startswith("--config=") or arg in ("-v", "--verbose"):
            common.append(arg)
            index += 1
            continue
        rest.append(arg)
        index += 1
    return common + rest


def parse_symbols(value: str) -> list[str]:
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def parse_strategies(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def default_start(timeframe: str) -> str | None:
    tf = normalize_timeframe(timeframe)
    days = _DEFAULT_LOOKBACK_DAYS.get(tf)
    if days is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def apply_backtest_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    bt = cfg.setdefault("backtest", {})
    risk = cfg.setdefault("risk", {})

    if args.balance is not None:
        bt["initial_balance"] = float(args.balance)
    if args.spread is not None:
        bt["spread_pips"] = float(args.spread)
    if args.commission is not None:
        bt["commission_per_lot"] = float(args.commission)
    if args.slippage is not None:
        bt["slippage_pips"] = float(args.slippage)
    if args.risk is not None:
        risk["risk_per_trade"] = float(args.risk)
    return cfg


# --------------------------------------------------------------------------- commands
def cmd_doctor(args: argparse.Namespace, config: dict[str, Any]) -> int:
    print("fxdesk doctor")
    print("-" * 50)
    print(f"python        {sys.version.split()[0]}")
    print(f"strategies    {', '.join(strategy_names())}")
    print(f"timeframes    {', '.join(supported_timeframes())}")
    print(f"symbols       {len(known_symbols())} built in")

    mt4 = MT4FileBridgeBroker(config)
    print(
        f"mt4 bridge    "
        f"{'available' if mt4.available() else 'not configured'} "
        f"({mt4.bridge_dir})"
    )

    mt5_broker = MT5Broker(config)
    print(
        f"mt5 broker    "
        f"{'available' if mt5_broker.available() else 'unavailable (package not installed)'}"
    )

    service = DataService(config)
    status = service.provider_status()
    keys = config.get("data", {}).get("api_keys", {})

    print("\nproviders")
    for name in provider_names():
        available = status.get(name, False)
        note = ""
        if name == "twelvedata":
            note = " (key set)" if keys.get("twelvedata") else " (no key)"
        if name == "alphavantage":
            note = " (key set)" if keys.get("alphavantage") else " (no key)"
        print(f"  {name:<14} {'available' if available else 'unavailable'}{note}")

    if args.online:
        print("\nonline test: EURUSD 1d")
        try:
            frame = service.fetch("EURUSD", "1d", refresh=True)
            print(
                f"  ok: {len(frame)} bars, "
                f"{frame.index[0]:%Y-%m-%d} .. {frame.index[-1]:%Y-%m-%d}"
            )
        except Exception as exc:
            print(f"  failed: {exc}")
            return 1
    return 0


def cmd_providers(args: argparse.Namespace, config: dict[str, Any]) -> int:
    service = DataService(config)
    status = service.provider_status()
    keys = config.get("data", {}).get("api_keys", {})
    for name in provider_names():
        key_note = ""
        if name in ("twelvedata", "alphavantage"):
            key_note = "key=yes" if keys.get(name) else "key=no"
        print(
            f"{name:<14} {'available' if status.get(name) else 'unavailable':<12} {key_note}"
        )
    return 0


def cmd_strategies(args: argparse.Namespace, config: dict[str, Any]) -> int:
    strategies_cfg = config.get("strategies", {})
    for name in strategy_names():
        params = strategies_cfg.get(name, {})
        print(f"{name}:")
        print(json.dumps(params, indent=2))
    return 0


def cmd_symbols(args: argparse.Namespace, config: dict[str, Any]) -> int:
    print(f"{'SYMBOL':<10}{'BASE':<6}{'QUOTE':<6}{'DIGITS':>7}{'PIP':>10}{'CONTRACT':>12}  KIND")
    for code in known_symbols():
        spec = KNOWN[code]
        print(
            f"{spec.symbol:<10}{spec.base:<6}{spec.quote:<6}{spec.digits:>7}"
            f"{spec.pip_size:>10.5f}{spec.contract_size:>12.0f}  {spec.kind}"
        )
    return 0


def cmd_data_fetch(args: argparse.Namespace, config: dict[str, Any]) -> int:
    service = DataService(config)
    symbol = args.symbol.upper()
    try:
        frame = service.fetch(
            symbol,
            args.timeframe,
            start=args.start,
            end=args.end,
            provider=args.provider,
            refresh=True,
            use_cache=not args.no_cache,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"{symbol} {normalize_timeframe(args.timeframe)}: {len(frame)} bars "
        f"{frame.index[0]} .. {frame.index[-1]}"
    )
    print(frame.tail(10).to_string())

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index_label="time")
        print(f"saved {output}")
    return 0


def cmd_backtest(args: argparse.Namespace, config: dict[str, Any]) -> int:
    symbols = parse_symbols(args.symbol)
    service = DataService(config)
    start = args.start or default_start(args.timeframe)
    exit_code = 0

    for symbol in symbols:
        try:
            frame = service.fetch(
                symbol,
                args.timeframe,
                start=start,
                end=args.end,
                provider=args.provider,
                refresh=args.refresh,
                use_cache=not args.no_cache,
            )
        except Exception as exc:
            print(f"{symbol}: data error: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        run_config = apply_backtest_overrides(config, args)
        strategy = build_strategy(args.strategy, run_config)
        needed = strategy.required_bars() + 2
        if len(frame) < needed:
            print(
                f"{symbol}: only {len(frame)} bars, strategy needs {needed}; "
                f"widen --start or use a larger timeframe",
                file=sys.stderr,
            )
            exit_code = 1
            continue

        run_config.setdefault("backtest", {})["warmup_bars"] = max(
            int(run_config.get("backtest", {}).get("warmup_bars", 0)),
            strategy.required_bars(),
        )

        strategy_frame = strategy.generate_frame(frame)
        result = Backtester(run_config).run(
            symbol,
            normalize_timeframe(args.timeframe),
            frame,
            strategy_frame,
            strategy_name=args.strategy,
        )

        mc_iterations = (
            args.monte_carlo
            if args.monte_carlo is not None
            else int(run_config.get("backtest", {}).get("monte_carlo_iterations", 0) or 0)
        )
        result.analysis = analyze_result(
            result,
            frame,
            monte_carlo_iterations=mc_iterations,
            seed=int(run_config.get("backtest", {}).get("monte_carlo_seed", 0) or 0),
        )

        print(result.summary())
        paths = save_outputs(result, args.output_dir, plot=args.plot)
        print("saved: " + ", ".join(str(path) for path in paths.values()))
        print()

    return exit_code


def cmd_walkforward(args: argparse.Namespace, config: dict[str, Any]) -> int:
    symbol = args.symbol.upper()
    service = DataService(config)
    start = args.start or default_start(args.timeframe)

    try:
        frame = service.fetch(
            symbol,
            args.timeframe,
            start=start,
            end=args.end,
            provider=args.provider,
            refresh=args.refresh,
            use_cache=not args.no_cache,
        )
    except Exception as exc:
        print(f"{symbol}: data error: {exc}", file=sys.stderr)
        return 1

    grid = None
    if args.grid:
        try:
            grid = json.loads(args.grid)
        except json.JSONDecodeError as exc:
            print(f"invalid --grid JSON: {exc}", file=sys.stderr)
            return 2

    walkforward = WalkForward(
        config,
        args.strategy,
        param_grid=grid,
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        step_bars=args.step_bars,
        objective=args.objective,
        min_train_trades=args.min_train_trades,
        max_combinations=args.max_combinations,
        monte_carlo_iterations=args.monte_carlo or 0,
    )
    result = walkforward.run(symbol, normalize_timeframe(args.timeframe), frame)

    print(result.summary())
    paths = save_walkforward_outputs(result, args.output_dir, plot=args.plot)
    print("saved: " + ", ".join(str(path) for path in paths.values()))
    return 0


def cmd_signals(args: argparse.Namespace, config: dict[str, Any]) -> int:
    symbols = parse_symbols(args.symbol)
    strategies = parse_strategies(args.strategy)
    service = DataService(config)
    engine = SignalEngine(config, data=service)

    quotes = {}
    feed = None
    if not args.no_live:
        try:
            feed = build_feed(config, data=service)
            for symbol in symbols:
                try:
                    quotes[symbol] = feed.get_quote(symbol)
                except Exception as exc:
                    print(f"warning: no live quote for {symbol}: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"warning: live feed unavailable: {exc}", file=sys.stderr)

    max_plans = (
        args.max_plans
        if args.max_plans is not None
        else config.get("signals", {}).get("max_plans")
    )

    try:
        plans = engine.scan(
            symbols,
            args.timeframe,
            strategies,
            quotes=quotes,
            equity=args.equity,
            allow_continuation=not args.events_only,
            max_plans=max_plans,
        )
    finally:
        if feed is not None:
            feed.close()

    if args.json:
        print(json.dumps([plan.to_dict() for plan in plans], indent=2, default=str))
    else:
        print(format_plans(plans))
    return 0


def cmd_mt4(args: argparse.Namespace, config: dict[str, Any]) -> int:
    broker = MT4FileBridgeBroker(config)
    command = args.mt4_command

    if command == "ping":
        broker.connect()
        print("pong")
        return 0

    if not broker.available():
        print(
            f"MT4 bridge directory does not exist: {broker.bridge_dir}",
            file=sys.stderr,
        )
        return 1

    if command == "account":
        payload: Any = broker.account_info().to_dict()
    elif command == "quote":
        quote = broker.quote(args.symbol)
        payload = {
            "symbol": quote.symbol,
            "bid": quote.bid,
            "ask": quote.ask,
            "mid": quote.mid,
            "spread": quote.spread,
            "time": quote.time.isoformat() if quote.time else None,
        }
    elif command == "positions":
        payload = [position.to_dict() for position in broker.positions()]
    elif command == "symbol":
        info = broker.symbol_info(args.symbol)
        payload = {
            "symbol": info.symbol,
            "digits": info.digits,
            "pip_size": info.pip_size,
            "contract_size": info.contract_size,
            "min_lot": info.min_lot,
            "lot_step": info.lot_step,
            "max_lot": info.max_lot,
            "spread": info.spread,
        }
    else:  # pragma: no cover - argparse enforces the choices
        raise FxDeskError(f"unknown mt4 command {command!r}")

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
    elif isinstance(payload, list):
        if not payload:
            print("no open positions")
        else:
            for position in payload:
                print(
                    f"#{position['ticket']} {position['symbol']} {position['side']} "
                    f"{position['volume']} lots @ {position['entry']} "
                    f"P/L {position['profit']}"
                )
    else:
        for key, value in payload.items():
            print(f"{key:<14} {value}")
    return 0


def cmd_mt5(args: argparse.Namespace, config: dict[str, Any]) -> int:
    broker = MT5Broker(config)
    if not broker.available():
        print(
            "MetaTrader5 package is not installed (pip install MetaTrader5)",
            file=sys.stderr,
        )
        return 1

    command = args.mt5_command
    try:
        if command == "ping":
            broker.connect()
            print("pong")
            return 0

        if command == "account":
            payload: Any = broker.account_info().to_dict()
        elif command == "quote":
            quote = broker.quote(args.symbol)
            payload = {
                "symbol": quote.symbol,
                "bid": quote.bid,
                "ask": quote.ask,
                "mid": quote.mid,
                "spread": quote.spread,
                "time": quote.time.isoformat() if quote.time else None,
            }
        elif command == "positions":
            payload = [position.to_dict() for position in broker.positions()]
        elif command == "symbol":
            info = broker.symbol_info(args.symbol)
            payload = {
                "symbol": info.symbol,
                "digits": info.digits,
                "pip_size": info.pip_size,
                "contract_size": info.contract_size,
                "min_lot": info.min_lot,
                "lot_step": info.lot_step,
                "max_lot": info.max_lot,
                "spread": info.spread,
            }
        else:  # pragma: no cover - argparse enforces the choices
            raise FxDeskError(f"unknown mt5 command {command!r}")
    finally:
        broker.disconnect()

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
    elif isinstance(payload, list):
        if not payload:
            print("no open positions")
        else:
            for position in payload:
                print(
                    f"#{position['ticket']} {position['symbol']} {position['side']} "
                    f"{position['volume']} lots @ {position['entry']} "
                    f"P/L {position['profit']}"
                )
    else:
        for key, value in payload.items():
            print(f"{key:<14} {value}")
    return 0


def cmd_paper(args: argparse.Namespace, config: dict[str, Any]) -> int:
    symbols = parse_symbols(args.symbol)
    strategies = parse_strategies(args.strategy)

    state_file = args.state_file or config.get("paper", {}).get(
        "state_file", "paper_state.json"
    )
    if args.reset:
        path = Path(state_file)
        if path.exists():
            path.unlink()
            print(f"removed {path}")

    broker = PaperBroker(config, initial_balance=args.balance)
    runner = PaperRunner(
        config,
        broker=broker,
        state_file=state_file,
    )
    runner.run(
        symbols,
        args.timeframe,
        strategies,
        poll_seconds=args.poll,
        once=args.once,
        allow_continuation=args.continuation,
    )
    return 0


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fxdesk",
        description="Forex/CFD research, backtesting, signals and paper trading.",
    )
    parser.add_argument("--config", default=None, help="path to config YAML")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check dependencies and data providers")
    doctor.add_argument("--online", action="store_true", help="test a real download")
    doctor.set_defaults(func=cmd_doctor)

    providers = sub.add_parser("providers", help="list data providers and status")
    providers.set_defaults(func=cmd_providers)

    strategies = sub.add_parser("strategies", help="list strategies and parameters")
    strategies.set_defaults(func=cmd_strategies)

    symbols = sub.add_parser("symbols", help="list built-in symbol metadata")
    symbols.set_defaults(func=cmd_symbols)

    data = sub.add_parser("data", help="market data commands")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    fetch = data_sub.add_parser("fetch", help="download candles")
    fetch.add_argument("--symbol", default="EURUSD")
    fetch.add_argument("--timeframe", default="1d")
    fetch.add_argument("--start", default=None)
    fetch.add_argument("--end", default=None)
    fetch.add_argument("--provider", default=None)
    fetch.add_argument("--output", default=None, help="write CSV to this path")
    fetch.add_argument("--no-cache", action="store_true")
    fetch.set_defaults(func=cmd_data_fetch)

    backtest = sub.add_parser("backtest", help="run a historical backtest")
    backtest.add_argument("--symbol", default="EURUSD", help="comma separated")
    backtest.add_argument("--timeframe", default="1h")
    backtest.add_argument("--strategy", default="composite")
    backtest.add_argument("--start", default=None)
    backtest.add_argument("--end", default=None)
    backtest.add_argument("--provider", default=None)
    backtest.add_argument("--balance", type=float, default=None)
    backtest.add_argument("--spread", type=float, default=None, help="pips")
    backtest.add_argument("--commission", type=float, default=None, help="per lot")
    backtest.add_argument("--slippage", type=float, default=None, help="pips")
    backtest.add_argument("--risk", type=float, default=None, help="fraction, e.g. 0.01")
    backtest.add_argument(
        "--monte-carlo",
        type=int,
        default=None,
        help="bootstrap runs for outcome distribution (0 disables)",
    )
    backtest.add_argument("--plot", action="store_true")
    backtest.add_argument("--output-dir", default="reports")
    backtest.add_argument("--no-cache", action="store_true")
    backtest.add_argument("--refresh", action="store_true")
    backtest.set_defaults(func=cmd_backtest)

    walkforward = sub.add_parser(
        "walkforward",
        help="rolling train/test validation with parameter selection",
    )
    walkforward.add_argument("--symbol", default="EURUSD")
    walkforward.add_argument("--timeframe", default="1h")
    walkforward.add_argument("--strategy", default="trend_ma")
    walkforward.add_argument("--start", default=None)
    walkforward.add_argument("--end", default=None)
    walkforward.add_argument("--provider", default=None)
    walkforward.add_argument("--train-bars", type=int, default=None)
    walkforward.add_argument("--test-bars", type=int, default=None)
    walkforward.add_argument("--step-bars", type=int, default=None)
    walkforward.add_argument("--min-train-trades", type=int, default=None)
    walkforward.add_argument("--max-combinations", type=int, default=None)
    walkforward.add_argument(
        "--objective",
        default=None,
        choices=["sharpe", "sortino", "expectancy", "profit_factor", "total_return", "calmar"],
    )
    walkforward.add_argument(
        "--grid",
        default=None,
        help='JSON parameter grid, e.g. \'{"fast": [10, 20], "slow": [50]}\'',
    )
    walkforward.add_argument("--monte-carlo", type=int, default=None)
    walkforward.add_argument("--plot", action="store_true")
    walkforward.add_argument("--output-dir", default="reports")
    walkforward.add_argument("--no-cache", action="store_true")
    walkforward.add_argument("--refresh", action="store_true")
    walkforward.set_defaults(func=cmd_walkforward)

    signals = sub.add_parser("signals", help="scan for the best trade plans")
    signals.add_argument("--symbol", default="EURUSD,GBPUSD,USDJPY")
    signals.add_argument("--timeframe", default="1h")
    signals.add_argument("--strategy", default="composite")
    signals.add_argument("--equity", type=float, default=None)
    signals.add_argument("--max-plans", type=int, default=None)
    signals.add_argument(
        "--events-only",
        action="store_true",
        help="only fresh entry events, not existing bias",
    )
    signals.add_argument(
        "--no-live",
        action="store_true",
        help="use last candle instead of a live quote feed",
    )
    signals.add_argument("--json", action="store_true")
    signals.set_defaults(func=cmd_signals)

    mt4 = sub.add_parser("mt4", help="query the MetaTrader 4 file bridge")
    mt4_sub = mt4.add_subparsers(dest="mt4_command", required=True)
    mt4_ping = mt4_sub.add_parser("ping", help="check that the EA responds")
    mt4_ping.set_defaults(func=cmd_mt4)
    mt4_account = mt4_sub.add_parser("account", help="show account information")
    mt4_account.add_argument("--json", action="store_true")
    mt4_account.set_defaults(func=cmd_mt4)
    mt4_quote = mt4_sub.add_parser("quote", help="show a live bid/ask quote")
    mt4_quote.add_argument("--symbol", default="EURUSD")
    mt4_quote.add_argument("--json", action="store_true")
    mt4_quote.set_defaults(func=cmd_mt4)
    mt4_symbol = mt4_sub.add_parser("symbol", help="show broker symbol metadata")
    mt4_symbol.add_argument("--symbol", default="EURUSD")
    mt4_symbol.add_argument("--json", action="store_true")
    mt4_symbol.set_defaults(func=cmd_mt4)
    mt4_positions = mt4_sub.add_parser("positions", help="list open positions")
    mt4_positions.add_argument("--json", action="store_true")
    mt4_positions.set_defaults(func=cmd_mt4)

    mt5 = sub.add_parser("mt5", help="query the native MetaTrader 5 broker")
    mt5_sub = mt5.add_subparsers(dest="mt5_command", required=True)
    mt5_ping = mt5_sub.add_parser("ping", help="check that the terminal responds")
    mt5_ping.set_defaults(func=cmd_mt5)
    mt5_account = mt5_sub.add_parser("account", help="show account information")
    mt5_account.add_argument("--json", action="store_true")
    mt5_account.set_defaults(func=cmd_mt5)
    mt5_quote = mt5_sub.add_parser("quote", help="show a live bid/ask quote")
    mt5_quote.add_argument("--symbol", default="EURUSD")
    mt5_quote.add_argument("--json", action="store_true")
    mt5_quote.set_defaults(func=cmd_mt5)
    mt5_symbol = mt5_sub.add_parser("symbol", help="show broker symbol metadata")
    mt5_symbol.add_argument("--symbol", default="EURUSD")
    mt5_symbol.add_argument("--json", action="store_true")
    mt5_symbol.set_defaults(func=cmd_mt5)
    mt5_positions = mt5_sub.add_parser("positions", help="list open positions")
    mt5_positions.add_argument("--json", action="store_true")
    mt5_positions.set_defaults(func=cmd_mt5)

    paper = sub.add_parser("paper", help="run the paper-trading loop")
    paper.add_argument("--symbol", default="EURUSD,GBPUSD,USDJPY")
    paper.add_argument("--timeframe", default="1h")
    paper.add_argument("--strategy", default="composite")
    paper.add_argument("--poll", type=float, default=None, help="seconds between cycles")
    paper.add_argument("--once", action="store_true", help="run a single cycle")
    paper.add_argument(
        "--continuation",
        action="store_true",
        help="enter on existing bias as well as fresh events",
    )
    paper.add_argument("--state-file", default=None)
    paper.add_argument("--reset", action="store_true")
    paper.add_argument("--balance", type=float, default=None)
    paper.set_defaults(func=cmd_paper)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_hoist_common(argv))
    setup_logging(args.verbose)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    try:
        return int(args.func(args, config))
    except FxDeskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
