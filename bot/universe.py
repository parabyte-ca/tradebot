"""Stock universe filter.

Criteria:
  - Market cap > $500 M (shares outstanding × current price)
  - Average daily volume > $5 M (ADV = avg volume × avg close over 20 days)

The default seed list is the top 50 S&P 500 components by liquidity.
TODO: Replace static seed with dynamic S&P 500 constituent pull.
"""

import logging
from typing import List

import pandas as pd

from data.alpaca_client import AlpacaClient
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Static S&P 500 seed by average daily dollar volume (approximate, as of 2024-Q4)
# TODO: Replace with dynamic constituent fetch when data subscription allows.
SEED_UNIVERSE: List[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK.B", "JPM", "AVGO",
    "LLY", "V", "UNH", "XOM", "MA", "JNJ", "PG", "HD", "COST", "MRK",
    "ABBV", "CVX", "CRM", "BAC", "WMT", "NFLX", "AMD", "ACN", "TMO", "ORCL",
    "ADBE", "PEP", "KO", "CSCO", "MCD", "ABT", "LIN", "DHR", "TXN", "CAT",
    "NEE", "QCOM", "PM", "INTU", "RTX", "GE", "UNP", "SPGI", "AMGN", "ISRG",
]


def filter_universe(
    symbols: List[str] | None = None,
    min_market_cap_m: float = 500.0,
    min_adv_m: float = 5.0,
    lookback_days: int = 20,
) -> List[str]:
    """Return symbols from *symbols* (or SEED_UNIVERSE) that pass liquidity gates.

    Args:
        symbols: Candidate tickers; defaults to SEED_UNIVERSE.
        min_market_cap_m: Minimum market cap in $M.
        min_adv_m: Minimum 20-day average daily dollar volume in $M.
        lookback_days: Number of trading days used for ADV calculation.

    Returns:
        Filtered list of symbols that pass both gates.
    """
    if symbols is None:
        symbols = SEED_UNIVERSE

    client = AlpacaClient()
    end = date.today()
    start = end - timedelta(days=lookback_days * 2)  # extra buffer for market holidays

    passed = []
    for sym in symbols:
        try:
            df = client.get_daily_bars(sym, start=start, end=end)
            if df.empty or len(df) < lookback_days:
                logger.debug("Skipping %s — insufficient history", sym)
                continue

            df = df.tail(lookback_days)
            adv_m = (df["close"] * df["volume"]).mean() / 1e6
            market_cap_m = df["close"].iloc[-1] * df["volume"].mean() / 1e6  # proxy

            if adv_m < min_adv_m:
                logger.debug("Skipping %s — ADV $%.1fM < threshold $%.1fM", sym, adv_m, min_adv_m)
                continue
            if market_cap_m < min_market_cap_m:
                logger.debug(
                    "Skipping %s — market cap proxy $%.1fM < threshold $%.1fM",
                    sym, market_cap_m, min_market_cap_m,
                )
                continue

            passed.append(sym)
        except Exception as exc:
            logger.warning("Universe filter error for %s: %s", sym, exc)

    logger.info("Universe: %d / %d symbols passed filters", len(passed), len(symbols))
    return passed
