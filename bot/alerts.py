"""Telegram webhook alerts: fills, drawdown warnings, heartbeat failures.

Sends messages via the Telegram Bot HTTP API.  All calls are fire-and-forget
with a short timeout so alert failures never block the trading loop.
"""

import logging
from typing import Optional

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)


def _send(text: str, parse_mode: str = "Markdown") -> bool:
    """POST a message to the configured Telegram chat.

    Returns True on success, False on any error.
    """
    cfg = get_settings()
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        logger.warning("Telegram not configured — alert suppressed: %s", text[:80])
        return False

    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": cfg.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Telegram alert failed: %s", exc)
        return False


def alert_fill(
    symbol: str,
    side: str,
    quantity: float,
    fill_price: float,
    order_id: Optional[str] = None,
) -> None:
    """Send a fill confirmation alert."""
    emoji = "🟢" if side.lower() == "buy" else "🔴"
    text = (
        f"{emoji} *FILL* — {side.upper()} {quantity:.0f} × `{symbol}`\n"
        f"Price: `${fill_price:.2f}`"
    )
    if order_id:
        text += f"\nOrder ID: `{order_id}`"
    _send(text)


def alert_drawdown(current_pct: float, threshold_pct: float) -> None:
    """Send a drawdown warning alert."""
    text = (
        f"⚠️ *DRAWDOWN ALERT*\n"
        f"Portfolio drawdown: `{current_pct:.1%}` (threshold: `{threshold_pct:.1%}`)"
    )
    _send(text)


def alert_critical(message: str) -> None:
    """Send a CRITICAL-level alert (bot pause, unhandled exception storm)."""
    text = f"🚨 *CRITICAL — tradebot*\n{message}"
    _send(text)


def alert_heartbeat_failure(detail: str = "") -> None:
    """Send a heartbeat failure alert."""
    text = f"💔 *HEARTBEAT FAILED — tradebot*"
    if detail:
        text += f"\n{detail}"
    _send(text)


def send_heartbeat() -> None:
    """Ping the Healthchecks.io URL to signal the bot is alive."""
    cfg = get_settings()
    if not cfg.healthchecks_url:
        return
    try:
        requests.get(cfg.healthchecks_url, timeout=5)
        logger.debug("Heartbeat sent to Healthchecks.io")
    except Exception as exc:
        logger.error("Heartbeat ping failed: %s", exc)
        alert_heartbeat_failure(str(exc))
