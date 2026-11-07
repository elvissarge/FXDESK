"""Service layer shared by the web API (and reusable from other frontends)."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from fxdesk.backtest.analysis import analyze_result
from fxdesk.backtest.engine import Backtester
from fxdesk.backtest.report import save_outputs
from fxdesk.backtest.walkforward import WalkForward, save_walkforward_outputs
from fxdesk.data import DataService
from fxdesk.errors import DataError
from fxdesk.live.feed import build_feed
from fxdesk.signals.engine import SignalEngine
from fxdesk.strategies.registry import build_strategy
from fxdesk.timeframes import normalize_timeframe
from fxdesk.web.serialize import equity_points, frame_records, jsonable, trades_records

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


def default_start(timeframe: str) -> str | None:
    tf = normalize_timeframe(timeframe)
    days = _DEFAULT_LOOKBACK_DAYS.get(tf)
    if days is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def _symbols(value: Any, default: str = "EURUSD") -> list[str]:
    items = _as_list(value)
    return [item.upper() for item in items] or [default]


def _strategies(value: Any, default: str = "composite") -> list[str]:
    return _as_list(value) or [default]


def _apply_overrides(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    backtest = cfg.setdefault("backtest", {})
    risk = cfg.setdefault("risk", {})

    for source, target in (
        ("balance", "initial_balance"),
        ("spread", "spread_pips"),
        ("commission", "commission_per_lot"),
        ("slippage", "slippage_pips"),
    ):
        if params.get(source) is not None:
            backtest[target] = float(params[source])
    if params.get("risk") is not None:
        risk["risk_per_trade"] = float(params["risk"])
    return cfg


def _fetch(
    service: DataService,
    symbol: str,
    timeframe: str,
    params: dict[str, Any],
    start: str | None,
):
    return service.fetch(
        symbol,
        timeframe,
        start=start,
        end=params.get("end"),
        provider=params.get("provider"),
        refresh=bool(params.get("refresh", False)),
        use_cache=bool(params.get("use_cache", True)),
    )


def run_backtest(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    cfg = _apply_overrides(config, params)
    symbol = _symbols(params.get("symbol"))[0]
    timeframe = normalize_timeframe(str(params.get("timeframe") or "1h"))
    strategy_name = str(params.get("strategy") or "composite")

    service = DataService(cfg)
    start = params.get("start") or default_start(timeframe)
    frame = _fetch(service, symbol, timeframe, params, start)

    strategy = build_strategy(strategy_name, cfg)
    needed = strategy.required_bars() + 2
    if len(frame) < needed:
        raise DataError(
            f"{symbol} {timeframe}: only {len(frame)} bars, "
            f"strategy needs {needed}; widen start or use a larger timeframe"
        )

    backtest_cfg = cfg.setdefault("backtest", {})
    backtest_cfg["warmup_bars"] = max(
        int(backtest_cfg.get("warmup_bars", 0)), strategy.required_bars()
    )

    strategy_frame = strategy.generate_frame(frame)
    result = Backtester(cfg).run(
        symbol, timeframe, frame, strategy_frame, strategy_name=strategy_name
    )

    iterations = params.get("monte_carlo")
    if iterations is None:
        iterations = int(backtest_cfg.get("monte_carlo_iterations", 0) or 0)
    result.analysis = analyze_result(
        result,
        frame,
        monte_carlo_iterations=int(iterations or 0),
        seed=int(params.get("seed", 0) or 0),
    )

    payload: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": strategy_name,
        "bars": int(len(frame)),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "summary": result.summary(),
        "metrics": jsonable(result.metrics),
        "analysis": jsonable(result.analysis),
        "equity": equity_points(result.equity),
        "trades": trades_records(result.trades),
        "final_balance": float(result.final_balance),
        "initial_balance": float(result.initial_balance),
    }

    if params.get("save"):
        paths = save_outputs(
            result,
            params.get("output_dir") or "reports",
            plot=bool(params.get("plot", False)),
        )
        payload["paths"] = {key: str(path) for key, path in paths.items()}

    return jsonable(payload)


def run_walkforward(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    cfg = _apply_overrides(config, params)
    symbol = _symbols(params.get("symbol"))[0]
    timeframe = normalize_timeframe(str(params.get("timeframe") or "1h"))
    strategy_name = str(params.get("strategy") or "trend_ma")

    service = DataService(cfg)
    frame = _fetch(service, symbol, timeframe, params, params.get("start"))

    walkforward = WalkForward(
        cfg,
        strategy_name,
        param_grid=params.get("grid"),
        train_bars=params.get("train_bars"),
        test_bars=params.get("test_bars"),
        step_bars=params.get("step_bars"),
        objective=params.get("objective"),
        min_train_trades=params.get("min_train_trades"),
        max_combinations=params.get("max_combinations"),
        monte_carlo_iterations=int(params.get("monte_carlo") or 0),
        seed=int(params.get("seed", 0) or 0),
    )
    result = walkforward.run(symbol, timeframe, frame)

    payload: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "strategy": strategy_name,
        "bars": int(len(frame)),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "summary": result.summary(),
        "metrics": jsonable(result.metrics),
        "analysis": jsonable(result.analysis),
        "windows": jsonable(result.windows),
        "equity": equity_points(result.equity),
        "trades": trades_records(result.trades),
        "final_balance": float(result.final_balance),
        "initial_balance": float(result.initial_balance),
    }

    if params.get("save"):
        paths = save_walkforward_outputs(
            result,
            params.get("output_dir") or "reports",
            plot=bool(params.get("plot", False)),
        )
        payload["paths"] = {key: str(path) for key, path in paths.items()}

    return jsonable(payload)


def run_signals(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    symbols = _symbols(params.get("symbols") or params.get("symbol"))
    strategies = _strategies(params.get("strategies") or params.get("strategy"))
    timeframe = normalize_timeframe(str(params.get("timeframe") or "1h"))

    service = DataService(cfg)
    engine = SignalEngine(cfg, data=service)

    quotes = None
    feed = None
    if params.get("live"):
        try:
            feed = build_feed(cfg, data=service)
            quotes = {symbol: feed.get_quote(symbol) for symbol in symbols}
        except Exception:
            quotes = None
            if feed is not None:
                feed.close()
                feed = None

    try:
        plans = engine.scan(
            symbols,
            timeframe,
            strategies,
            quotes=quotes,
            equity=params.get("equity"),
            allow_continuation=bool(params.get("allow_continuation", True)),
            max_plans=params.get("max_plans"),
        )
    finally:
        if feed is not None:
            feed.close()

    return {
        "symbols": symbols,
        "timeframe": timeframe,
        "strategies": strategies,
        "live": bool(params.get("live", False)),
        "count": len(plans),
        "plans": [jsonable(plan.to_dict()) for plan in plans],
    }


def run_data_fetch(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    symbol = _symbols(params.get("symbol"))[0]
    timeframe = normalize_timeframe(str(params.get("timeframe") or "1d"))
    service = DataService(config)
    frame = _fetch(
        service,
        symbol,
        timeframe,
        params,
        params.get("start") or default_start(timeframe),
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": int(len(frame)),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "candles": frame_records(frame, limit=int(params.get("limit", 500))),
    }
