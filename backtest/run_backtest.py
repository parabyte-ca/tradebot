"""Lumibot backtesting entrypoint.

Usage:
    python -m backtest.run_backtest

Results are written to backtest/results/ as JSON and CSV (gitignored).
"""

import json
import logging
import os
from datetime import datetime

from lumibot.backtesting import YahooDataBacktesting
from lumibot.traders import Trader

from bot.strategy import SwingBot
from config.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run(
    start_date: str = "2022-01-01",
    end_date: str = "2023-12-31",
    initial_capital: float = 100_000.0,
    output_dir: str = "backtest/results",
) -> dict:
    """Run a full backtest and persist results.

    Args:
        start_date:      ISO date string for backtest start.
        end_date:        ISO date string for backtest end.
        initial_capital: Starting cash in USD.
        output_dir:      Directory to write result files.

    Returns:
        Dictionary of performance statistics from Lumibot.
    """
    os.makedirs(output_dir, exist_ok=True)

    backtesting_start = datetime.strptime(start_date, "%Y-%m-%d")
    backtesting_end = datetime.strptime(end_date, "%Y-%m-%d")

    logger.info(
        "Starting backtest: %s → %s | capital=$%.0f",
        start_date,
        end_date,
        initial_capital,
    )

    results, strat_obj = SwingBot.backtest(
        YahooDataBacktesting,
        backtesting_start,
        backtesting_end,
        initial_capital=initial_capital,
        show_plot=False,
        save_logfile=False,
        parameters={},
    )

    # Persist results
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    results_path = os.path.join(output_dir, f"backtest_{timestamp}.json")
    with open(results_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)

    logger.info("Backtest complete. Results: %s", results_path)
    logger.info("CAGR: %s | Sharpe: %s | Max DD: %s",
                results.get("cagr"), results.get("sharpe"), results.get("max_drawdown"))

    return results


if __name__ == "__main__":
    run()
