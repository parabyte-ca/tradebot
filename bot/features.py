"""Feature engineering for the LightGBM signal model.

compute_features(symbol, df) returns a single-row DataFrame with all
features needed for prediction. The same function is used for both
training (called for each historical row) and live inference.

Feature groups
--------------
Price/volume : RSI(14), MACD(12/26/9), Bollinger Band width, ATR(14),
               volume z-score, price vs 20/50/200-day SMA ratios.
Momentum     : 1-week, 1-month, 3-month log returns.
Mean reversion: distance from 20-day mean normalised by ATR.
Sentiment    : 7-day rolling FinBERT compound score.
Regime       : VIX estimate level, SPY-above-200-SMA binary flag.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from data.finnhub_client import FinnhubClient

logger = logging.getLogger(__name__)

_finnhub = None  # module-level singleton — FinBERT loads once


def _get_finnhub() -> FinnhubClient:
    global _finnhub
    if _finnhub is None:
        _finnhub = FinnhubClient()
    return _finnhub


# ---------------------------------------------------------------------------
# Individual indicator helpers
# ---------------------------------------------------------------------------

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _bb_width(close: pd.Series, period: int = 20) -> pd.Series:
    """Normalised Bollinger Band width = (upper - lower) / middle."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return (2 * std) / mid.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Main feature computation
# ---------------------------------------------------------------------------

def compute_features(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """Compute all model features for *symbol* from its OHLCV DataFrame.

    Args:
        symbol: Ticker symbol (used for sentiment lookup).
        df:     DataFrame with columns [open, high, low, close, volume],
                sorted ascending by date, covering at least 210 rows.

    Returns:
        Single-row DataFrame with all feature columns for the last bar.
        Returns an empty DataFrame with a warning if history is insufficient.
    """
    if len(df) < 210:
        logger.warning("Insufficient history for %s (%d rows, need 210)", symbol, len(df))
        return pd.DataFrame()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    feat: dict = {}

    # --- RSI ---
    rsi = _rsi(close)
    feat["rsi_14"] = rsi.iloc[-1]

    # --- MACD ---
    macd_line, signal_line, macd_hist = _macd(close)
    feat["macd"] = macd_line.iloc[-1]
    feat["macd_signal"] = signal_line.iloc[-1]
    feat["macd_hist"] = macd_hist.iloc[-1]

    # --- Bollinger Band width ---
    feat["bb_width_20"] = _bb_width(close).iloc[-1]

    # --- ATR ---
    atr = _atr(high, low, close)
    atr_val = atr.iloc[-1]
    feat["atr_14"] = atr_val

    # --- Volume z-score (20-day) ---
    vol_mean = volume.rolling(20).mean().iloc[-1]
    vol_std = volume.rolling(20).std().iloc[-1]
    feat["volume_zscore"] = (volume.iloc[-1] - vol_mean) / (vol_std or 1.0)

    # --- Price vs SMA ratios ---
    for window in (20, 50, 200):
        sma = close.rolling(window).mean().iloc[-1]
        feat[f"price_vs_sma{window}"] = close.iloc[-1] / sma - 1.0 if sma else 0.0

    # --- Momentum: log returns ---
    for days, label in [(5, "1w"), (21, "1m"), (63, "3m")]:
        if len(close) > days:
            feat[f"ret_{label}"] = float(np.log(close.iloc[-1] / close.iloc[-1 - days]))
        else:
            feat[f"ret_{label}"] = 0.0

    # --- Mean reversion: distance from 20-day mean, normalised by ATR ---
    mean_20 = close.rolling(20).mean().iloc[-1]
    feat["mean_rev_atr"] = (close.iloc[-1] - mean_20) / (atr_val or 1.0)

    # --- Sentiment: 7-day rolling FinBERT score ---
    try:
        reference_date = df.index[-1].date().isoformat() if hasattr(df.index[-1], "date") else str(df.index[-1])[:10]
        feat["sentiment_7d"] = _get_finnhub().get_sentiment(symbol, lookback_days=7, reference_date=reference_date)
    except Exception as exc:
        logger.warning("Sentiment fetch failed for %s: %s", symbol, exc)
        feat["sentiment_7d"] = 0.0

    # --- Regime features (passed in as env-level constants or fetched lazily) ---
    # These are filled by strategy.py after regime.classify_regime() to avoid
    # redundant API calls when computing features for the full universe.
    feat["vix_level"] = np.nan   # filled by caller
    feat["spy_above_200"] = np.nan  # filled by caller

    return pd.DataFrame([feat])
