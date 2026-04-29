"""Bot entrypoint: wires together Lumibot, APScheduler, and Prometheus metrics.

Starts:
  1. Prometheus HTTP server on port 8421.
  2. APScheduler weekly retraining cron.
  3. Lumibot Trader with the IBKR broker in paper-trading mode.
"""

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from lumibot.brokers import InteractiveBrokers
from lumibot.traders import Trader
from prometheus_client import Gauge, start_http_server

from bot.strategy import SwingBot
from config.settings import get_settings
from data.cache import init_db

# Structured JSON logging for Promtail → Loki
from pythonjsonlogger import jsonlogger

_handler = logging.StreamHandler()
_handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])
logger = logging.getLogger(__name__)

# Prometheus gauges (populated by strategy callbacks in a production build)
# TODO: Add more granular per-position and fill-rate metrics.
PORTFOLIO_VALUE = Gauge("tradebot_portfolio_value", "Total portfolio equity in USD")
OPEN_POSITIONS = Gauge("tradebot_open_positions", "Number of open positions")
REGIME_BEARISH = Gauge("tradebot_regime_bearish", "1 if current regime is bearish")


def _retrain_job() -> None:
    """Weekly model retraining — called by APScheduler."""
    logger.info("Starting weekly model retrain")
    try:
        from bot.model import save_model, train_model  # noqa: PLC0415
        from bot.universe import SEED_UNIVERSE  # noqa: PLC0415
        from data.alpaca_client import AlpacaClient  # noqa: PLC0415
        from datetime import date, timedelta  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
        from bot.features import compute_features  # noqa: PLC0415

        client = AlpacaClient()
        end = date.today()
        start = end - timedelta(days=500)
        frames = []
        for sym in SEED_UNIVERSE[:20]:  # limit for free-tier API budget
            try:
                df = client.get_daily_bars(sym, start=start, end=end)
                if len(df) > 210:
                    feat = compute_features(sym, df)
                    if not feat.empty:
                        feat["close"] = df["close"].iloc[-1]
                        frames.append(feat)
            except Exception as exc:
                logger.warning("Retrain data fetch failed for %s: %s", sym, exc)

        if not frames:
            logger.error("No training data collected — skipping retrain")
            return

        combined = pd.concat(frames, ignore_index=True)
        model, aucs = train_model(combined)
        save_model(model)
        logger.info("Retrain complete. Mean AUC=%.4f", sum(aucs) / len(aucs) if aucs else 0)
    except Exception as exc:
        logger.error("Retrain job failed: %s", exc, exc_info=True)


def main() -> None:
    """Main entrypoint."""
    cfg = get_settings()
    init_db()

    # Start Prometheus metrics server
    start_http_server(8421)
    logger.info("Prometheus metrics server started on :8421")

    # Start weekly retraining scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(_retrain_job, "cron", day_of_week="sun", hour=2, minute=0)
    scheduler.start()
    logger.info("APScheduler started — weekly retrain scheduled for Sunday 02:00 UTC")

    # Configure IBKR broker (paper trading)
    broker = InteractiveBrokers(
        config={
            "host": cfg.ibkr_host,
            "port": cfg.ibkr_port,
            "clientId": cfg.ibkr_client_id,
        }
    )

    strategy = SwingBot(
        broker=broker,
        parameters={},
    )

    trader = Trader()
    trader.add_strategy(strategy)

    logger.info(
        "Starting SwingBot | IBKR %s:%d (client_id=%d) | PAPER TRADING ONLY",
        cfg.ibkr_host,
        cfg.ibkr_port,
        cfg.ibkr_client_id,
    )
    trader.run_all()


if __name__ == "__main__":
    main()
