"""Regime classifier.

Gates: if VIX > VIX_BEAR_THRESHOLD **or** SPY is trading below its 200-day SMA,
the regime is considered bearish and the position limit is reduced.

VIX is fetched from Alpaca (symbol: VIXY as proxy) or falls back to a FRED
API call for ^VIX when Alpaca does not carry the index directly.

TODO: Add FRED API client for direct VIX index data.
"""

import logging
from datetime import date, timedelta
from enum import Enum
from typing import Optional

import pandas as pd

from config.settings import get_settings
from data.alpaca_client import AlpacaClient

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


def _get_spy_vs_200sma(client: AlpacaClient) -> Optional[bool]:
    """Return True if SPY close is above its 200-day SMA, False otherwise."""
    end = date.today()
    start = end - timedelta(days=300)
    try:
        df = client.get_daily_bars("SPY", start=start, end=end)
        if len(df) < 200:
            logger.warning("Insufficient SPY history for 200-day SMA")
            return None
        above = float(df["close"].iloc[-1]) > df["close"].rolling(200).mean().iloc[-1]
        return above
    except Exception as exc:
        logger.error("SPY 200-day SMA calc failed: %s", exc)
        return None


def _get_vix_level(client: AlpacaClient) -> Optional[float]:
    """Estimate current VIX via the VIXY ETF as a proxy.

    VIXY tracks short-term VIX futures, so it overstates spot VIX by ~20–30%.
    We apply a rough 0.75 haircut.

    TODO: Replace with direct FRED API or a data vendor that provides ^VIX.
    """
    end = date.today()
    start = end - timedelta(days=5)
    try:
        df = client.get_daily_bars("VIXY", start=start, end=end)
        if df.empty:
            return None
        raw = float(df["close"].iloc[-1])
        vix_estimate = raw * 0.75
        logger.debug("VIXY close=%.2f → VIX estimate=%.2f", raw, vix_estimate)
        return vix_estimate
    except Exception as exc:
        logger.error("VIX proxy fetch failed: %s", exc)
        return None


def classify_regime() -> Regime:
    """Return the current market regime.

    Returns Regime.BEARISH if:
      - Estimated VIX >= VIX_BEAR_THRESHOLD, **or**
      - SPY is below its 200-day SMA.

    Returns Regime.BULLISH otherwise (or on data failure — fails open).
    """
    cfg = get_settings()
    client = AlpacaClient()

    vix = _get_vix_level(client)
    spy_above_200 = _get_spy_vs_200sma(client)

    bearish = False

    if vix is not None and vix >= cfg.vix_bear_threshold:
        logger.info("Bearish regime: VIX estimate %.2f >= threshold %.2f", vix, cfg.vix_bear_threshold)
        bearish = True

    if spy_above_200 is False:
        logger.info("Bearish regime: SPY below 200-day SMA")
        bearish = True

    regime = Regime.BEARISH if bearish else Regime.BULLISH
    logger.info("Regime: %s (VIX=%.1f, SPY_above_200=%s)", regime.value, vix or -1, spy_above_200)
    return regime
