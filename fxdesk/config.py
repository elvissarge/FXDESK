"""Configuration loading with environment-variable expansion."""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

from fxdesk.errors import ConfigError

DEFAULTS: dict[str, Any] = {
    "account": {
        "currency": "USD",
        "initial_balance": 10000.0,
    },
    "data": {
        "cache_dir": "data_cache",
        "cache_ttl_hours": 24,
        "max_bars": 20000,
        "providers": [
            "mt5",
            "twelvedata",
            "alphavantage",
            "yahoo",
            "dukascopy",
            "frankfurter",
            "stooq",
        ],
        "provider_order_intraday": [
            "mt5",
            "twelvedata",
            "alphavantage",
            "yahoo",
            "dukascopy",
        ],
        "provider_order_daily": [
            "mt5",
            "yahoo",
            "twelvedata",
            "alphavantage",
            "frankfurter",
            "stooq",
        ],
        "api_keys": {
            "twelvedata": None,
            "alphavantage": None,
        },
        "dukascopy_max_days": 45,
        "dukascopy_workers": 8,
    },
    "mt5": {
        "path": None,
        "login": None,
        "password": None,
        "server": None,
        "symbol_suffix": "",
        "timeout_ms": 60000,
        "deviation_points": 20,
        "magic": 20260101,
        "filling": "auto",
    },
    "mt4": {
        "bridge_dir": "bridge/runtime",
        "timeout_seconds": 10.0,
        "symbol_suffix": "",
    },
    "pip_value_rates": {
        "USD": 1.0,
        "EUR": 1.08,
        "GBP": 1.27,
        "JPY": 0.0067,
        "CHF": 1.12,
        "CAD": 0.74,
        "AUD": 0.66,
        "NZD": 0.61,
    },
    "risk": {
        "risk_per_trade": 0.01,
        "max_open_positions": 3,
        "min_risk_reward": 1.5,
        "max_spread_pips": 2.0,
        "max_daily_loss_pct": 3.0,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "max_lot": 50.0,
    },
    "backtest": {
        "initial_balance": 10000.0,
        "spread_pips": 1.0,
        "commission_per_lot": 7.0,
        "slippage_pips": 0.2,
        "swap_pips_per_day": 0.0,
        "allow_short": True,
        "one_position_per_symbol": True,
        "warmup_bars": 250,
        "close_at_end": True,
        "monte_carlo_iterations": 0,
        "cost_model": {},
    },
    "walkforward": {
        "train_bars": 1000,
        "test_bars": 250,
        "step_bars": 250,
        "min_train_trades": 3,
        "objective": "sharpe",
        "max_combinations": 250,
        "param_grid": {},
    },
    "paper": {
        "poll_seconds": 15,
        "slippage_pips": 0.2,
        "spread_pips": 1.0,
        "quote_timeframe": "1m",
        "commission_per_lot": 0.0,
        "initial_balance": 10000.0,
        "state_file": "paper_state.json",
    },
    "signals": {
        "lookback_bars": 500,
        "max_plans": 10,
        "synthetic_spread_pips": 1.0,
    },
    "strategies": {
        "trend_ma": {
            "fast": 20,
            "slow": 50,
            "trend": 200,
            "atr_period": 14,
            "atr_mult": 2.0,
            "rr": 2.0,
            "adx_period": 14,
            "adx_min": 0.0,
        },
        "breakout": {
            "lookback": 20,
            "trend": 200,
            "atr_period": 14,
            "atr_mult": 2.0,
            "rr": 2.0,
            "adx_period": 14,
            "adx_min": 0.0,
        },
        "mean_reversion": {
            "bb_period": 20,
            "bb_std": 2.0,
            "rsi_period": 14,
            "rsi_low": 30,
            "rsi_high": 70,
            "atr_period": 14,
            "atr_mult": 1.5,
            "rr": 1.5,
            "adx_period": 14,
            "adx_max": 100.0,
        },
        "composite": {
            "min_score": 0.6,
            "strategies": ["trend_ma", "breakout", "mean_reversion"],
        },
    },
}

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            env = os.environ.get(name)
            if env is None or env == "":
                return default if default is not None else ""
            return env

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {key: _expand_env(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def find_config(path: str | Path | None = None) -> Path | None:
    if path:
        return Path(path)
    for candidate in (Path("config.yaml"), Path("config.yml"), Path("fxdesk.yaml")):
        if candidate.exists():
            return candidate
    return None


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = find_config(path)
    user_config: dict[str, Any] = {}

    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(f"config file not found: {config_path}")
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ConfigError(f"config root must be a mapping: {config_path}")
        user_config = raw

    cfg = deep_merge(DEFAULTS, _expand_env(user_config))

    keys = cfg.setdefault("data", {}).setdefault("api_keys", {})
    if not keys.get("twelvedata"):
        keys["twelvedata"] = os.environ.get("TWELVEDATA_API_KEY")
    if not keys.get("alphavantage"):
        keys["alphavantage"] = os.environ.get("ALPHAVANTAGE_API_KEY")

    return cfg


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
