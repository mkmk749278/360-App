# 360-Crypto-Scalping V2 — AI-Powered Futures Scalping Engine

A high-performance, fully asynchronous Python engine that scans the **top 50 USDT-M futures pairs** on Binance in real time, detects Smart Money Concepts (SMC) setups, calculates dynamic confidence scores (0–100), and routes signals to a **single Active Trading** Telegram channel.

> **Version:** 2.0.0 &nbsp;|&nbsp; **Python:** ≥ 3.11 &nbsp;|&nbsp; **Tests:** 2,300+ &nbsp;|&nbsp; **Deployment:** Docker Compose (one-click)

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Usage Examples](#usage-examples)
7. [Telegram Commands](#telegram-commands)
8. [Signal Format](#signal-format)
9. [Project Structure](#project-structure)
10. [Testing](#testing)
11. [Troubleshooting](#troubleshooting)
12. [Contributing](#contributing)
13. [License](#license)

---

## Project Overview

360-Crypto-Scalping V2 is a **production-grade, 24/7 crypto signal engine** built on these core principles:

- **Single Channel** — All signals go to one **Active Trading** Telegram channel. No separate portfolio channels; simpler for users, easier to maintain.
- **Top-50 Futures Only** — Scans the top 50 USDT-M futures by 24 h volume. Reduces API weight, memory, and scan latency compared to scanning 800+ pairs.
- **Docker-First** — One-click VPS deployment with Docker Compose. No manual Python/venv setup needed.
- **Async-First** — Full `asyncio` + `aiohttp` architecture with WebSocket + REST parallelism.
- **Fault-Tolerant** — WebSocket auto-reconnect, REST fallback, graceful Redis degradation, circuit-breaker protection.

---

## Architecture

```
Binance REST ──► PairManager (top-50 futures, tier-based, auto-refresh)
                       │
                       ▼
              HistoricalDataStore (OHLCV seed × 6 timeframes, disk cache)
                       │
Binance WS ──► WebSocketManager (multi-conn, heartbeat, auto-reconnect)
                       │
                       ▼
                  Scanner Loop (10+ gate pipeline)
           ┌───────────┤────────────────┐──────────────┐
      Indicators    SMC Algos     AI Engine       Regime Detector
       (EMA, RSI,   (Sweep,       (News, Social,  (Trending, Ranging,
        MACD, ADX,   MSS, FVG)    Whale, GPT-4)   Volatile, Quiet)
        ATR, BB)
           └───────────┤────────────────┘──────────────┘
                       ▼
              5 × Scalp Strategies
        ┌──────┬───────┬───────┬───────┐
      SCALP   FVG    CVD   VWAP    OBI
        └──────┴───────┴───────┴───────┘
                       │
            Gating Filters & Quality Checks
         (MTF confluence, correlation, kill-zone,
          macro blackout, OI, spoof detect, spread)
                       │
               ConfidenceScorer (0–100)
                       │
                Signal Queue (Redis / asyncio)
                       │
                       ▼
                 SignalRouter ──► Telegram
                       │             ├─ ⚡ Active Trading
                       │             └─ 🆓 Free Channel (optional)
                       ▼
                 TradeMonitor
           (TP/SL · Trailing · DCA · Updates)
                       │
           ┌───────────┼───────────────┐
     PerformanceTracker          CircuitBreaker
     (rolling stats, per-pair)   (auto-pause on loss)
           │
     TradeObserver + FeedbackLoop
     (lifecycle capture, AI digest)
```

### Boot Sequence

1. **Redis connection** — graceful fallback to in-memory if unavailable.
2. **Pair fetching** — top-50 futures (or full universe if `TOP50_FUTURES_ONLY=false`).
3. **Historical data seeding** — load disk cache and gap-fill, or full fetch (1–5 min).
4. **Load predictive model** — multi-factor price-direction forecaster.
5. **Start WebSocket connections** — Tier 1 pairs only; Tier 2/3 use REST.
6. **Pre-flight checks** — Telegram, pairs, data, Redis, Binance API.
7. **Launch runtime tasks** — scanner loop, signal router, trade monitor, telemetry, pair refresh, macro watchdog, trade observer, and more.

---

## Features

### Core Trading Engine

| Feature | Module(s) | Description |
|---|---|---|
| **SMC Detection** | `src/smc.py` | Liquidity sweeps, Market Structure Shifts (MSS), Fair Value Gaps (FVG) |
| **5 Scalp Strategies** | `src/channels/` | Standard Scalp, FVG, CVD Divergence, VWAP Deviation, Order Book Imbalance |
| **Confidence Scoring** | `src/confidence.py` | Multi-layer 0–100 scorer with 8+ sub-components (SMC, trend, liquidity, spread, data sufficiency, multi-exchange, on-chain, order flow, AI sentiment, correlation) |
| **Multi-Timeframe** | `src/mtf.py` | 1 m / 5 m / 15 m / 1 h / 4 h / 1 d confluence and gating |
| **Market Regime** | `src/regime.py` | Trending Up/Down, Ranging, Volatile, Quiet classification with penalty system |
| **Dynamic Pairs** | `src/pair_manager.py` | Auto-fetch top-50 futures by volume, 3-tier partitioning (T1/T2/T3), auto-prune |
| **Dynamic Tiering** | `src/tier_manager.py` | Live re-ranking based on volume (70 %) + volatility (30 %) weighting |

### AI & Prediction

| Feature | Module(s) | Description |
|---|---|---|
| **AI Sentiment** | `src/ai_engine/` | CryptoPanic news, LunarCrush social, Fear & Greed Index |
| **Predictive AI** | `src/predictive_ai.py` | Multi-factor price-direction forecasting (EMA, RSI, ADX, ATR, BB, momentum) |
| **GPT-4 Evaluator** | `src/openai_evaluator.py` | Macro-event evaluation via OpenAI (optional) |
| **Macro Watchdog** | `src/macro_watchdog.py` | Async news / sentiment / Fear & Greed poller |

### Risk & Protection

| Feature | Module(s) | Description |
|---|---|---|
| **Circuit Breaker** | `src/circuit_breaker.py` | Auto-pause after consecutive SL hits, hourly/daily drawdown limits, per-symbol caps |
| **Risk Management** | `src/risk.py` | Position sizing, risk labels, concurrent signal validation |
| **DCA Logic** | `src/dca.py` | Dollar-cost averaging / double-entry zones |
| **Kill Zone Gate** | `src/kill_zone.py` | Reversal-zone suppression |
| **Macro Blackout** | `src/macro_blackout.py` | Blackout periods around high-impact events |

### Signal Quality & Filtering

| Feature | Module(s) | Description |
|---|---|---|
| **Gating Filters** | `src/filters.py` | Spread, ADX, volume, MACD, RSI, EMA alignment |
| **Correlation Filter** | `src/correlation.py`, `src/cross_asset.py` | BTC/ETH "sneeze" prevention, graduated correlation gating |
| **Cluster Suppression** | `src/cluster_suppression.py` | De-duplication of correlated signals |
| **Spoof Detection** | `src/spoof_detect.py` | Order-book spoofing gate |
| **Volume Divergence** | `src/volume_divergence.py` | Volume divergence filters |
| **OI Filter** | `src/oi_filter.py` | Open Interest gating |
| **Confidence Decay** | `src/confidence_decay.py` | Time-based confidence degradation |

### Monitoring & Analytics

| Feature | Module(s) | Description |
|---|---|---|
| **Trade Monitoring** | `src/trade_monitor.py` | Real-time TP/SL tracking, trailing stops, PnL updates |
| **Performance Tracker** | `src/performance_tracker.py` | Persisted rolling stats (7 d / 30 d), per-channel, per-pair |
| **Per-Pair Analysis** | `src/pair_analyzer.py`, `src/pair_anomaly_detector.py` | Quality metrics, anomaly detection, recommendations |
| **Trade Observer** | `src/trade_observer.py` | Full trade lifecycle capture, AI-generated digests |
| **Telemetry** | `src/telemetry.py` | CPU, memory, WS health, scan latency, API usage, queue size |
| **Suppression Telemetry** | `src/suppress_telemetry.py` | Tracks all suppression reasons & events for diagnostics |

### Infrastructure

| Feature | Module(s) | Description |
|---|---|---|
| **WebSocket Resilience** | `src/websocket_manager.py` | Multi-connection, heartbeat, exponential-backoff reconnect, REST fallback |
| **Redis Caching** | `src/redis_client.py` | Optional Redis-backed state persistence with in-memory fallback |
| **Binance API Client** | `src/binance.py` | Rate-limit tracking, 429/418 retry, request-weight accounting |
| **Multi-Exchange** | `src/exchange.py` | Cross-exchange verification (Bybit/OKX) |
| **Historical Data** | `src/historical_data.py` | OHLCV + tick seeding, disk caching, gap-fill after restarts |
| **Admin Commands** | `src/commands/` | Decorator-based command registry with 30+ Telegram commands |
| **Backtesting** | `src/backtester.py` | Full backtesting engine with slippage/fee modelling |
| **Chart Generation** | `src/chart_generator.py` | TradingView-style chart images |
| **Cornix Format** | `src/cornix_formatter.py` | Cornix auto-execution message formatting (optional) |
| **On-Chain Data** | `src/onchain.py` | Glassnode + Whale Alert integration (optional) |
| **Gem Scanner** | `src/pair_manager.py` | Macro reversal scanner for deeply discounted alts (optional) |
| **Order Flow** | `src/order_flow.py` | Liquidation events, Open Interest polling |

---

## Installation

### Option A — One-Click VPS Deployment (Recommended)

Deploy on a fresh Ubuntu VPS (20.04 / 22.04 / 24.04) with a single command:

```bash
git clone https://github.com/mkmk749278/360-v2.git && cd 360-v2
cp .env.example .env
nano .env              # Fill in your Telegram credentials
sudo bash deploy_vps.sh
```

That's it. The script installs Docker, builds the image, and starts Redis + Engine.

#### What `deploy_vps.sh` does

1. Installs Docker & Docker Compose (if not present)
2. Clones/updates the repository
3. Creates `.env` from `.env.example`
4. Builds the Docker image
5. Starts Redis + Engine with `docker compose up -d`
6. Prints management commands

### Option B — Docker Compose (Manual)

Requires Docker and Docker Compose already installed:

```bash
git clone https://github.com/mkmk749278/360-v2.git && cd 360-v2
cp .env.example .env
nano .env
docker compose build
docker compose up -d
```

### Option C — Bare-Metal (Development)

```bash
git clone https://github.com/mkmk749278/360-v2.git && cd 360-v2
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env

# Optional: start Redis locally
redis-server --daemonize yes

# Run the engine
python -m src.main
```

### Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| Docker (for VPS/container deployment) | 20.10+ |
| Docker Compose | V2 |
| Redis (optional, auto-started in Docker) | 7+ |

### Service Management

```bash
docker compose logs -f engine      # Follow live logs
docker compose restart engine      # Restart the engine
docker compose down                # Stop everything
docker compose up -d --build       # Rebuild and restart
docker compose ps                  # Check status
sudo bash deploy_vps.sh --clean    # Full cleanup and redeploy
```

---

## Configuration

All configuration is managed through environment variables. Copy `.env.example` to `.env` and edit before deploying.

### Required Variables

| Variable | Description | How to Get |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token | [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_ACTIVE_CHANNEL_ID` | Active Trading channel ID | Add [@RawDataBot](https://t.me/RawDataBot) to the channel |
| `TELEGRAM_ADMIN_CHAT_ID` | Your personal chat ID | Send `/start` to [@userinfobot](https://t.me/userinfobot) |

### Optional — AI APIs

The engine works without any external API keys (confidence capped at ~85 %).

| Variable | Service | Free? |
|---|---|---|
| `NEWS_API_KEY` | [CryptoPanic](https://cryptopanic.com/developers/api/) — news sentiment | Yes |
| `SOCIAL_SENTIMENT_API_KEY` | [LunarCrush](https://lunarcrush.com/developers) — social sentiment | Yes |
| `OPENAI_API_KEY` | [OpenAI](https://platform.openai.com/api-keys) — GPT-4 macro evaluator | No |
| `ONCHAIN_API_KEY` | [Glassnode](https://glassnode.com/) — on-chain intelligence | No |

### Optional — Binance API

Public market-data endpoints require **no keys**. Only set these for authenticated endpoints:

| Variable | Description |
|---|---|
| `BINANCE_API_KEY` | Binance API key |
| `BINANCE_API_SECRET` | Binance API secret |

### Engine Settings (Defaults)

| Variable | Default | Description |
|---|---|---|
| `TOP50_FUTURES_ONLY` | `true` | Restrict to top-50 USDT-M futures |
| `TOP50_FUTURES_COUNT` | `50` | Number of futures pairs to track |
| `TOP50_UPDATE_INTERVAL_SECONDS` | `3600` | Refresh interval for the top-50 list |
| `SCAN_INTERVAL_SECONDS` | `1` | Scanner loop interval |
| `SCAN_MIN_VOLUME_USD` | `1000000` | Minimum 24 h volume to scan a pair |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL (auto-configured in Docker) |

### Circuit Breaker Settings

| Variable | Default | Description |
|---|---|---|
| `CIRCUIT_BREAKER_MAX_CONSECUTIVE_SL` | `3` | Pause after N consecutive stop-losses |
| `CIRCUIT_BREAKER_MAX_HOURLY_SL` | `5` | Maximum SL hits per hour |
| `CIRCUIT_BREAKER_MAX_DAILY_DRAWDOWN_PCT` | `10.0` | Daily drawdown limit (%) |
| `CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `900` | Cooldown after circuit breaker triggers |

### Concurrent Signal Limits

| Variable | Default | Description |
|---|---|---|
| `MAX_SCALP_SIGNALS` | `5` | Max concurrent Standard Scalp signals |
| `MAX_SCALP_FVG_SIGNALS` | `3` | Max concurrent FVG signals |
| `MAX_SCALP_CVD_SIGNALS` | `3` | Max concurrent CVD signals |
| `MAX_SCALP_VWAP_SIGNALS` | `3` | Max concurrent VWAP signals |
| `MAX_SCALP_OBI_SIGNALS` | `3` | Max concurrent OBI signals |

> See `.env.example` for the full list of all configurable variables.

---

## Usage Examples

### Viewing Logs

```bash
# Follow live engine output
docker compose logs -f engine

# View last 100 lines
docker compose logs --tail=100 engine
```

### Updating to Latest Code

```bash
cd 360-v2
git pull
docker compose up -d --build
```

Or via Telegram (admin only):

```
/deploy          # Git pull + rebuild + restart
/rollback        # Revert to previous commit
```

### Force-Scanning

```
/scan            # Trigger an immediate scan cycle
```

### Running a Backtest

```
/bt BTCUSDT      # Backtest a single pair
/bt_all          # Backtest all Tier 1 pairs
/bt_config       # View/adjust backtest parameters (slippage, fees)
```

### Checking Performance

```
/dashboard       # Full 7-day / 30-day stats dashboard
/stats           # Per-channel win rate, P/L stats
/tp_stats        # TP hit rate analysis
/report          # Generate detailed pair analysis report
```

---

## Telegram Commands

### Admin Commands

| Command | Description |
|---|---|
| `/status` | Engine uptime, tasks, queue, WS health |
| `/dashboard` | Full performance dashboard (7 d / 30 d stats) |
| `/scan` | Trigger immediate scanner cycle |
| `/pairs` | View active pairs by tier |
| `/update_pairs` | Manually refresh the top-50 pair list |
| `/view_active_signals` | List all currently active signals |
| `/logs [lines]` | View recent log output |
| `/stats` | Per-channel performance statistics |
| `/breaker` | Circuit breaker status & reset |
| `/pause <channel>` | Pause a channel (e.g., `SCALP`) |
| `/resume <channel>` | Resume a paused channel |
| `/confidence <value>` | Override minimum confidence threshold |
| `/restart` | Graceful engine restart |
| `/deploy` | Pull latest code, rebuild, restart |
| `/rollback` | Revert to previous Git commit |
| `/suppressed` | View suppressed signals today |
| `/report` | Generate per-pair analysis report |
| `/digest` | Generate AI trade digest |
| `/gem` | Toggle GEM scanner mode |
| `/gem_config` | Configure GEM scanner parameters |
| `/subscribe_alerts` | Subscribe to admin alert notifications |
| `/force_update_ai` | Force-reload predictive model |
| `/set_free_channel_limit` | Adjust free-channel signal count |

### User Commands

| Command | Description |
|---|---|
| `/signals` | Show last 5 active signals |
| `/info <id>` | Detailed info on a specific signal |
| `/history` | Last 10 completed signals with PnL |
| `/last_update` | Last scan latency & pair count |
| `/signal_stats` | Signal quality statistics |
| `/tp_stats` | TP hit rate statistics |
| `/free_signals` | Today's free channel highlights |
| `/subscribe` | Subscribe to premium notifications |
| `/unsubscribe` | Unsubscribe from notifications |

### Backtest Commands

| Command | Description |
|---|---|
| `/bt <symbol>` | Backtest a single symbol |
| `/bt_all` | Backtest all Tier 1 pairs |
| `/bt_config` | View/configure backtest parameters |

---

## Signal Format

Signals are posted to the Active Trading Telegram channel in the following format:

```
⚡ SCALP ALERT 💎
Pair: BTCUSDT (Futures)
📈 LONG 🚀
🚀 Entry: 68,150
🛡️ SL: 68,080
🎯 TP1: 68,250 (1R)
🎯 TP2: 68,350 (1.5R)
🎯 TP3: 68,500 (2R)
💹 Trailing: 1.5×ATR
🤖 Confidence: 87%
📰 AI: Bullish — Whale accumulation detected
⚠️ Risk: Moderate
```

Signals are updated in real time as targets are hit:

```
✅ TP1 HIT — BTCUSDT +1R (+0.15%)
✅ TP2 HIT — BTCUSDT +1.5R (+0.22%)
🔒 Trailing stop moved to breakeven
```

---

## Project Structure

```
360-v2/
├── config/
│   └── __init__.py                # Centralized settings, constants, defaults
├── src/
│   ├── main.py                    # Engine orchestrator & entry point
│   ├── bootstrap.py               # Boot sequence, WS initialisation, shutdown
│   ├── scanner/                   # Core scanning loop (10+ gate pipeline)
│   │   ├── __init__.py            # Main scan loop (1,600+ lines)
│   │   ├── data_fetcher.py        # REST / WS data retrieval
│   │   ├── indicator_compute.py   # Batch indicator calculation
│   │   ├── common_gates.py        # Shared gating logic
│   │   ├── filter_module.py       # Modular filter pipeline
│   │   ├── regime_manager.py      # Regime-aware scan adjustments
│   │   └── ws_optimizer.py        # WS stream optimisation
│   ├── channels/                  # Strategy implementations
│   │   ├── base.py                # Base channel class & signal model
│   │   ├── scalp.py               # Standard Scalp (M1/M5)
│   │   ├── scalp_fvg.py           # Fair Value Gap scalp
│   │   ├── scalp_cvd.py           # CVD divergence scalp
│   │   ├── scalp_vwap.py          # VWAP deviation scalp
│   │   ├── scalp_obi.py           # Order Book Imbalance scalp
│   │   └── signal_params.py       # Risk / TP parameter tables
│   ├── commands/                  # Telegram command handlers
│   │   ├── __init__.py            # CommandHandler (dispatcher)
│   │   ├── registry.py            # Decorator-based command registry
│   │   ├── signals.py             # /signals, /history, /info, /subscribe
│   │   ├── engine.py              # /status, /dashboard, /scan, /pairs, /logs
│   │   ├── channels.py            # /pause, /resume, /confidence, /breaker
│   │   ├── deploy.py              # /deploy, /restart, /rollback
│   │   └── backtest.py            # /bt, /bt_all, /bt_config
│   ├── ai_engine/                 # AI sentiment & prediction
│   │   ├── __init__.py            # CryptoPanic, LunarCrush, Fear & Greed
│   │   ├── predictor.py           # Price-direction forecasting
│   │   ├── scorer.py              # AI confidence sub-scoring
│   │   └── feedback.py            # Outcome feedback integration
│   ├── indicators.py              # EMA, SMA, RSI, MACD, ADX, ATR, BB
│   ├── smc.py                     # Liquidity Sweeps, MSS, FVG detection
│   ├── confidence.py              # Multi-layer confidence scorer (0–100)
│   ├── regime.py                  # Market regime classification
│   ├── mtf.py                     # Multi-timeframe confluence
│   ├── pair_manager.py            # Dynamic top-50 pair management
│   ├── pair_analyzer.py           # Per-pair quality metrics
│   ├── pair_anomaly_detector.py   # Anomaly detection (9 types)
│   ├── pair_analysis_report.py    # Analysis report orchestration
│   ├── tier_manager.py            # Dynamic tier re-ranking
│   ├── historical_data.py         # OHLCV & tick seeding, disk cache
│   ├── websocket_manager.py       # Multi-connection WS with resilience
│   ├── signal_router.py           # Queue → enrichment → Telegram
│   ├── signal_queue.py            # Redis-backed queue (asyncio fallback)
│   ├── trade_monitor.py           # TP/SL/trailing monitoring
│   ├── trade_observer.py          # Trade lifecycle + AI digests
│   ├── telegram_bot.py            # Telegram formatting & commands
│   ├── telemetry.py               # System health monitoring
│   ├── circuit_breaker.py         # Auto-pause after consecutive losses
│   ├── performance_tracker.py     # Signal outcome tracking
│   ├── performance_metrics.py     # PnL, drawdown, outcome helpers
│   ├── predictive_ai.py           # ML price direction prediction
│   ├── openai_evaluator.py        # GPT-4 macro evaluation
│   ├── macro_watchdog.py          # Async news/sentiment poller
│   ├── risk.py                    # Position sizing & risk enforcement
│   ├── filters.py                 # Pre-signal filter functions
│   ├── correlation.py             # BTC/ETH correlation groups
│   ├── cross_asset.py             # Cross-asset "sneeze" filter
│   ├── order_flow.py              # Liquidation events, OI polling
│   ├── order_book.py              # Order book depth analysis
│   ├── exchange.py                # Multi-exchange abstraction
│   ├── binance.py                 # Binance REST/WS API client
│   ├── redis_client.py            # Async Redis wrapper (fallback)
│   ├── backtester.py              # Full backtesting engine
│   ├── dca.py                     # DCA / double-entry logic
│   ├── onchain.py                 # Glassnode + Whale Alert
│   ├── chart_generator.py         # TradingView-style charts
│   └── cornix_formatter.py        # Cornix auto-execution format
├── tests/                         # 91 test files, 2,300+ tests
├── assets/icons/                  # SVG branding assets
├── Dockerfile                     # Python 3.12, non-root, healthcheck
├── docker-compose.yml             # Engine + Redis (resource-limited)
├── deploy_vps.sh                  # One-click VPS deployment
├── deploy.sh                      # Docker-only build & start
├── healthcheck.py                 # Container health probe
├── requirements.txt               # Python dependencies
├── pyproject.toml                 # Build config, pytest, ruff, mypy
├── .env.example                   # Template with all variables
└── .gitignore
```

---

## Testing

The project includes **91 test files** with **2,300+ tests** covering all major subsystems.

### Running Tests

```bash
# Install dependencies
pip install -r requirements.txt

# Run full test suite (recommended)
python -m pytest tests/ -x --ignore=tests/test_deployment.py -q

# Run with verbose output
python -m pytest tests/ -v --ignore=tests/test_deployment.py

# Run a specific test file
python -m pytest tests/test_confidence.py -v

# Run tests matching a pattern
python -m pytest tests/ -k "test_scanner" -v
```

> **Note:** `pytest-asyncio` is configured with `asyncio_mode = auto`. The `test_deployment.py` file is excluded from standard runs as it requires a live Docker environment.

### Test Categories

| Category | Files | Coverage Area |
|---|---|---|
| Scanner & Indicators | 10 | Scanner loop, data fetcher, indicators, SMC, MTF |
| Channels & Strategies | 5 | All 5 channel strategies, free channel, fast path |
| Confidence Scoring | 5 | Confidence, calibration, decay, signal quality |
| Backtesting | 6 | Backtester, integration, simulator, order flow |
| Trade Monitoring | 4 | Trade monitor, observer, DCA, circuit breaker |
| AI & Predictive | 4 | AI engine, predictive AI, OpenAI evaluator |
| Regime & Filtering | 8 | Regime classification, filters, common gates |
| Signal Management | 8 | Signal format, params, quality, router, queue |
| WebSocket & Network | 3 | WebSocket manager, WS optimizer, Redis |
| Performance | 3 | Performance tracker, pair metrics, volatility |
| Specialized | 15+ | Commands, correlation, CVD, spoof detection, etc. |

---

## Troubleshooting

### Engine won't start

1. **Check `.env` is configured** — ensure `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ACTIVE_CHANNEL_ID`, and `TELEGRAM_ADMIN_CHAT_ID` are set.
2. **View logs** — `docker compose logs engine` for error details.
3. **Redis issues** — the engine works without Redis (falls back to in-memory). If Redis won't start, check `docker compose ps`.

### No signals being generated

1. **Check scan status** — send `/status` to the bot to see if the scanner is running.
2. **Check pair count** — send `/pairs` to confirm pairs are loaded.
3. **Check circuit breaker** — send `/breaker` to see if trading is paused.
4. **Low confidence** — signals below the minimum threshold (default 65 %) are suppressed. Use `/suppressed` to see filtered signals.
5. **Market conditions** — during QUIET or low-volatility regimes, signals are naturally suppressed.

### WebSocket disconnections

The engine handles WebSocket drops automatically with exponential-backoff reconnect. Alerts are only sent after 3+ consecutive reconnection failures. Check WS health with `/status`.

### High memory usage

The engine is limited to 1 GB by default in `docker-compose.yml`. For VPS with ≤ 1 GB RAM, reduce `TOP50_FUTURES_COUNT` to 30 or lower.

### Rebuilding from scratch

```bash
sudo bash deploy_vps.sh --clean    # Removes all containers, images, Redis data
```

---

## Contributing

### Development Setup

```bash
git clone https://github.com/mkmk749278/360-v2.git && cd 360-v2
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Code Style

The project uses [Ruff](https://docs.astral.sh/ruff/) for linting (line length: 100, target: Python 3.11) and [mypy](https://mypy.readthedocs.io/) for type checking:

```bash
ruff check src/ config/
mypy src/ config/
```

### Running Tests Before Submitting

```bash
python -m pytest tests/ -x --ignore=tests/test_deployment.py -q
```

### Guidelines

- Follow existing code patterns and module structure.
- Add tests for new features in `tests/` following the `test_<module>.py` convention.
- Keep configuration in `config/__init__.py` and expose via environment variables.
- Use `loguru` for logging (not `print` or stdlib `logging`).
- All async code uses `asyncio` and `aiohttp`.

---

## License

This project does not currently include a license file. All rights are reserved by the repository owner. Contact the maintainer for usage permissions.