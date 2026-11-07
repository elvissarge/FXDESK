"""Pandas/numpy technical indicators (no TA-Lib dependency)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    return out


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    previous_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def bollinger(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    mid = sma(series, period)
    std = series.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame(
        {
            "mid": mid,
            "upper": mid + std * num_std,
            "lower": mid - std * num_std,
            "std": std,
        }
    )


def donchian(
    high: pd.Series, low: pd.Series, period: int = 20
) -> pd.DataFrame:
    upper = high.rolling(period, min_periods=period).max()
    lower = low.rolling(period, min_periods=period).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0})


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    line = fast_ema - slow_ema
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame(
        {"macd": line, "signal": signal_line, "histogram": line - signal_line}
    )


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    lowest = low.rolling(k_period, min_periods=k_period).min()
    highest = high.rolling(k_period, min_periods=k_period).max()
    denominator = (highest - lowest).replace(0.0, np.nan)
    k = 100.0 * (close - lowest) / denominator
    d = k.rolling(d_period, min_periods=d_period).mean()
    return pd.DataFrame({"k": k, "d": d})


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.DataFrame:
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )

    tr = true_range(high, low, close)
    smoothed_tr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    plus_di = 100.0 * plus_dm.ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean() / smoothed_tr.replace(0.0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean() / smoothed_tr.replace(0.0, np.nan)

    denominator = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denominator
    adx_line = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    return pd.DataFrame(
        {"adx": adx_line, "plus_di": plus_di, "minus_di": minus_di}
    )


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    return series.pct_change(periods=period) * 100.0


def rolling_slope(series: pd.Series, period: int = 20) -> pd.Series:
    x = np.arange(period, dtype=float)
    x_centered = x - x.mean()
    denominator = (x_centered**2).sum()

    def _slope(values: np.ndarray) -> float:
        if np.isnan(values).any():
            return np.nan
        return float((x_centered * (values - values.mean())).sum() / denominator)

    return series.rolling(period, min_periods=period).apply(_slope, raw=True)
