# tradebot

> **⚠️ PAPER TRADING ONLY**
> This bot is configured exclusively for Interactive Brokers paper trading (TWS port 7497).
> Do not switch to live trading (port 7496) until a minimum 90-day paper validation period has passed with consistent, reviewed performance. No real money should be at risk during development.

AI-powered swing trading bot for Canadian retail trading of US-listed equities, self-hosted on TrueNAS SCALE. Uses LightGBM signals with FinBERT sentiment, Lumibot execution, and a full Prometheus + Grafana + Loki monitoring stack.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       TrueNAS SCALE (192.168.2.15)             │
│                                                                  │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────────┐ │
│  │   tradebot   │───▶│  Prometheus   │───▶│    Grafana :8420 │ │
│  │  (bot loop)  │    │    :9090      │    │  (dashboards)    │ │
│  │    :8421     │    └───────────────┘    └──────────────────┘ │
│  └──────┬───────┘                                               │
│         │ logs                ┌───────────┐                     │
│         ▼                     │   Loki    │                     │
│  ┌────────────┐               │   :3100   │                     │
│  │  Promtail  │──────────────▶│           │                     │
│  └────────────┘               └───────────┘                     │
│                                                                  │
│  External APIs                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │  Alpaca  │  │ Finnhub  │  │ SEC EDGAR│  │ IBKR TWS/IB  │  │
│  │  (OHLCV) │  │ (news)   │  │(fundmtls)│  │ Gateway:7497 │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Signal pipeline:**
```
Universe (50 S&P 500 stocks by liquidity)
  → Regime gate (VIX + SPY 200-day SMA)
  → Feature engineering (RSI, MACD, ATR, momentum, FinBERT sentiment)
  → LightGBM binary classifier (up/down in 5 days)
  → Half-Kelly position sizing (capped at 8% per position)
  → Bracket orders via IBKR TWS (entry + stop-loss + take-profit atomic)
  → Telegram alerts + Healthchecks.io heartbeat
```

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/parabyte-ca/tradebot.git
cd tradebot

# 2. Configure
cp .env.example .env
# Edit .env — fill in all API keys (see sections below)

# 3. Deploy
./setup.sh
```

Grafana dashboard: `http://192.168.2.15:8420` (or Tailscale IP)

---

## Interactive Brokers Canada — Account Setup

1. **Account type**: IBKR Pro margin account (USD denomination)
2. **Minimum equity**: USD $25,000 (pattern day trader rule, margin requirement)
3. **Funding**: EFT from Canadian bank; IBKR will hold in CAD and convert via IDEALPRO FX at ~0.08% spread
4. **Paper trading**: Enable via Account Management → Settings → Paper Trading Account. TWS paper port = **7497**.
5. **API access**: Enable in TWS → Edit → Global Configuration → API → Settings. Check "Enable ActiveX and Socket Clients". Set Trusted IP to `192.168.2.15`.
6. **TWS API credentials**:
   - Create a read-only key for market data (`IBKR_READONLY_KEY`)
   - Create a trading key for order submission (`IBKR_TRADING_KEY`) — **disable withdrawals** on this credential
7. **IP whitelist**: Both keys must be IP-restricted to `192.168.2.15` only

> **Security**: The IBKR account's API trading credential must have withdrawal permissions **disabled**. Document this in your account notes. Losing this key cannot result in fund withdrawal.

---

## CRA Tax Considerations

> **Not tax advice — consult a CPA.**

- Trading in a **non-registered margin account** (RRSP/TFSA are not eligible for active trading strategies that could constitute a business)
- CRA may classify frequent swing trading income as **business income** (T2125 — Statement of Business or Professional Activities), not capital gains
- Track: all fills (auto-logged to SQLite), commissions, data subscription costs, hosting costs as business expenses
- TFSA note: CRA has reassessed TFSAs used for active trading as business income — do **not** use a TFSA for this strategy

---

## API Keys Required

| Service | Key | Purpose |
|---------|-----|---------|
| Interactive Brokers | `IBKR_TRADING_KEY` | Order submission (paper) |
| Interactive Brokers | `IBKR_READONLY_KEY` | Market data |
| Alpaca | `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` | OHLCV data (free tier) |
| Finnhub | `FINNHUB_API_KEY` | News headlines (free tier) |
| Telegram | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Alerts |
| Healthchecks.io | `HEALTHCHECKS_URL` | Heartbeat monitoring (optional) |

---

## Running a backtest

```bash
docker exec -it tradebot python -m backtest.run_backtest
```

Results are written to `backtest/results/` (gitignored).

---

## Retraining the model

Retraining runs automatically every Sunday at 02:00 UTC via APScheduler.
To trigger manually:

```bash
docker exec -it tradebot python -c "from bot.main import _retrain_job; _retrain_job()"
```

---

## Monitoring

| URL | Service |
|-----|---------|
| `http://192.168.2.15:8420` | Grafana dashboard |
| `http://192.168.2.15:9090` | Prometheus |
| `http://192.168.2.15:8421/metrics` | Raw bot metrics |

Log stream: Grafana → Explore → Loki → `{container="tradebot"}`

---

## Out of scope (current version)

- Live trading (paper only until 90-day validation)
- Options trading
- Canadian-listed securities (CIRO DMR 3200 restriction on algorithmic trading of Canadian equities for retail)
- GPU-accelerated model training
- Cryptocurrency

---

## Licence

MIT — see [LICENSE](LICENSE)
