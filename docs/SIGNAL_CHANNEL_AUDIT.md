# Signal Channel Audit Report

**Date:** 2026-04-01  
**Scope:** All 9 scalp channels in `src/channels/`  
**Objective:** Verify signal reliability, assess quality, identify dependencies, and highlight edge cases.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Channel-by-Channel Audit](#2-channel-by-channel-audit)
   - [ScalpChannel (LIQUIDITY_SWEEP_REVERSAL / RANGE_FADE / WHALE_MOMENTUM)](#21-scalpchannel)
   - [ScalpFVGChannel (FVG_RETEST)](#22-scalpfvgchannel)
   - [ScalpCVDChannel (CVD_DIVERGENCE)](#23-scalpcvdchannel)
   - [ScalpDivergenceChannel (RSI_MACD_DIVERGENCE)](#24-scalpdivergencechannel)
   - [ScalpSupertrendChannel (SUPERTREND_FLIP)](#25-scalpsupertrendchannel)
   - [ScalpIchimokuChannel (ICHIMOKU_TK_CROSS)](#26-scalpichimokuchannel)
   - [ScalpOrderblockChannel (SMC_ORDERBLOCK)](#27-scalporderblockchannel)
   - [ScalpOBIChannel (OBI_ABSORPTION)](#28-scalpobichannel)
   - [ScalpVWAPChannel (VWAP_BOUNCE)](#29-scalpvwapchannel)
3. [Cross-Channel Dependency Map](#3-cross-channel-dependency-map)
4. [Bottlenecks and Edge Cases](#4-bottlenecks-and-edge-cases)
5. [Test Coverage Assessment](#5-test-coverage-assessment)
6. [Recommendations](#6-recommendations)

---

## 1. Architecture Overview

### Signal Pipeline

```
Scanner (_scan_symbol)
  ├─ Build ScanContext (candles, indicators, SMC data, regime)
  ├─ For each channel:
  │    ├─ Cooldown check (skip if symbol+channel in cooldown)
  │    ├─ chan.evaluate() → Signal | None
  │    ├─ _prepare_signal() → 17-stage validation pipeline
  │    │    ├─ Hard gates: setup/regime, execution, MTF confluence, cross-asset
  │    │    ├─ Soft gates: VWAP extension, kill zone, OI, spoofing, clustering
  │    │    ├─ Confidence scoring (component + channel weights + penalties)
  │    │    └─ Tier assignment: A+ (80-100), B (65-79), WATCHLIST (50-64), FILTERED (<50)
  │    └─ _enqueue_signal() → set cooldown
  └─ Return all qualifying signals
```

### Channel Registration (src/main.py)

| # | Channel Class | Setup Classes | Signal Prefix | Config Name |
|---|---------------|---------------|---------------|-------------|
| 1 | ScalpChannel | LIQUIDITY_SWEEP_REVERSAL, RANGE_FADE, WHALE_MOMENTUM | SSCL- | 360_SCALP |
| 2 | ScalpFVGChannel | FVG_RETEST | SFVG- | 360_SCALP_FVG |
| 3 | ScalpCVDChannel | CVD_DIVERGENCE | SCVD- | 360_SCALP_CVD |
| 4 | ScalpVWAPChannel | VWAP_BOUNCE | SVWP- | 360_SCALP_VWAP |
| 5 | ScalpOBIChannel | OBI_ABSORPTION | SOBI- | 360_SCALP_OBI |
| 6 | ScalpDivergenceChannel | RSI_MACD_DIVERGENCE | SDIV- | 360_SCALP_DIVERGENCE |
| 7 | ScalpSupertrendChannel | SUPERTREND_FLIP | SSTR- | 360_SCALP_SUPERTREND |
| 8 | ScalpIchimokuChannel | ICHIMOKU_TK_CROSS | SICH- | 360_SCALP_ICHIMOKU |
| 9 | ScalpOrderblockChannel | SMC_ORDERBLOCK | SORB- | 360_SCALP_ORDERBLOCK |

### Shared Configuration

| Parameter | SCALP | FVG | CVD | VWAP | OBI | DIV | ST | ICH | OB |
|-----------|-------|-----|-----|------|-----|-----|----|----|-----|
| sl_pct_range | 0.20–0.50 | 0.10–0.20 | 0.15–0.30 | 0.10–0.20 | 0.10–0.20 | 0.15–0.30 | 0.15–0.30 | 0.15–0.30 | 0.15–0.30 |
| tp_ratios | 1.5/2.5/4.0 | 1.5/2.5/3.0 | 1.5/2.5/3.5 | 1.5/2.5/3.5 | 1.0/1.5/2.0 | 1.5/2.5/3.5 | 1.5/2.5/3.5 | 1.5/2.5/3.0 | 1.5/2.5/3.0 |
| adx_min/max | 15/100 | 15/100 | 15/100 | 0/25 | varies | 15/100 | 15/100 | 15/100 | 15/100 |
| spread_max | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 |
| min_volume | 5M | 5M | 5M | 5M | 5M | 5M | 5M | 5M | 5M |
| dca_enabled | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |

---

## 2. Channel-by-Channel Audit

### 2.1 ScalpChannel

**File:** `src/channels/scalp.py` (549 lines)  
**Sub-paths:** 3 independent evaluators, winner selected by regime-weighted R-multiple.

#### 2.1.1 LIQUIDITY_SWEEP_REVERSAL

| Aspect | Details |
|--------|---------|
| **Trigger** | SMC liquidity sweeps detected in `smc_data["sweeps"]` |
| **Direction** | Determined by sweep direction (buy sweep → LONG, sell sweep → SHORT) |
| **Confirmations** | EMA9/21 alignment, momentum persistence (≥2 candles), MACD histogram, 1h MTF gate |
| **ADX Gate** | Must pass `config.adx_min` (≥15) |
| **RSI Gate** | Pair-adjusted OB/OS levels via `check_rsi()` |
| **SL** | `max(close × sl_pct_range[0]/100, ATR × 0.5)` from close |
| **Timeframe** | 5m primary |
| **ATR Fallback** | `close × 0.001` (0.1%) |

**Signal Quality Assessment:** ✅ Strong  
- Full SMC confluence (sweep + MSS + FVG overlap possible)
- Momentum persistence filter prevents whipsaw entries
- ATR-adaptive momentum threshold (`0.10–0.30%` range) adjusts well to volatility
- 1h MTF gate provides multi-timeframe confirmation

**Potential Edge Cases:**
- ⚠️ Sweep detection depends entirely on upstream `smc_data["sweeps"]` — if detector misses a sweep, channel is silent
- ⚠️ Momentum persistence defaults to 2 candles when no `pair_profile`; may be too loose for high-volatility altcoins
- ⚠️ `momentum_array` check silently skipped if `None` — signal can pass without persistence validation

#### 2.1.2 RANGE_FADE

| Aspect | Details |
|--------|---------|
| **Trigger** | Price touches Bollinger Band boundary (±BB touch tolerance) |
| **Direction** | Touch lower BB → LONG, touch upper BB → SHORT |
| **Regime Gate** | ADX ceiling: RANGING/QUIET=25, TRENDING=18, default=22; ADX floor: 6–8 |
| **BB Guards** | Width expansion >10% → reject; Squeeze <0.3% → reject |
| **Confirmations** | RSI threshold, MACD strict mode, 15m RSI MTF gate, 1h EMA trend alignment |
| **SL** | Dynamic based on ATR (fallback `close × 0.002`) |
| **Timeframe** | 5m primary |

**Signal Quality Assessment:** ✅ Strong  
- Multi-layer filtering prevents false mean-reversion signals
- BB squeeze guard prevents entries before breakout
- BB expansion guard avoids fading into expanding volatility
- 1h EMA rejection (±0.05%) prevents fading strong HTF trends
- MACD confirmation in strict mode adds quality

**Potential Edge Cases:**
- ⚠️ `bb_touch_pct` defaults to `0.002` (0.2%) without `pair_profile` — tight for large-cap majors with thin bands
- ⚠️ Only first condition match (LONG or SHORT) is evaluated; simultaneous BB touches (extreme squeeze) would pick LONG
- ⚠️ MACD strict mode may reject valid BB touch setups during quiet markets with flat MACD histograms

#### 2.1.3 WHALE_MOMENTUM

| Aspect | Details |
|--------|---------|
| **Trigger** | `smc_data["whale_alert"]` OR `smc_data["volume_delta_spike"]` |
| **Direction** | Buy volume ≥2× sell volume → LONG; sell ≥2× buy → SHORT |
| **Volume Gate** | Total recent tick volume ≥ $500K USD |
| **OBI Gate** | Bid/ask depth imbalance ≥1.5× (from live order book) |
| **Confirmations** | RSI regime check (1m timeframe) |
| **SL** | ATR-based (1m ATR, fallback `close × 0.002`) |
| **TP Ratios** | Compressed: 0.3R, 0.7R, 1.0R (quick exits) |
| **Timeframe** | 1m primary |

**Signal Quality Assessment:** ⚠️ Moderate  
- **No ADX check** — can fire in any regime regardless of trend strength
- **No EMA alignment** — purely order-flow driven
- **No MTF gate** — no higher-timeframe confirmation
- OBI check optional (skipped if `order_book` is `None`)
- Relies heavily on real-time data quality (`recent_ticks`, `order_book`)

**Potential Edge Cases:**
- ⚠️ If `recent_ticks` is empty or stale, `buy_vol` and `sell_vol` both = 0, fails the $500K gate (fail-safe)
- ⚠️ OBI check is soft — if `order_book` is `None`, the check is skipped entirely, weakening signal quality
- ⚠️ `isBuyerMaker` field interpretation: `True` = sell aggressor, `False` = buy aggressor — potential confusion in data providers

---

### 2.2 ScalpFVGChannel

**File:** `src/channels/scalp_fvg.py` (263 lines)  
**Setup Class:** `FVG_RETEST`

| Aspect | Details |
|--------|---------|
| **Trigger** | Price retests a detected Fair Value Gap zone from `smc_data["fvg"]` |
| **Direction** | Bullish FVG (gap-up) → LONG on retest; Bearish FVG (gap-down) → SHORT |
| **Zone Filters** | Max age: 80 candles; Fill >60% → reject; Proximity threshold: 35% of zone width |
| **Confirmations** | ADX ≥15, RSI pair-adjusted levels |
| **SL** | `min(gap_boundary - ATR×0.5, close × sl_pct_range[0]/100)` with age decay |
| **Age Decay** | `max(0.2, 1.0 - candles_ago/100)` applied to SL distance |
| **HTF Confluence** | Boosts to `A+` tier if 15m FVG overlaps 5m zone |
| **Timeframe** | 5m primary, 15m fallback |
| **ATR Fallback** | `close × 0.002` (0.2%) |

**Signal Quality Assessment:** ✅ Strong  
- **Works without sweeps** (independent FVG detection) as stated in the problem
- Zone fill check prevents trading into already-consumed zones
- Age decay naturally penalizes old zones with tighter SL
- HTF confluence boost provides quality tiering (`A+` for overlapping HTF zones)
- Complete metadata: `analyst_reason` includes zone age and decay factor

**Potential Edge Cases:**
- ⚠️ **First matching zone wins**: Iterates FVG list and `break`s on first match — if multiple zones overlap current price, only the earliest in the list is selected (not necessarily the strongest)
- ⚠️ **Zone age 80-candle cutoff**: Hard cutoff — a 79-candle-old zone passes, 81 is rejected. Institutional FVG zones can remain valid longer
- ⚠️ **Fill percentage calculation**: If zone is 59% filled, it passes; at 61% it's rejected — sharp cliff with no gradual penalty

---

### 2.3 ScalpCVDChannel

**File:** `src/channels/scalp_cvd.py` (176 lines)  
**Setup Class:** `CVD_DIVERGENCE`

| Aspect | Details |
|--------|---------|
| **Trigger** | CVD divergence detected in `smc_data["cvd_divergence"]` ("BULLISH" or "BEARISH") |
| **Direction** | Bullish CVD divergence → LONG near support; Bearish → SHORT near resistance |
| **Metadata Gates** | Age ≤10 candles, Strength ≥0.3 (both enforced when `_CVD_REQUIRE_METADATA=True`) |
| **ADX Gate** | Hard reject if ADX >35 (divergences unreliable in strong trends) |
| **S/R Proximity** | Price within 1×ATR of recent high/low (or 0.8% without ATR) |
| **Confirmations** | RSI pair-adjusted levels |
| **SL** | `max(close × sl_pct_range[0]/100, ATR × 0.8)` |
| **Timeframe** | 5m only |
| **ATR Fallback** | `close × 0.002` (0.2%) |

**Signal Quality Assessment:** ✅ Strong  
- **Full metadata with `_CVD_REQUIRE_METADATA=True`**: age and strength fields are mandatory
- Fail-closed design: missing metadata → signal rejected (not silently passed)
- ADX ≤35 gate correctly filters divergences that would fail in strong trends
- S/R proximity check ensures entry is near a structural level

**Potential Edge Cases:**
- ⚠️ **ATR-based proximity (1.0× ATR)** is generous — price can be 1 full ATR away from recent low and still qualify
- ⚠️ **Percentage fallback (0.8%)** is tight for low-volatility assets — a $40,000 BTC would need to be within $320 of recent support
- ⚠️ **No analyst_reason field populated** — unlike FVG channel, CVD signals lack descriptive reason text

---

### 2.4 ScalpDivergenceChannel

**File:** `src/channels/scalp_divergence.py` (223 lines)  
**Setup Class:** `RSI_MACD_DIVERGENCE`

| Aspect | Details |
|--------|---------|
| **Trigger** | RSI divergence detected via local swing analysis (20-candle lookback) |
| **Types** | Regular Bullish/Bearish (reversal), Hidden Bullish/Bearish (continuation) |
| **MACD Boost** | Optional MACD histogram divergence confirmation (tagged "+MACD" in reason) |
| **ADX Gate** | Hard reject if ADX ≥40 |
| **RSI Gate** | LONG: RSI < 75; SHORT: RSI > 25 |
| **Min Candles** | 30 (20 lookback + 10 buffer) |
| **SL** | `max(close × 0.15%/100, ATR × 0.8)` |
| **Timeframe** | 5m only |

**Signal Quality Assessment:** ⚠️ Moderate  
- Self-contained divergence detection (no external SMC dependency)
- 4 divergence types provide comprehensive coverage
- MACD confirmation is soft (boost, not requirement) — appropriate for thin MACD histograms
- RSI NaN values replaced with 50.0 — safe default but could mask data issues

**Potential Edge Cases:**
- ⚠️ **NaN replacement with 50.0**: If RSI array contains NaN values (insufficient data), they're replaced with 50.0 — this creates a flat baseline that could produce false divergence signals (e.g., NaN→50 followed by real value may look like a swing)
- ⚠️ **Local extrema detection (window=3)**: Requires 3-candle symmetry around a swing point — fast V-shaped reversals (1-2 candles) are missed
- ⚠️ **Minimum 2 swing points required**: New trading sessions with limited history may not have enough swings
- ⚠️ **Priority ordering**: Regular divergences checked before hidden — if both exist simultaneously, regular wins (which may not be the stronger signal)
- ⚠️ **No MTF gate**: No higher-timeframe confirmation unlike the main ScalpChannel

---

### 2.5 ScalpSupertrendChannel

**File:** `src/channels/scalp_supertrend.py` (179 lines)  
**Setup Class:** `SUPERTREND_FLIP`

| Aspect | Details |
|--------|---------|
| **Trigger** | Supertrend direction flip (bullish↔bearish) |
| **Direction** | DOWN→UP flip → LONG; UP→DOWN flip → SHORT |
| **Confirmations** | EMA9/21 alignment, volume ≥1.3× average (20 bars) |
| **ADX Gate** | Must have ADX ≥15 (need trend strength for meaningful flips) |
| **SL** | At Supertrend line value; floor at `close × 0.10%` |
| **Min Candles** | 55 (Supertrend period=10 + EMA21 + buffer) |
| **Timeframe** | 5m only |

**Signal Quality Assessment:** ✅ Good  
- Supertrend-at-SL is a natural and defensible stop placement
- Volume spike confirmation (1.3×) validates the flip with participation
- EMA alignment prevents counter-trend entries
- Self-contained computation (no external data dependencies beyond candles)

**Potential Edge Cases:**
- ⚠️ **First flip is missed**: Requires both `prev_dir` and `curr_dir` — the very first Supertrend value has no previous direction
- ⚠️ **Volume gate skipped if <21 candles**: If candle count is between 55 (min) and 76 (55+21), volume confirmation may not have enough history, but the gate still runs — edge case depends on implementation
- ⚠️ **EMA crossover zone**: When EMA9 ≈ EMA21, the alignment check becomes noisy — rapid alternation between pass/fail
- ⚠️ **No MTF gate**: No higher-timeframe confirmation

---

### 2.6 ScalpIchimokuChannel

**File:** `src/channels/scalp_ichimoku.py` (197 lines)  
**Setup Class:** `ICHIMOKU_TK_CROSS`

| Aspect | Details |
|--------|---------|
| **Trigger** | Tenkan-sen crosses Kijun-sen (TK cross) |
| **Direction** | Bullish TK cross + price above cloud → LONG; Bearish TK cross + price below cloud → SHORT |
| **Cloud Filter** | Price must be on correct side of Kumo (above for LONG, below for SHORT) |
| **SL** | At Kijun-sen level; floor at `close × 0.10%` |
| **Min Candles** | 80 (Senkou-B period=52 + shift=26 + buffer) |
| **Timeframe** | 5m primary, 15m fallback |

**Signal Quality Assessment:** ✅ Good  
- Classical Ichimoku signal with proper cloud confirmation
- Kijun-sen as SL is structurally meaningful (Ichimoku equilibrium line)
- 5m→15m fallback provides coverage when 5m data is insufficient
- Cloud filter prevents entries inside the cloud (indecision zone)

**Potential Edge Cases:**
- ⚠️ **80-candle minimum is demanding**: On fresh pairs or after data gaps, 80 5m candles = ~7 hours of clean data required
- ⚠️ **Cloud NaN handling**: If Senkou spans are NaN, cloud filter is skipped — signals can pass without cloud confirmation (degraded mode)
- ⚠️ **Cloud squeeze**: When Senkou-A ≈ Senkou-B, cloud_top ≈ cloud_bot — the filter becomes trivially easy to pass (any price slightly above/below passes)
- ⚠️ **No volume confirmation**: Unlike Supertrend, no volume gate — TK crosses without volume participation may be weak
- ⚠️ **No ADX check inside channel**: Relies on upstream config `adx_min=15` via basic filters

---

### 2.7 ScalpOrderblockChannel

**File:** `src/channels/scalp_orderblock.py` (269 lines)  
**Setup Class:** `SMC_ORDERBLOCK`

| Aspect | Details |
|--------|---------|
| **Trigger** | Price enters a fresh (untouched) order block zone |
| **OB Detection** | Impulse candle: body/range ≥60% AND range ≥1.5× ATR; preceding candle = the OB |
| **Direction** | Bullish OB (bearish candle before bullish impulse) → LONG; Bearish OB → SHORT |
| **Freshness** | Only untouched OBs (marked as "touched" after first retest) |
| **SL** | Beyond OB far edge + 0.2× ATR buffer |
| **Lookback** | 50 candles |
| **Timeframe** | 5m only |

**Signal Quality Assessment:** ⚠️ Moderate  
- Self-contained OB detection with proper impulse validation
- "Touched" marking prevents double-dipping on used OBs
- Most recent fresh OB prioritized (reverse iteration)
- SL placement beyond OB boundary with ATR buffer is structurally sound

**Potential Edge Cases:**
- ⚠️ **Strict impulse criteria**: Body ratio ≥60% AND range ≥1.5× ATR — high-quality OBs with smaller body ratios (e.g., dojis with long wicks before impulse) are missed
- ⚠️ **Aggressive touch marking**: OB marked "touched" on ANY retest — a brief wick through the zone invalidates it permanently, even if the zone held
- ⚠️ **SL recomputation issue**: SL is first calculated from OB boundary (line 221/224), then recomputed from close ± sl_dist (line 231-239) — the OB-boundary-based SL is effectively overwritten, losing the structural reference
- ⚠️ **No volume or order book confirmation**: Despite being an "order block" channel, there's no order book data used — purely price-action based
- ⚠️ **No MTF gate**: No higher-timeframe confirmation

---

### 2.8 ScalpOBIChannel

**File:** `src/channels/scalp_obi.py` (233 lines)  
**Setup Class:** `OBI_ABSORPTION`

| Aspect | Details |
|--------|---------|
| **Trigger** | OBI ≥ +0.65 (bid absorption → LONG) or OBI ≤ -0.65 (ask absorption → SHORT) |
| **OBI Calculation** | Exponential depth-weighted: L1=1.0, decay 0.25/level over top 10 levels |
| **Staleness Gate** | Order book must be ≤2 seconds old |
| **Depth Gate** | Top-10 bids + asks ≥ $100K USD |
| **Spoofing Gate** | Layered order pattern detection → reject if detected |
| **S/R Proximity** | Price within 1×ATR of recent high/low (or 0.5% without ATR) |
| **SL** | `max(close × sl_pct_range[0]/100, ATR × 0.5)` — tightest among all channels |
| **ATR Fallback** | `close × 0.001` (0.1%) — tightest fallback |
| **Timeframe** | 5m for candles; real-time for order book |

**Signal Quality Assessment:** ✅ Strong  
- **Real-time order book data** provides unique edge over candle-only channels
- Exponential depth weighting emphasizes near-touch levels (most relevant for immediate execution)
- Spoofing detection gate prevents acting on manipulated order books
- 2-second staleness guard ensures data freshness
- $100K depth minimum filters out illiquid pairs
- Fail-closed timestamp requirement (`_OBI_REQUIRE_TIMESTAMP=True`)

**Potential Edge Cases:**
- ⚠️ **2-second staleness is very strict**: If order book refresh cycle is >2s (e.g., during REST fallback when WebSocket is degraded), all OBI signals are blocked
- ⚠️ **$100K depth threshold**: Excludes many mid-cap and small-cap pairs — may be too restrictive
- ⚠️ **Spoofing detection effectiveness**: Depends on `check_spoof_gate()` implementation — sophisticated spoofing (iceberg orders) may not be caught
- ⚠️ **OBI boundary inclusive**: `obi >= 0.65` means exactly 0.65 passes — fragile boundary at threshold

---

### 2.9 ScalpVWAPChannel

**File:** `src/channels/scalp_vwap.py` (173 lines)  
**Setup Class:** `VWAP_BOUNCE`

| Aspect | Details |
|--------|---------|
| **Trigger** | Price touches VWAP ±1 standard deviation band |
| **Direction** | Touch lower band → LONG; touch upper band → SHORT |
| **Regime Gate** | RANGING or QUIET only (ADX ≤ 25 enforced) |
| **Volume Gate** | Current volume ≥ 1.5× 20-bar average |
| **TP1** | VWAP center (mean-reversion target) |
| **SL** | Beyond ±2SD band + 0.1×SD buffer |
| **VWAP Lookback** | 50 candles |
| **Timeframe** | 5m primary, 15m fallback |

**Signal Quality Assessment:** ✅ Strong  
- **Self-contained VWAP computation** (no external dependency)
- VWAP center as TP1 is a natural mean-reversion target
- ADX ≤ 25 enforcement correctly limits to ranging environments
- Volume confirmation (1.5×) validates institutional participation at band touch
- ±2SD SL with buffer provides statistically grounded stop placement

**Potential Edge Cases:**
- ⚠️ **Band touch vs. band cross**: Only signals on touch (`close ≤ lower_band_1`), not on close above — a candle that briefly wicks below -1SD but closes above will not trigger
- ⚠️ **Volume gate is strict (1.5×)**: In QUIET regimes (where VWAP works best), volume is naturally low — 1.5× average may still be insufficient for conviction
- ⚠️ **No analyst_reason populated**: Signal lacks descriptive text (unlike FVG/OBI channels)
- ⚠️ **ADX check skipped if ADX unavailable**: If `adx_last` is `None`, the defensive check is not applied — degrades to regime-only gating
- ⚠️ **50-candle VWAP lookback**: On 5m = ~4 hours of data; intraday VWAP resets are not modeled

---

## 3. Cross-Channel Dependency Map

### 3.1 No Direct Inter-Channel Dependencies

All 9 channels are evaluated **independently** in sequence. No channel's output affects another channel's evaluation. The scanner iterates channels and each receives the same `ScanContext`.

### 3.2 Shared Data Dependencies

```
                    ┌──────────────────────────────────────────┐
                    │           ScanContext (shared)            │
                    │                                          │
                    │  candles: 1m, 5m, 15m, 1h, 4h           │
                    │  indicators: per-TF ADX/RSI/EMA/MACD/BB │
                    │  smc_data:                               │
                    │    ├─ sweeps ──────── ScalpChannel (LSR) │
                    │    ├─ fvg ────────── ScalpFVGChannel     │
                    │    ├─ cvd_divergence ─ ScalpCVDChannel   │
                    │    ├─ whale_alert ── ScalpChannel (WM)   │
                    │    ├─ order_book ─── ScalpOBIChannel     │
                    │    │                 ScalpChannel (WM)    │
                    │    ├─ recent_ticks ─ ScalpChannel (WM)   │
                    │    └─ pair_profile ─ ALL channels        │
                    │  regime: MarketRegime enum               │
                    │  regime_context: enriched regime data     │
                    └──────────────────────────────────────────┘
```

### 3.3 Indirect Dependencies via Shared State

| Dependency | Mechanism | Affected Channels |
|-----------|-----------|------------------|
| **Cooldown** | `(symbol, channel)` timer after signal enqueue | All — 300s per channel |
| **Cluster Suppression** | Too many same-direction scalp signals → block | All scalp channels |
| **Active Signals** | Opposing position open → confidence penalty | All channels |
| **Signal Router** | Signal queue capacity and processing order | All channels |

### 3.4 Data Source Dependencies

| Channel | Candle TF | Indicator TF | SMC Data | Order Book | Real-Time |
|---------|-----------|-------------|----------|-----------|-----------|
| ScalpChannel (LSR) | 5m | 5m, 1h | sweeps, pair_profile | — | — |
| ScalpChannel (RF) | 5m | 5m, 15m, 1h | pair_profile | — | — |
| ScalpChannel (WM) | 1m | 1m | whale_alert, order_book, recent_ticks | ✅ Live | ✅ Ticks |
| ScalpFVGChannel | 5m/15m | 5m/15m | fvg | — | — |
| ScalpCVDChannel | 5m | 5m | cvd_divergence + metadata | — | — |
| ScalpDivergenceChannel | 5m | 5m | pair_profile | — | — |
| ScalpSupertrendChannel | 5m | 5m | pair_profile | — | — |
| ScalpIchimokuChannel | 5m/15m | 5m/15m | pair_profile | — | — |
| ScalpOrderblockChannel | 5m | 5m | pair_profile | — | — |
| ScalpOBIChannel | 5m | 5m | order_book, pair_profile | ✅ Live | ✅ 2s max |
| ScalpVWAPChannel | 5m/15m | 5m/15m | pair_profile | — | — |

---

## 4. Bottlenecks and Edge Cases

### 4.1 Data Availability Bottlenecks

| Bottleneck | Impact | Channels Affected |
|-----------|--------|------------------|
| **WebSocket degradation** | Order book stale >2s → all OBI signals blocked | ScalpOBIChannel |
| **WebSocket degradation** | No `recent_ticks` → whale momentum disabled | ScalpChannel (WM) |
| **Insufficient candle history** | <80 candles on 5m → Ichimoku disabled entirely | ScalpIchimokuChannel |
| **Insufficient candle history** | <55 candles on 5m → Supertrend disabled | ScalpSupertrendChannel |
| **SMC detector misfire** | No sweeps detected → LSR channel silent | ScalpChannel (LSR) |
| **CVD computation delay** | CVD divergence >10 candles old → rejected | ScalpCVDChannel |

### 4.2 Regime-Based Signal Suppression

| Regime | Channels Boosted | Channels Suppressed |
|--------|-----------------|-------------------|
| **TRENDING_UP/DOWN** | ScalpChannel (LSR) ×1.5 | RANGE_FADE ×0.3, VWAP blocked (ADX>25) |
| **RANGING/QUIET** | RANGE_FADE ×1.5, VWAP allowed | ScalpChannel (LSR) ×0.5, WM ×0.7 |
| **VOLATILE** | ScalpChannel (WM) ×1.5 | RANGE_FADE ×0.5 |
| **Unknown** | Neutral (1.0×) | Neutral (1.0×) |

### 4.3 Critical Edge Cases Across Channels

1. **ATR = 0 or NaN**: All channels have fallback values (`close × 0.001` to `close × 0.002`), but the fallback range varies between channels. A consistent fallback would improve predictability.

2. **Empty `pair_profile`**: Defaults applied (`"MIDCAP"` tier, generic RSI thresholds). 6 of 9 channels use pair-adjusted thresholds; without profiles, signals may be miscalibrated for extreme pairs.

3. **Concurrent regime transitions**: The regime is computed once per scan cycle. If the market transitions mid-cycle, channels evaluated later in the sequence may be operating on stale regime data.

4. **Cooldown overlap**: All scalp channels share the same 300s cooldown key pattern `(symbol, channel_name)`. If ScalpChannel generates RANGE_FADE signal at T=0, the same symbol's ScalpChannel is blocked for 300s — **all 3 sub-paths** (LSR, RF, WM) are blocked, not just RANGE_FADE.

5. **Signal metadata inconsistency**: Some channels populate `analyst_reason` (FVG, OBI, Divergence, Supertrend, Ichimoku, Orderblock) while others leave it empty (CVD, VWAP). This affects downstream signal quality assessment and user experience.

---

## 5. Test Coverage Assessment

### 5.1 Coverage by Channel

| Channel | Test File | Test Count | Edge Cases | Assessment |
|---------|-----------|-----------|-----------|-----------|
| ScalpChannel (all 3 paths) | `test_channels.py` | 13 | ✅ Sweep, regime, ADX, OBI mandatory | ✅ Good |
| ScalpFVGChannel | `test_signal_quality_improvements.py` | 5-6 | ✅ Fill %, age, HTF | ✅ Good |
| ScalpCVDChannel | `test_signal_quality_improvements.py` | 8-9 | ✅ Staleness, strength, metadata | ✅ Strong |
| ScalpOBIChannel | `test_signal_quality_improvements.py` | 5-6 | ✅ Timestamp, depth, spoofing | ✅ Good |
| ScalpVWAPChannel | Integration refs + `test_channels_extended.py` | ~4 | ⚠️ Analyst reason verified | ⚠️ Moderate |
| ScalpDivergenceChannel | `test_channels_extended.py` | 6 | ✅ ADX, RSI, MACD, NaN, volume | ✅ Good |
| ScalpSupertrendChannel | `test_channels_extended.py` | 5 | ✅ ADX, flip, volume, data min | ✅ Good |
| ScalpIchimokuChannel | `test_channels_extended.py` | 4 | ✅ Data min, TK cross, fallback | ✅ Good |
| ScalpOrderblockChannel | `test_channels_extended.py` | 5 | ✅ OB detection, SL boundary, spread | ✅ Good |

### 5.2 Integration Test Coverage

- ✅ Full pipeline test (`test_backtest_integration.py`): 11 tests covering scanner → channel → signal flow
- ✅ SCALP delivery path (`test_scalp_fast_path.py`): 25 tests for stale signal gates and latency tracking
- ✅ Confidence scoring integration: component weights, regime penalties, MTF confluence

### 5.3 Coverage Gaps

1. ~~**4 channels have zero dedicated tests**~~ ✅ Fixed — all channels now have dedicated tests in `test_channels_extended.py`
2. No stress tests for concurrent multi-channel evaluation
3. No tests for regime transition effects on in-flight signals
4. No tests for WebSocket degradation impact on OBI/WM channels
5. ~~Limited VWAP channel testing~~ Improved with analyst_reason verification

---

## 6. Recommendations

### 6.1 Signal Reliability Improvements

| Priority | Recommendation | Channels | Status |
|----------|---------------|----------|--------|
| **P0** | Add unit tests for untested channels | DIV, ST, ICH, OB | ✅ Done — `tests/test_channels_extended.py` (24 tests) |
| **P0** | Populate `analyst_reason` in CVD and VWAP channels | CVD, VWAP | ✅ Done — CVD includes divergence type, age, strength; VWAP includes band and VWAP price |
| **P1** | Add MTF gate to Divergence and Supertrend channels | DIV, ST | ✅ Done — `mtf_gate_scalp_divergence()` and `mtf_gate_scalp_supertrend()` wired in |
| **P1** | Make OBI check mandatory for WHALE_MOMENTUM | SCALP (WM) | ✅ Done — returns None when `order_book` is None |
| **P1** | Fix ScalpOrderblockChannel SL recomputation | OB | ✅ Done — OB-boundary SL preserved; floor applied only when sl_dist is too tight |
| **P2** | Add graduated FVG fill penalty (replace 60% cliff) | FVG | ✅ Done — graduated decay: 0% fill→1.0, 50%→0.7, 75%→0.4; hard reject >75% |
| **P2** | Improve NaN handling in Divergence channel | DIV | ✅ Done — NaN values dropped instead of replaced with 50.0; rejects if <50% clean data |
| **P2** | Add volume confirmation to Ichimoku channel | ICH | ✅ Done — requires volume ≥ 1.2× 20-bar average |
| **P3** | Standardize ATR fallback across channels | ALL | ✅ Done — all channels use `close × 0.002` (OBI keeps `0.001` by design) |
| **P3** | Consider per-sub-path cooldown for ScalpChannel | SCALP | Deferred — requires scanner-level changes |

### 6.2 Signal Quality Improvements

| Recommendation | Impact |
|----------------|--------|
| Add MACD histogram staleness check in Divergence channel | Prevents using stale MACD data for confirmation |
| Implement OB zone strength scoring (impulse size / ATR ratio) | Better OB quality differentiation |
| Add VWAP reset at session boundaries (daily/weekly) | Current 50-candle rolling VWAP doesn't account for session resets |
| Log soft-gate penalty breakdown per signal | Aids debugging when signals are near rejection threshold |

### 6.3 Monitoring Recommendations

| Metric | Purpose |
|--------|---------|
| Signal generation count per channel per hour | Detect channel going silent (data issue or filter too strict) |
| Average confidence per channel per regime | Detect systematic regime-channel miscalibration |
| Soft-gate penalty distribution per channel | Identify which gates are most active (potential over-filtering) |
| Order book staleness rate for OBI channel | Detect WebSocket degradation impact |
| CVD divergence age distribution | Ensure fresh divergences are being detected |

---

## Appendix: Signal Metadata Completeness Matrix

| Field | LSR | RF | WM | FVG | CVD | DIV | ST | ICH | OB | OBI | VWAP |
|-------|-----|----|----|-----|-----|-----|----|----|-----|-----|------|
| signal_id | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| setup_class | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| direction | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| entry/sl/tp1-3 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| analyst_reason | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| regime | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| atr_percentile | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| pair_tier | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| dca_zone | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| quality_tier | via scoring | via scoring | via scoring | A+ (HTF) | via scoring | via scoring | via scoring | via scoring | via scoring | via scoring | via scoring |
| vwap_price | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

*End of audit report.*
