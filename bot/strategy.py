"""SwingBot — Lumibot Strategy subclass implementing the swing trading logic.

PAPER TRADING ONLY.
Do not switch IBKR_PORT to 7496 (live) until 90-day paper validation passes.

Iteration cycle: daily (sleeptime = "1D")
  1. Classify market regime (VIX + SPY 200-day SMA gate).
  2. Fetch features for the liquid universe.
  3. Score symbols via LightGBM.
  4. Size positions via half-Kelly.
  5. Submit bracket orders (entry + stop-loss + take-profit atomically).
  6. Alert Telegram on every new order.
  7. Ping Healthchecks.io heartbeat.

Circuit breaker: if on_trading_iteration raises unhandled exceptions 3 times
consecutively, the bot pauses itself and sends a CRITICAL Telegram alert.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from lumibot.brokers import InteractiveBrokers
from lumibot.strategies import Strategy
from lumibot.traders import Trader

from bot.alerts import alert_critical, alert_fill, send_heartbeat
from bot.features import compute_features
from bot.model import load_model, predict
from bot.regime import Regime, classify_regime
from bot.risk import size_positions
from bot.universe import SEED_UNIVERSE, filter_universe
from config.settings import get_settings
from data.alpaca_client import AlpacaClient
from data.cache import init_db, log_fill

logger = logging.getLogger(__name__)


class SwingBot(Strategy):
    """Daily swing trading strategy using LightGBM signals."""

    # --- Lumibot lifecycle ---------------------------------------------------

    def initialize(self) -> None:
        """Set up bot parameters, load model, initialise DB."""
        self.sleeptime = "1D"
        cfg = get_settings()
        self._cfg = cfg
        self._max_positions = cfg.max_positions
        self._consecutive_errors = 0

        init_db()
        self._model = load_model()
        if self._model is None:
            logger.warning("No trained model found — scores will default to 0.5")

        self._alpaca = AlpacaClient()
        # Build initial universe synchronously on start
        try:
            self._universe = filter_universe()
        except Exception as exc:
            logger.error("Universe filter failed on init: %s — using seed", exc)
            self._universe = list(SEED_UNIVERSE)

        logger.info(
            "SwingBot initialized | universe=%d | max_positions=%d",
            len(self._universe),
            self._max_positions,
        )

    def on_trading_iteration(self) -> None:
        """Main daily trading loop."""
        try:
            self._run_iteration()
            self._consecutive_errors = 0
        except Exception as exc:
            self._consecutive_errors += 1
            logger.error(
                "on_trading_iteration error #%d: %s",
                self._consecutive_errors,
                exc,
                exc_info=True,
            )
            if self._consecutive_errors >= 3:
                alert_critical(
                    f"SwingBot paused after {self._consecutive_errors} consecutive "
                    f"unhandled errors.\nLast error: {exc}"
                )
                logger.critical("Pausing bot due to repeated errors")
                self.is_backtesting or self._pause()
        finally:
            send_heartbeat()

    def on_filled_order(self, position, order, price, quantity, multiplier) -> None:
        """Called by Lumibot when an order fill is confirmed."""
        symbol = order.asset.symbol if hasattr(order.asset, "symbol") else str(order.asset)
        side = order.side
        try:
            log_fill(symbol, side, float(quantity), float(price), str(order.identifier))
        except Exception as exc:
            logger.error("Failed to log fill for %s: %s", symbol, exc)
        alert_fill(symbol, side, float(quantity), float(price), str(order.identifier))

    # --- Internal helpers ----------------------------------------------------

    def _pause(self) -> None:
        """Stop the trading loop without killing the process."""
        self.sleeptime = "1000D"  # effectively pause until operator restarts
        logger.critical("SwingBot paused — set sleeptime=1D to resume")

    def _run_iteration(self) -> None:
        """Core logic, extracted so the error counter wraps the whole block."""
        cfg = self._cfg

        # 1. Regime gate
        regime = classify_regime()
        if regime == Regime.BEARISH:
            self._max_positions = 3
            logger.info("Bearish regime — reducing max positions to 3")
        else:
            self._max_positions = cfg.max_positions

        # 2. Fetch features for universe
        from datetime import date  # noqa: PLC0415
        end = date.today()
        start = end - timedelta(days=250)

        feature_rows: Dict[str, object] = {}
        prices: Dict[str, float] = {}

        for symbol in self._universe:
            try:
                df = self._alpaca.get_daily_bars(symbol, start=start, end=end)
                if df.empty:
                    continue
                feat = compute_features(symbol, df)
                if feat.empty:
                    continue
                # Fill regime columns from classify_regime result
                # (avoids re-fetching for each symbol)
                feat["spy_above_200"] = 1.0 if regime == Regime.BULLISH else 0.0
                feature_rows[symbol] = feat
                prices[symbol] = float(df["close"].iloc[-1])
            except Exception as exc:
                logger.warning("Feature fetch failed for %s: %s", symbol, exc)

        if not feature_rows:
            logger.warning("No features computed — skipping iteration")
            return

        # 3. Score via model
        import pandas as pd  # noqa: PLC0415

        all_features = pd.concat(list(feature_rows.values()), ignore_index=True)
        all_features.index = list(feature_rows.keys())

        if self._model is not None:
            scores_series = predict(self._model, all_features)
            scores = dict(scores_series)
        else:
            scores = {sym: 0.5 for sym in feature_rows}

        # 4. Size positions via half-Kelly
        portfolio_value = float(self.portfolio_value)
        position_orders = size_positions(
            scores=scores,
            prices=prices,
            portfolio_value=portfolio_value,
            max_positions=self._max_positions,
        )

        # 5. Determine what we already hold vs. what we want
        current_positions = {
            p.asset.symbol: p
            for p in self.get_positions()
            if hasattr(p.asset, "symbol")
        }
        target_symbols = {o.symbol for o in position_orders}

        # Exit positions no longer in target
        for sym, pos in current_positions.items():
            if sym not in target_symbols:
                self.sell_all(sym)
                logger.info("Exiting %s (not in new target set)", sym)

        # Enter new positions with bracket orders
        for order in position_orders:
            if order.symbol in current_positions:
                continue  # already held — do not double-up

            entry_price = prices[order.symbol]
            stop_price = round(entry_price * (1 - cfg.stop_loss_pct), 2)
            tp_price = round(entry_price * (1 + cfg.take_profit_pct), 2)

            # Bracket order: entry + stop + take-profit atomically
            # Safety invariant: stop is ALWAYS submitted with the entry.
            bracket = self.create_order(
                asset=order.symbol,
                quantity=order.quantity,
                side="buy",
                order_type="bracket",
                stop_loss_price=stop_price,
                take_profit_price=tp_price,
            )
            self.submit_order(bracket)
            logger.info(
                "Bracket order: BUY %d %s @ market | SL=%.2f | TP=%.2f",
                order.quantity,
                order.symbol,
                stop_price,
                tp_price,
            )
            # Telegram fill alert is sent in on_filled_order upon confirmation
