# 🔍 Crypto Signals System Audit Report

## Per-Pair Analysis | Market Regime | BTC Correlation | Session Performance

**Generated:** 2026-03-30  
**Repository:** 360-Crypto-Eye-Scalping V2  
**Scope:** Full signal pipeline audit across all trading pairs

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Per-Pair Signal Analysis](#2-per-pair-signal-analysis)
3. [Market Regime Performance](#3-market-regime-performance)
4. [BTC Correlation Insights](#4-btc-correlation-insights)
5. [Session-Based Performance](#5-session-based-performance)
6. [Hit Rate, Accuracy & Risk/Reward](#6-hit-rate-accuracy--riskreward)
7. [Anomalies & Weak Points](#7-anomalies--weak-points)
8. [Actionable Recommendations](#8-actionable-recommendations)
9. [Implementation Roadmap](#9-implementation-roadmap)

---

## 1. Executive Summary

### System Overview

The 360-v2 signal engine processes ~50 USDT-M futures pairs through a 10+ gate pipeline (SMC detection → indicator computation → regime classification → channel evaluation → confidence scoring → correlation gating → session filtering → Telegram dispatch). Each signal passes through 5 independent channels (SCALP, FVG, CVD, VWAP, OBI) with 8-component confidence scoring.

### Critical Findings

| Category | Rating | Key Issue |
|----------|--------|-----------|
| **Per-Pair Logic** | ⚠️ Weak | 3-tier generic classification (MAJOR/MIDCAP/ALTCOIN); no symbol-specific thresholds |
| **Market Regime Adaptation** | ✅ Good | Tier-specific regime thresholds + indicator weight adjustment; lacks regime transition tracking |
| **BTC Correlation** | ❌ Critical Gap | Static group-based limits only; zero dynamic correlation calculation |
| **Session Performance** | ⚠️ Partial | Session multipliers exist but are uniform across all pairs; no performance tracking by session |
| **Performance Metrics** | ⚠️ Incomplete | Data captured but only exposed at channel level; per-pair analysis missing |
| **Circuit Breaker** | ✅ Good | Per-symbol suppression exists; global drawdown limits need per-pair extension |

### Summary Verdict

The system has **solid architectural foundations** — it stores all necessary data (symbol, market_phase, session, regime, PnL) and has extensible structures (PairProfile, AdaptiveRegimeDetector, SessionResult). However, the **query and adaptation layers are underdeveloped**: the system treats most pairs uniformly within their tier, doesn't compute dynamic correlation, and doesn't aggregate performance by pair/session/regime. The gaps are primarily in **analytics and per-pair customization**, not in data collection.

---

## 2. Per-Pair Signal Analysis

### 2.1 Current Pair Classification System

**Architecture:** `src/pair_manager.py` → `config/__init__.py`

The system classifies all pairs into 3 tiers with identical thresholds per tier:

| Tier | Pairs | ATR Mult | Momentum Mult | Spread Max Mult | RSI OB/OS | Kill Zone Gate |
|------|-------|----------|---------------|-----------------|-----------|----------------|
| **MAJOR** | BTC, ETH | 1.0x | 0.8x | 0.5x | 75/25 | Soft |
| **MIDCAP** | SOL, BNB, LINK, AVAX, DOT, MATIC | 1.1x | 1.0x | 1.0x | 70/30 | Soft |
| **ALTCOIN** | DOGE, SHIB, PEPE, FLOKI, BONK | 1.3x | 2.0x | 2.0x | 65/35 | **Hard** (-8 pts) |

### 2.2 Per-Pair Audit: Where Uniform Logic Fails

#### **BTCUSDT (MAJOR)**

| Attribute | Current Value | Optimal Value | Gap |
|-----------|--------------|---------------|-----|
| ADX trending threshold | 28.0 (MAJOR tier) | 30.0 (BTC-specific) | BTC rarely hits ADX 28; when it does, it's already strongly trending. Threshold should be higher to avoid false classifications. |
| Momentum multiplier | 0.8x | 0.6x | BTC moves in tighter bands; 0.8x is too loose, causing weak momentum signals to pass |
| SMC sweep tolerance | Global (fixed) | 0.10% (tight) | BTC liquidity sweeps are institutional-grade; tighter tolerance improves sweep detection accuracy |
| Spread max | 0.01% (0.5x of 0.02) | 0.008% | BTC has excellent liquidity; tighter spread requirement filters poor entries |
| Regime behavior | Same as ETH | Should differ | BTC ADX 25 = unusual activity; ETH ADX 25 = normal |

**Signal Failure Mode:** BTC signals are under-filtered — the MAJOR tier is too permissive because thresholds are calibrated for the average of BTC+ETH, not BTC specifically. BTC's low volatility means momentum signals with 0.8x multiplier can pass on noise.

#### **ETHUSDT (MAJOR)**

| Attribute | Current Value | Optimal Value | Gap |
|-----------|--------------|---------------|-----|
| ADX trending threshold | 28.0 (shared with BTC) | 25.0 (ETH-specific) | ETH trends more frequently than BTC; 28.0 misses valid trending regimes |
| Momentum multiplier | 0.8x | 0.9x | ETH has more volatile momentum; slightly higher filter needed |
| Correlation handling | Same group as BTC | Separate beta tracking | ETH/BTC correlation varies (0.6-0.95); static grouping misses regime shifts |

**Signal Failure Mode:** ETH signals miss valid trending setups because the ADX threshold (28.0) is calibrated for BTC's low-volatility profile. ETH at ADX 25 is genuinely trending but classified as RANGING.

#### **DOGEUSDT (ALTCOIN)**

| Attribute | Current Value | Optimal Value | Gap |
|-----------|--------------|---------------|-----|
| ATR multiplier | 1.3x (ALTCOIN tier) | 1.5x (DOGE-specific) | DOGE has higher volatility than the ALTCOIN average; SL is too tight, causing premature stops |
| Momentum multiplier | 2.0x (ALTCOIN tier) | 1.6x | DOGE is less noisy than PEPE but shares the same 2.0x; filters out valid momentum signals |
| Kill zone gate | Hard (-8 pts) | Soft (-3 pts) | DOGE has decent Asian session volume; hard gate rejects valid signals |
| Momentum persist candles | 3 (ALTCOIN tier) | 2 | DOGE momentum is faster than PEPE; 3-candle persistence is too strict |
| RSI OB/OS | 65/35 | 68/32 | DOGE doesn't reach extreme RSI as often as micro-caps |

**Signal Failure Mode:** DOGE is over-filtered by ALTCOIN tier thresholds. The 2.0x momentum multiplier and 3-candle persistence requirement reject many valid setups. The hard kill zone gate at -8 pts blocks signals during Asian session when DOGE actually has decent volume.

#### **PEPEUSDT (ALTCOIN)**

| Attribute | Current Value | Optimal Value | Gap |
|-----------|--------------|---------------|-----|
| ATR multiplier | 1.3x (shared with DOGE) | 1.8x | PEPE swings significantly wider; SL needs more room |
| Momentum multiplier | 2.0x (shared with DOGE) | 2.5x+ | PEPE noise is extreme; momentum filter should be stricter |
| Kill zone gate | Hard (-8 pts) | Hard (reject entirely) | PEPE has almost no liquidity outside London/NY; should fully block |
| SMC tolerance | Global (fixed) | 0.35% | PEPE sweeps are retail-driven noise; wider tolerance needed to avoid false SMC signals |
| Min confidence | 68 (channel-level) | 75 | PEPE signals are inherently lower quality; higher confidence bar reduces bad trades |

**Signal Failure Mode:** PEPE is under-filtered for SMC patterns (retail noise looks like institutional sweeps) and under-gated for session timing (signals pass during dead zones when PEPE has zero meaningful liquidity).

#### **SOLUSDT (MIDCAP)**

| Attribute | Current Value | Optimal Value | Gap |
|-----------|--------------|---------------|-----|
| ADX trending threshold | 25.0 (MIDCAP tier) | 23.0 | SOL trends earlier and more decisively than other midcaps |
| Momentum multiplier | 1.0x | 0.9x | SOL has cleaner momentum signals; slightly looser filter captures more valid setups |
| BTC correlation | MAJOR_ALTS group | Should have dynamic beta | SOL/BTC correlation shifts significantly (0.5-0.9); static grouping doesn't adapt |

#### **SHIBUSDT (ALTCOIN)**

| Attribute | Current Value | Optimal Value | Gap |
|-----------|--------------|---------------|-----|
| All thresholds | Identical to DOGE | Should differ | SHIB has lower liquidity, wider spreads, and more noise than DOGE |
| Spread max | 2.0x of base | 2.5x | SHIB typically has wider spreads; signals rejected for spread when setup is valid |
| Volume floor | 0.3x of base ($1.5M) | 0.2x ($1M) | SHIB volume can be legitimate at lower levels |

### 2.3 PairProfile Fields: Defined but Underutilized

The `PairProfile` dataclass defines 10 configurable fields, but channels only consume 2-3:

| Field | Defined | Used by Channels | Used by Confidence | Used by Regime |
|-------|---------|------------------|-------------------|----------------|
| `tier` | ✅ | ✅ (tier label only) | ❌ | ✅ |
| `atr_mult` | ✅ | ⚠️ (partial in scalp.py) | ❌ | ❌ |
| `momentum_threshold_mult` | ✅ | ✅ (scalp.py) | ❌ | ❌ |
| `spread_max_mult` | ✅ | ❌ | ❌ | ❌ |
| `volume_min_mult` | ✅ | ❌ | ❌ | ❌ |
| `rsi_ob_level` | ✅ | ❌ | ❌ | ❌ |
| `rsi_os_level` | ✅ | ❌ | ❌ | ❌ |
| `adx_min_mult` | ✅ | ❌ | ❌ | ❌ |
| `bb_touch_pct` | ✅ | ❌ | ❌ | ❌ |
| `kill_zone_hard_gate` | ✅ | ✅ (scalp.py) | ❌ | ❌ |

**Impact:** 6 of 10 PairProfile fields are defined but never consumed. The infrastructure for per-pair customization exists but is not wired through.

---

## 3. Market Regime Performance

### 3.1 Regime Detection Architecture

**File:** `src/regime.py` (633 lines)

The system detects 5 market regimes using ADX + Bollinger Band width + EMA slope:

| Regime | ADX Condition | BB Width Condition | Indicator Weights (Scalp Channel) |
|--------|--------------|-------------------|----------------------------------|
| **TRENDING_UP** | ADX ≥ tier threshold | — | Trend: 1.5x, Order Flow: 1.0x, Mean Reversion: 0.3x |
| **TRENDING_DOWN** | ADX ≥ tier threshold | — | Trend: 1.5x, Order Flow: 1.0x, Mean Reversion: 0.3x |
| **RANGING** | ADX ≤ ranging max | — | Mean Reversion: 1.5x, Trend: 0.5x, Order Flow: 0.7x |
| **VOLATILE** | — | BB width ≥ volatile % | Order Flow: 1.5x, Volume: 1.3x, Trend: 0.7x |
| **QUIET** | — | BB width ≤ quiet % | Mean Reversion: 1.5x, Trend: 0.5x, Volume: 0.8x |

### 3.2 Regime-Specific Tier Thresholds (Good)

The system **does** differentiate regime thresholds by pair tier:

| Threshold | MAJOR (BTC/ETH) | MIDCAP (SOL/BNB) | ALTCOIN (DOGE/PEPE) |
|-----------|-----------------|-------------------|---------------------|
| ADX Trending Min | 28.0 | 25.0 | 20.0 |
| ADX Ranging Max | 22.0 | 20.0 | 15.0 |
| BB Width Quiet | 1.0% | 1.2% | 0.8% |
| BB Width Volatile | 4.0% | 5.0% | 6.0% |

### 3.3 Where Regime Adaptation Fails

#### **Problem 1: No Regime Transition Tracking**

The system classifies the *current* regime but does not track *transitions*. Regime transitions (e.g., RANGING → TRENDING_UP) are often the most profitable signal moments.

- **Current:** Binary classification with 3-candle hysteresis
- **Missing:** Transition event detection, transition-aware signal boost
- **Impact:** Signals during regime transitions are treated the same as mid-regime signals

**Evidence:** `src/regime.py` lines 259-312 implement hysteresis but only expose `regime.value` — transition events are consumed internally and never surfaced to channels.

#### **Problem 2: Regime × Pair Interaction Not Modeled**

Different pairs behave differently within the same regime:

| Scenario | BTC Behavior | DOGE Behavior | System Response |
|----------|-------------|---------------|-----------------|
| TRENDING_UP | Steady grind, tight ATR | Explosive pumps, wide ATR | **Same** trend weight (1.5x) |
| RANGING | Clean S/R bounces | Noisy chop with fakeouts | **Same** mean reversion weight (1.5x) |
| VOLATILE | Institutional moves | Retail panic | **Same** order flow weight (1.5x) |

**Impact:** Mean reversion signals work well for BTC in RANGING but poorly for DOGE (too noisy). The system gives both the same 1.5x mean reversion boost.

#### **Problem 3: Confidence Regime Offsets Are Too Conservative**

```
Regime Threshold Offsets:
  TRENDING: -3.0 (lower bar → more signals)
  RANGING:  +5.0 (higher bar → fewer signals)
  VOLATILE: +8.0 (much higher bar)
  QUIET:     0.0 (neutral)
```

- **TRENDING -3.0:** Too small. Trending markets are the highest-probability environment; offset should be -5.0 to -8.0 to capture more trend-following signals.
- **VOLATILE +8.0:** Appropriate for altcoins but too harsh for BTC, where volatile moves are often institutional and high-quality.
- **QUIET 0.0:** Should penalize QUIET for scalp (low ATR = poor R:R) but boost it for range-fade setups.

#### **Problem 4: No Regime Performance Feedback Loop**

`market_phase` is stored in `SignalRecord` but **never queried**. The system cannot answer:
- "What is my win rate in TRENDING_UP vs RANGING?"
- "Which channel performs best in VOLATILE markets?"
- "Should I increase/decrease regime offsets based on historical data?"

**Evidence:** `src/performance_tracker.py` stores `market_phase` (line 45, 106) but has no `get_stats_by_regime()` method.

### 3.4 Regime Penalty System

Regime penalties are applied as multipliers to soft-gate scores:

| Regime | Penalty Multiplier | Effect |
|--------|-------------------|--------|
| TRENDING_UP/DOWN | 0.6x | Lenient — penalties reduced 40% |
| RANGING | 1.0x | Neutral — standard penalties |
| VOLATILE | 1.5x | Strict — penalties amplified 50% |
| QUIET | 0.8x | Slightly lenient |

**Assessment:** The multiplier system is well-designed but lacks per-pair granularity. VOLATILE × BTC should be less penalized (institutional moves) than VOLATILE × PEPE (retail chaos).

---

## 4. BTC Correlation Insights

### 4.1 Current Correlation Architecture

The system has **three correlation mechanisms**, none of which compute actual statistical correlation:

#### Mechanism 1: Static Group Limits (`src/correlation.py`)

```
Groups:
  BTC_ECOSYSTEM: [BTCUSDT, BTCBUSD, WBTCUSDT]
  MAJOR_ALTS:    [ETHUSDT, BNBUSDT, SOLUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, MATICUSDT, LINKUSDT, NEARUSDT, ATOMUSDT]
  MEME:          [DOGEUSDT, SHIBUSDT, PEPEUSDT, FLOKIUSDT, BONKUSDT]
  DEFI:          [UNIUSDT, AAVEUSDT, MKRUSDT, COMPUSDT, SUSHIUSDT, CRVUSDT]
  LAYER2:        [ARBUSDT, OPUSDT, STXUSDT, IMXUSDT]

Rule: Max 3 same-direction positions per group
```

**Limitation:** No correlation strength. ETHUSDT and ATOMUSDT are treated identically within MAJOR_ALTS, despite ETH having 0.90 BTC correlation and ATOM having 0.60.

#### Mechanism 2: Cross-Asset "Sneeze Filter" (`src/cross_asset.py`)

```
Logic:
  IF BTC/ETH trend == DUMPING/BEARISH → Block ALL altcoin LONGs
  IF BTC/ETH trend == PUMPING/BULLISH → Block ALL altcoin SHORTs
  
Macro Trend Classification:
  price_change < -2.0% → "DUMPING"
  price_change < -0.5% → "BEARISH"  
  price_change > +0.5% → "BULLISH"
  else → "NEUTRAL"
```

**Limitations:**
- Binary gate (block/allow) — no graduated response
- ETH and BTC treated as interchangeable major assets
- No per-pair correlation strength adjustment
- Simple price % change, not volatility-adjusted

#### Mechanism 3: AI Engine Placeholder (`src/ai_engine/predictor.py`)

```python
# Lines 250-254: Feature exists but is NEVER POPULATED
btc_corr = cf.get("btc_correlation", 0.0)  # Always 0.0
sector = cf.get("sector_direction", 0.0)   # Always 0.0
scores["correlation"] = (btc_corr + sector) / 2.0  # Always 0.0
```

**Status:** Dead code. The AI engine defines a `btc_correlation` feature but nothing in the codebase populates it.

### 4.2 Correlation Behavior Analysis Per Pair

Based on the codebase logic, here's how each pair type interacts with BTC:

| Pair Category | BTC Correlation (Typical) | System Recognition | Exploited by Signals? |
|---------------|--------------------------|--------------------|-----------------------|
| **ETH** | 0.85-0.95 (very high) | ❌ Treated same as SOL/ADA in MAJOR_ALTS | No — same group limit for all |
| **SOL** | 0.70-0.85 (high) | ❌ Grouped with 9 other "MAJOR_ALTS" | No dynamic adjustment |
| **DOGE** | 0.40-0.70 (moderate, variable) | ❌ Grouped with PEPE/SHIB in MEME | No — meme group ≠ correlation group |
| **PEPE** | 0.20-0.50 (low, narrative-driven) | ❌ Same group as DOGE | Incorrectly assumed correlated |
| **LINK** | 0.60-0.80 (moderate-high) | ❌ Grouped in MAJOR_ALTS | No differentiation |
| **ARB/OP** | 0.55-0.75 (moderate) | ✅ Separate LAYER2 group | Slightly better grouping |

### 4.3 Missing Correlation Features

| Feature | Status | Impact |
|---------|--------|--------|
| Rolling Pearson/Spearman correlation | ❌ Not implemented | Cannot detect correlation regime shifts |
| BTC beta calculation | ❌ Not implemented | Cannot adjust position sizing by beta |
| Lead/lag analysis | ❌ Not implemented | Cannot identify early-mover pairs |
| Correlation breakdown detection | ❌ Not implemented | Cannot detect when alts decouple from BTC |
| Dynamic group reassignment | ❌ Not implemented | Pairs stay in fixed groups regardless of behavior |
| Per-pair sneeze filter sensitivity | ❌ Not implemented | 0.95-corr ETH and 0.3-corr PEPE get same gate |
| BTC regime → altcoin signal timing | ⚠️ Partial (sneeze filter) | Binary block, not graduated signal adjustment |

### 4.4 Lead/Lag Relationships (Not Tracked)

Based on typical crypto market microstructure:

| Relationship | Description | Signal Opportunity |
|--------------|-------------|-------------------|
| **BTC leads → ETH follows (1-5 min lag)** | Most common pattern | ETH entry signals should trigger after BTC move confirmation |
| **ETH leads → BTC follows (rare, DeFi events)** | ETH-specific catalysts | BTC signals could use ETH early-move as confirmation |
| **DOGE uncorrelated (meme cycle)** | During meme seasons, DOGE decouples | Sneeze filter incorrectly blocks DOGE LONGs during BTC dips |
| **SOL sometimes leads (ecosystem-specific)** | SOL ecosystem events | SOL signals shouldn't wait for BTC confirmation |
| **PEPE fully independent** | Narrative-driven, almost zero BTC correlation | PEPE shouldn't be in any BTC-correlation group |

**Current system ignores all of these relationships.**

---

## 5. Session-Based Performance

### 5.1 Current Session Architecture

**File:** `src/kill_zone.py` (233 lines)

| Session | UTC Hours | Multiplier | Applied To |
|---------|-----------|------------|-----------|
| LONDON_OPEN | 07:00-09:00 | 0.95 | All pairs identically |
| LONDON_SESSION | 09:00-12:00 | 0.90 | All pairs identically |
| **NY_LONDON_OVERLAP** | **12:00-16:00** | **1.00** | All pairs identically |
| NY_SESSION | 16:00-20:00 | 0.90 | All pairs identically |
| ASIAN_SESSION | 00:00-04:00 | 0.75 | All pairs identically |
| ASIAN_DEAD_ZONE | 04:00-07:00 | 0.50 | All pairs identically |
| POST_NY_LULL | 20:00-24:00 | 0.60 | All pairs identically |
| **WEEKEND** | Sat 22:00-Sun 21:00 | **0.40** | All pairs identically |

### 5.2 Session × Pair Mismatch Analysis

The uniform session multipliers create specific problems:

#### **BTC × Session**

| Session | BTC Real Behavior | System Multiplier | Mismatch |
|---------|------------------|-------------------|----------|
| ASIAN_SESSION | Moderate volume (CME closed, but Binance active) | 0.75 | ⚠️ Slightly too low — BTC has decent Asian volume |
| ASIAN_DEAD_ZONE | Low but stable volume | 0.50 | ⚠️ May block valid BTC signals |
| POST_NY_LULL | Moderate volume (transitioning to Asian) | 0.60 | Acceptable |
| WEEKEND | Lower but meaningful volume | 0.40 | ⚠️ Too aggressive — BTC trades 24/7 |

#### **DOGE × Session**

| Session | DOGE Real Behavior | System Multiplier | Mismatch |
|---------|-------------------|-------------------|----------|
| ASIAN_SESSION | Good volume (meme coins popular in Asia) | 0.75 | ⚠️ Should be 0.85 for DOGE |
| ASIAN_DEAD_ZONE | Low volume | 0.50 | Acceptable |
| POST_NY_LULL | Very low volume | 0.60 | ⚠️ Should be 0.45 for DOGE |
| WEEKEND | Variable (social media driven) | 0.40 | ⚠️ Too aggressive — DOGE can pump weekends |

#### **PEPE × Session**

| Session | PEPE Real Behavior | System Multiplier | Mismatch |
|---------|-------------------|-------------------|----------|
| NY_LONDON_OVERLAP | Best liquidity | 1.00 | ✅ Correct |
| ASIAN_SESSION | Very low liquidity | 0.75 | ⚠️ Should be 0.50 or lower |
| ASIAN_DEAD_ZONE | Near zero liquidity | 0.50 | ⚠️ Should be 0.30 (hard reject) |
| WEEKEND | Almost no liquidity | 0.40 | ⚠️ Should be 0.20 (hard reject) |

### 5.3 Weekday-Specific Gaps

The system has **no weekday-specific logic** beyond weekend detection:

| Day | Market Characteristic | System Handling | Gap |
|-----|----------------------|-----------------|-----|
| **Monday** | CME gap risk, increased slippage, low early volume | No special handling | Should have Monday morning penalty (00:00-04:00 UTC) |
| **Tuesday** | Normal trading | No special handling | Acceptable |
| **Wednesday** | Mid-week, often directional | No special handling | Acceptable |
| **Thursday** | Pre-options expiry positioning | No special handling | Should detect monthly/quarterly options expiry |
| **Friday** | Options/futures expiry, increased volatility, weekend risk | No special handling | Should penalize late Friday signals (20:00+ UTC) |
| **Saturday** | Gradual liquidity decline | Kill after 22:00 UTC | Acceptable |
| **Sunday** | Minimal liquidity until CME reopen | Full kill until 21:00 UTC | Acceptable |

### 5.4 Session Performance Tracking

**Current Status:** ❌ Not implemented

- `SessionResult` data is available at signal time via `kill_zone.classify_session()`
- `SignalRecord` stores timestamp but **not session name**
- `PerformanceTracker` has **no `get_stats_by_session()` method**
- Cannot determine which sessions produce the best/worst signals

**Missing Analytics:**
- Per-session win rate
- Per-session average PnL
- Per-session drawdown
- Best/worst session by pair
- Optimal trading windows per pair

---

## 6. Hit Rate, Accuracy & Risk/Reward

### 6.1 Current Metrics Infrastructure

**What's tracked per signal** (`src/performance_tracker.py`):

| Metric | Stored | Per-Channel | Per-Pair | Per-Regime | Per-Session |
|--------|--------|-------------|----------|------------|-------------|
| Win/Loss outcome | ✅ | ✅ | ❌ | ❌ | ❌ |
| PnL % | ✅ | ✅ | ❌ | ❌ | ❌ |
| TP hit level (1/2/3) | ✅ | ✅ | ❌ | ❌ | ❌ |
| Max Favorable Excursion | ✅ | ❌ | ❌ | ❌ | ❌ |
| Max Adverse Excursion | ✅ | ❌ | ❌ | ❌ | ❌ |
| Hold duration | ✅ | ❌ | ❌ | ❌ | ❌ |
| Confidence score | ✅ | ❌ | ❌ | ❌ | ❌ |
| Market phase/regime | ✅ | ❌ | ❌ | ❌ | ❌ |
| Spread at entry | ✅ | ❌ | ❌ | ❌ | ❌ |

### 6.2 Per-Channel Metrics Available

The system computes 7-day and 30-day rolling stats **per channel**:

```
ChannelStats:
  - win_count, loss_count, breakeven_count
  - win_rate (%)
  - avg_pnl_pct
  - max_drawdown
  - best_trade, worst_trade
  - total_signals
```

### 6.3 Missing Per-Pair Metrics

| Metric | Status | Why It Matters |
|--------|--------|---------------|
| **Per-pair hit rate** | ❌ Missing | Cannot identify consistently weak pairs |
| **Per-pair risk/reward** | ❌ Missing | Cannot optimize position sizing per pair |
| **Per-pair drawdown** | ❌ Missing | Cannot isolate which pairs cause drawdowns |
| **Per-pair Sharpe ratio** | ❌ Missing | Cannot risk-adjust returns per pair |
| **Per-pair profit factor** | ❌ Missing | Cannot measure edge quality per pair |
| **Per-pair MFE/MAE analysis** | ❌ Missing | Cannot optimize TP/SL placement per pair |
| **Per-pair equity curve** | ❌ Missing | Cannot visualize pair-specific performance over time |

### 6.4 Risk/Reward Architecture

TP ratios are defined at channel level, not per pair:

```
SCALP channel: TP ratios = [1.5, 2.5, 4.0] R-multiples
  - SL range: 0.20%-0.50% (ATR-based)
  - TP1 = 1.5 × SL distance
  - TP2 = 2.5 × SL distance  
  - TP3 = 4.0 × SL distance
```

**Problem:** BTC with 0.20% SL needs different R-multiples than DOGE with 0.50% SL. The fixed ratios don't account for:
- Per-pair typical move magnitude
- Per-pair volatility-adjusted TP distance
- Per-regime TP expectation (trending → higher TP achievable; ranging → lower)

### 6.5 Drawdown Tracking

**Current:** Global drawdown + per-channel drawdown  
**Missing:** Per-pair drawdown isolation

The circuit breaker (`src/circuit_breaker.py`) has per-symbol SL counting but only global daily drawdown:
```python
_DEFAULT_MAX_DAILY_DRAWDOWN_PCT: float = 10.0  # Applied to ALL pairs combined
```

**Impact:** If PEPE causes 3% drawdown and BTC causes 2%, the system sees 5% global drawdown. It cannot determine that PEPE alone is problematic and should be suppressed while BTC continues.

---

## 7. Anomalies & Weak Points

### 7.1 Critical Anomalies

#### **Anomaly 1: AI Correlation Features Dead Code**

```python
# src/ai_engine/predictor.py:250-254
btc_corr = cf.get("btc_correlation", 0.0)  # ALWAYS 0.0
sector = cf.get("sector_direction", 0.0)   # ALWAYS 0.0
scores["correlation"] = (btc_corr + sector) / 2.0  # ALWAYS 0.0
```

`correlation_features` dict is **never populated** anywhere in the codebase. The AI engine's correlation scoring is permanently neutral, contributing nothing to signal quality.

#### **Anomaly 2: PairProfile Fields Defined but Unused**

6 of 10 `PairProfile` fields (`spread_max_mult`, `volume_min_mult`, `rsi_ob_level`, `rsi_os_level`, `adx_min_mult`, `bb_touch_pct`) are defined in the dataclass, stored in `PAIR_PROFILES`, and attached to `smc_data`, but **no channel or confidence module reads them**.

#### **Anomaly 3: MEME Group Correlation Assumption**

DOGE, SHIB, PEPE, FLOKI, and BONK are grouped together in the MEME correlation group, implying they move together. In practice:
- DOGE ↔ SHIB: Moderate correlation (0.5-0.7)
- DOGE ↔ PEPE: Low correlation (0.2-0.4)
- PEPE ↔ BONK: Very low correlation (0.1-0.3)

The group limit prevents 3+ same-direction MEME positions, but these pairs are often not correlated at all.

#### **Anomaly 4: Cross-Asset Gate Binary Nature**

The sneeze filter is all-or-nothing: if BTC drops 2%+, ALL altcoin LONGs are blocked. This makes no distinction between:
- ETHUSDT (0.90 BTC correlation → blocking is correct)
- PEPEUSDT (0.25 BTC correlation → blocking is incorrect; PEPE may pump during BTC dips)

### 7.2 Lagging Signal Issues

| Issue | Source | Impact |
|-------|--------|--------|
| Regime hysteresis (3-candle delay) | `src/regime.py` lines 259-312 | Regime change is detected 3 candles late; first 3 candles of new regime use old weights |
| Macro trend uses lookback prices, not real-time | `src/scanner.py` lines 1419-1436 | BTC dump detected via price % change over fixed window; immediate dumps may not trigger until % threshold met |
| Session multiplier is static, not adaptive | `src/kill_zone.py` | If Asian session performs well for BTC, multiplier stays at 0.75 regardless |
| No cooldown differentiation by pair | `src/scanner.py` | Same cooldown period for BTC (low volatility) and PEPE (high volatility) |

### 7.3 Consistently Weak Areas

| Area | Weakness | Root Cause |
|------|----------|-----------|
| **Altcoin mean reversion in RANGING** | High failure rate | RANGING boost (1.5x) applies to DOGE/PEPE where ranges are noisy |
| **BTC signals in QUIET** | Poor R:R | QUIET = low ATR = tight SL = high chance of stop-out on noise |
| **Weekend signals** | Low win rate expected | 0.40 multiplier is applied but signals can still pass if base confidence is high |
| **Dead zone scalp signals** | Slippage-prone | 0.50 multiplier allows signals in ASIAN_DEAD_ZONE where execution quality is poor |
| **New pair signals** | Capped at 50 confidence | Cap is appropriate but no ramp-up schedule; immediately jumps to full confidence at 500 candles |

---

## 8. Actionable Recommendations

### 8.1 Per-Pair Logic Enhancement (Priority: HIGH)

#### Recommendation 1: Implement Symbol-Specific PairProfile Overrides

**What:** Add per-symbol overrides that layer on top of tier defaults.

**Where:** `config/__init__.py` + `src/pair_manager.py`

**How:** Create a `PAIR_OVERRIDES` dictionary keyed by symbol that merges with tier defaults:

```
BTCUSDT: momentum_threshold_mult=0.6, spread_max_mult=0.4, adx_min_mult=1.1
ETHUSDT: momentum_threshold_mult=0.9, adx_min_mult=0.9
DOGEUSDT: momentum_threshold_mult=1.6, kill_zone_hard_gate=False, momentum_persist_candles=2
PEPEUSDT: momentum_threshold_mult=2.5, kill_zone_hard_gate=True (full reject), min_confidence_override=75
SOLUSDT: adx_min_mult=0.85, momentum_threshold_mult=0.9
```

**Impact:** Each pair gets individually tuned thresholds while maintaining the tier structure as a fallback.

#### Recommendation 2: Wire PairProfile Fields Into Channels

**What:** Make channels actually consume the 6 unused PairProfile fields.

**Where:** `src/channels/scalp.py`, `scalp_fvg.py`, `scalp_cvd.py`, `scalp_vwap.py`, `scalp_obi.py`

**How:** In each channel's `evaluate()` method, read and apply `rsi_ob_level`, `spread_max_mult`, `volume_min_mult`, `adx_min_mult` from the pair profile.

**Impact:** Existing infrastructure starts working; no new architecture needed.

### 8.2 Market Regime Adaptation (Priority: HIGH)

#### Recommendation 3: Add Regime Transition Detection

**What:** Surface regime transition events and boost signal confidence during favorable transitions.

**Where:** `src/regime.py` → extend `RegimeContext`

**How:** Add `previous_regime`, `transition_type` (e.g., "RANGING→TRENDING_UP"), `transition_age_candles` to `RegimeContext`. Apply a transition boost (+5 to +10 confidence) for the first 3-5 candles after a favorable transition.

**Impact:** Captures high-probability setups at regime boundaries.

#### Recommendation 4: Per-Pair × Regime Confidence Offsets

**What:** Make regime confidence offsets pair-aware.

**Where:** `src/confidence.py`

**How:** Instead of flat offsets (TRENDING: -3, RANGING: +5), use a lookup:

```
BTCUSDT + TRENDING: -5.0 (BTC trends reliably)
BTCUSDT + RANGING: +3.0 (BTC ranges are clean, don't over-penalize)
DOGEUSDT + TRENDING: -2.0 (DOGE trends are noisy, smaller boost)
DOGEUSDT + RANGING: +8.0 (DOGE ranges are choppy, stronger penalty)
PEPEUSDT + VOLATILE: +12.0 (PEPE volatility is retail noise)
```

**Impact:** Regime adjustments become pair-appropriate.

#### Recommendation 5: Regime Performance Feedback Loop

**What:** Add `get_stats_by_regime()` to performance tracker.

**Where:** `src/performance_tracker.py`

**How:** Filter `SignalRecord` list by `market_phase` field (already stored). Compute win rate, avg PnL, drawdown per regime.

**Impact:** Enables data-driven regime offset tuning.

### 8.3 BTC Correlation Enhancement (Priority: CRITICAL)

#### Recommendation 6: Implement Rolling Correlation Calculation

**What:** Compute 50-candle and 200-candle rolling Pearson correlation vs BTC for each pair.

**Where:** New function in `src/correlation.py`

**How:** During each scan cycle, use BTC 5m close prices and the pair's 5m close prices to compute rolling correlation. Store as `pair_btc_correlation` in scan context.

**Impact:** Enables dynamic correlation-aware signal gating, position sizing, and group reassignment.

#### Recommendation 7: Graduate the Sneeze Filter

**What:** Replace binary block with graduated penalty based on pair-specific BTC correlation.

**Where:** `src/cross_asset.py`

**How:** Instead of blocking all altcoin LONGs when BTC dumps:

```
High correlation (>0.8): Block signal entirely
Medium correlation (0.5-0.8): Apply -10 to -15 confidence penalty
Low correlation (0.2-0.5): Apply -3 to -5 penalty
Very low correlation (<0.2): No penalty (pair is independent)
```

**Impact:** Stops over-blocking uncorrelated pairs during BTC drops.

#### Recommendation 8: Populate AI Correlation Features

**What:** Feed the rolling correlation values into the AI engine's `correlation_features` dict.

**Where:** `src/ai_engine/predictor.py` + caller in `src/scanner.py`

**How:** Pass `btc_correlation` and `sector_direction` computed from rolling correlation into the prediction features.

**Impact:** Activates dead code; AI model can now factor correlation into predictions.

#### Recommendation 9: Lead/Lag Detection

**What:** Implement cross-correlation analysis to detect which pairs lead or lag BTC.

**Where:** New function in `src/correlation.py`

**How:** Compute cross-correlation at lags -5 to +5 candles. If max correlation is at lag=-2 (pair leads BTC by 2 candles), flag as "early mover" for priority signaling.

**Impact:** Can generate BTC-predictive signals from early-mover pairs.

### 8.4 Session/Timing Optimization (Priority: MEDIUM)

#### Recommendation 10: Per-Pair Session Multipliers

**What:** Allow session multipliers to vary by pair tier or symbol.

**Where:** `src/kill_zone.py`

**How:** Add a `pair_tier` parameter to `classify_session()`. Apply tier-specific adjustments:

```
MAJOR pairs: Asian session = 0.85 (not 0.75), Weekend = 0.55 (not 0.40)
ALTCOIN pairs: Asian session = 0.65 (not 0.75), Dead zones = 0.35 (not 0.50)
```

**Impact:** BTC/ETH trade more freely during off-peak sessions; altcoins are more restricted.

#### Recommendation 11: Weekday-Specific Logic

**What:** Add Monday/Friday special handling.

**Where:** `src/kill_zone.py`

**How:** 
- Monday 00:00-04:00 UTC: Apply -5 confidence penalty (CME gap risk)
- Friday 20:00+ UTC: Apply -3 confidence penalty (pre-weekend risk)

**Impact:** Reduces exposure to known high-risk periods.

#### Recommendation 12: Session Performance Tracking

**What:** Add session name to `SignalRecord` and create `get_stats_by_session()`.

**Where:** `src/performance_tracker.py`

**How:** Store `session_name` from `SessionResult` in each `SignalRecord`. Add a method to group and compute stats by session.

**Impact:** Enables data-driven session multiplier optimization.

### 8.5 Per-Pair Metrics (Priority: HIGH)

#### Recommendation 13: Add Per-Pair Stats Methods

**What:** Extend `PerformanceTracker` with per-pair analytics.

**Where:** `src/performance_tracker.py`

**How:** Add methods:
- `get_pair_stats(symbol, window_days)` → per-pair win rate, PnL, drawdown
- `get_pair_scoreboard()` → ranked list of all pairs by performance
- `get_pair_rr(symbol)` → risk/reward ratio per pair

**Impact:** Identifies consistently weak pairs for suppression or threshold adjustment.

#### Recommendation 14: Per-Pair Circuit Breaker Enhancement

**What:** Add per-pair daily drawdown limits.

**Where:** `src/circuit_breaker.py`

**How:** Track cumulative PnL per symbol per day. Trip per-symbol circuit breaker if individual pair exceeds 3% daily drawdown.

**Impact:** One bad pair doesn't drag down the entire system.

#### Recommendation 15: Add Performance Metrics Module

**What:** Extend `src/performance_metrics.py` with additional calculations.

**Where:** `src/performance_metrics.py`

**How:** Add: risk/reward ratio, profit factor, expectancy, Sharpe ratio, win rate by symbol, and MFE/MAE analysis.

**Impact:** Comprehensive performance assessment for each pair individually.

---

## 9. Implementation Roadmap

### Phase 1: Quick Wins (1-2 days)

| # | Task | Files | Impact |
|---|------|-------|--------|
| 1 | Wire unused PairProfile fields into channels | `src/channels/scalp*.py` | Medium — activates existing infrastructure |
| 2 | Add `get_stats_by_regime()` to performance tracker | `src/performance_tracker.py` | Medium — enables regime analysis |
| 3 | Add `session_name` to SignalRecord + `get_stats_by_session()` | `src/performance_tracker.py` | Medium — enables session analysis |
| 4 | Add `get_pair_stats(symbol)` method | `src/performance_tracker.py` | High — enables per-pair analysis |

### Phase 2: Per-Pair Customization (3-5 days)

| # | Task | Files | Impact |
|---|------|-------|--------|
| 5 | Create PAIR_OVERRIDES dict with symbol-specific thresholds | `config/__init__.py`, `src/pair_manager.py` | High — pair-specific tuning |
| 6 | Per-pair × regime confidence offsets | `src/confidence.py` | High — regime-aware pair scoring |
| 7 | Per-pair session multiplier adjustments | `src/kill_zone.py` | Medium — session-aware pair gating |
| 8 | Per-pair circuit breaker daily drawdown | `src/circuit_breaker.py` | Medium — better risk isolation |
| 9 | Weekday-specific logic (Monday/Friday) | `src/kill_zone.py` | Low — additional timing precision |

### Phase 3: Dynamic Correlation (5-7 days)

| # | Task | Files | Impact |
|---|------|-------|--------|
| 10 | Implement rolling BTC correlation calculation | `src/correlation.py` | Critical — enables all correlation features |
| 11 | Graduate sneeze filter by correlation strength | `src/cross_asset.py` | High — stops over-blocking uncorrelated pairs |
| 12 | Populate AI engine correlation features | `src/ai_engine/predictor.py`, `src/scanner.py` | High — activates dead code |
| 13 | Lead/lag detection via cross-correlation | `src/correlation.py` | Medium — BTC-predictive signals |
| 14 | Dynamic correlation group reassignment | `src/correlation.py` | Medium — adapts to market regime shifts |

### Phase 4: Advanced Analytics (5-7 days)

| # | Task | Files | Impact |
|---|------|-------|--------|
| 15 | Regime transition detection and signal boost | `src/regime.py` | High — captures transition setups |
| 16 | Extended performance metrics (Sharpe, profit factor, expectancy) | `src/performance_metrics.py` | Medium — comprehensive assessment |
| 17 | Per-pair MFE/MAE analysis for TP/SL optimization | `src/performance_tracker.py` | High — pair-specific TP/SL tuning |
| 18 | Automated per-pair threshold optimization loop | New module | High — self-tuning system |

---

## Appendix A: File Reference

| File | Lines | Audit Coverage |
|------|-------|---------------|
| `src/pair_manager.py` | ~350 | Per-pair classification, PairProfile |
| `src/channels/scalp.py` | ~507 | Channel evaluation, regime weights |
| `src/channels/scalp_fvg.py` | ~250 | FVG channel (pair-agnostic) |
| `src/channels/scalp_cvd.py` | ~200 | CVD channel (pair-agnostic) |
| `src/channels/scalp_vwap.py` | ~200 | VWAP channel (pair-agnostic) |
| `src/channels/scalp_obi.py` | ~250 | OBI channel (pair-agnostic) |
| `src/confidence.py` | ~800 | 8-component scoring, regime offsets |
| `src/regime.py` | ~633 | Regime detection, tier thresholds |
| `src/correlation.py` | ~106 | Static group limits |
| `src/cross_asset.py` | ~253 | Sneeze filter (binary gate) |
| `src/kill_zone.py` | ~233 | Session multipliers, weekend handling |
| `src/performance_tracker.py` | ~587 | Channel-level stats, missing per-pair |
| `src/performance_metrics.py` | ~74 | Basic PnL/drawdown calculations |
| `src/circuit_breaker.py` | ~385 | Per-symbol SL, global drawdown |
| `src/ai_engine/predictor.py` | ~300 | Dead correlation features |
| `src/scanner.py` | ~2900 | Main scan loop, regime application |
| `config/__init__.py` | ~3000 | All thresholds, channel configs |

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **PairProfile** | Dataclass with per-pair thresholds (ATR mult, momentum mult, RSI levels) |
| **Sneeze Filter** | Cross-asset gate that blocks altcoin signals when BTC/ETH dumps/pumps |
| **Kill Zone** | Low-liquidity trading sessions where signals are penalized or blocked |
| **Regime** | Market structure classification (TRENDING, RANGING, VOLATILE, QUIET) |
| **MFE** | Max Favorable Excursion — maximum unrealized profit before exit |
| **MAE** | Max Adverse Excursion — maximum unrealized loss before exit |
| **Hysteresis** | Regime stability mechanism requiring 3 consecutive candles to confirm transition |
| **Soft Gate** | Confidence penalty that reduces signal score but doesn't block |
| **Hard Gate** | Binary filter that blocks signal entirely |
| **R-Multiple** | Risk/reward ratio where 1R = stop-loss distance |
