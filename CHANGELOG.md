# Changelog

All notable changes to tradebot are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/).

---

## [0.1.0] — 2026-04-29

### Added
- Initial project scaffold
- `bot/strategy.py` — `SwingBot` Lumibot Strategy with daily swing trading loop
- `bot/features.py` — Feature engineering: RSI, MACD, ATR, BB width, momentum, mean-reversion, FinBERT sentiment
- `bot/model.py` — LightGBM binary classifier with triple-barrier labelling and purged walk-forward CV
- `bot/regime.py` — Regime classifier: VIX proxy + SPY 200-day SMA gate
- `bot/universe.py` — Stock universe filter: market cap > $500M, ADV > $5M
- `bot/risk.py` — Half-Kelly position sizing, 8% position cap
- `bot/alerts.py` — Telegram webhook for fills, drawdown, heartbeat, critical errors
- `bot/main.py` — Entrypoint: Prometheus metrics, APScheduler weekly retrain, Lumibot Trader
- `data/alpaca_client.py` — Alpaca OHLCV data wrapper
- `data/finnhub_client.py` — Finnhub news sentiment fetcher with SQLite cache
- `data/edgar_client.py` — SEC EDGAR fundamentals fetcher
- `data/cache.py` — SQLite cache for OHLCV, sentiment, fills, and KV store
- `config/settings.py` — Typed pydantic-settings configuration loaded from `.env`
- `backtest/run_backtest.py` — Lumibot backtesting entrypoint
- `docker-compose.yml` — Full stack: tradebot, Prometheus, Grafana, Loki, Promtail
- `Dockerfile` — Python 3.11-slim container
- `monitoring/` — Prometheus scrape config, Loki/Promtail config, Grafana auto-provisioning
- `setup.sh` / `update.sh` — Deployment scripts
- `.env.example` — Full config template with documentation
- `requirements.txt` — Pinned Python dependencies
