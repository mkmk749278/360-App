"""Per-pair analysis engine.

Builds independent snapshots of each trading pair's market structure,
computes signal quality metrics, and generates actionable recommendations
to improve pair-specific logic and suppress bad signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.correlation import compute_btc_correlation, detect_lead_lag
from src.performance_metrics import (
    calculate_drawdown_metrics,
    expectancy,
    mfe_mae_analysis,
    profit_factor,
    risk_reward_ratio,
    sharpe_ratio,
    win_rate,
)
from src.utils import get_logger

log = get_logger("pair_analyzer")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_VOL_LOW_PERCENTILE = 20.0
_VOL_HIGH_PERCENTILE = 80.0
_VOL_EXTREME_PERCENTILE = 95.0
_LIQ_THIN_VOL_USD = 5_000_000
_LIQ_DEEP_VOL_USD = 50_000_000
_LIQ_THIN_SPREAD_PCT = 0.03
_LIQ_DEEP_SPREAD_PCT = 0.01

_QUALITY_STRONG_HIT_RATE = 55.0
_QUALITY_STRONG_RR = 1.2
_QUALITY_ACCEPTABLE_HIT_RATE = 45.0
_QUALITY_WEAK_HIT_RATE = 35.0
_QUALITY_CRITICAL_DD = 15.0

# Default consistency trend when data is insufficient
_DEFAULT_CONSISTENCY_TREND = "STABLE"

# Minimum signals needed for pair quality to be meaningful
_MIN_SIGNALS_FOR_QUALITY = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PairSnapshot:
    """Point-in-time snapshot of a pair's market characteristics."""

    symbol: str
    pair_tier: str = "MIDCAP"
    # Volatility
    atr_current: float = 0.0
    atr_percentile: float = 50.0
    bb_width_pct: float = 2.0
    volatility_label: str = "NORMAL"
    # Liquidity
    volume_24h_usd: float = 0.0
    spread_pct: float = 0.0
    liquidity_label: str = "NORMAL"
    # Market Structure
    regime: str = "RANGING"
    adx_value: float = 0.0
    ema_trend: str = "NEUTRAL"
    # BTC Correlation
    btc_corr_short: float = 0.0
    btc_corr_long: float = 0.0
    btc_role: str = "SYNC"
    btc_best_lag: int = 0


@dataclass
class PairSignalQuality:
    """Signal quality metrics computed from historical performance."""

    symbol: str
    total_signals: int = 0
    hit_rate: float = 0.0
    risk_reward: float = 0.0
    profit_factor_val: float = 0.0
    expectancy_val: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    avg_mfe: float = 0.0
    avg_mae: float = 0.0
    consistency_score: float = 0.0
    consistency_trend: str = "STABLE"
    quality_label: str = "ACCEPTABLE"
    weak_areas: List[str] = field(default_factory=list)


@dataclass
class PairRecommendation:
    """Actionable recommendation to improve pair-specific signal quality."""

    symbol: str
    category: str  # REGIME / TIMING / CORRELATION / THRESHOLD / GENERAL
    priority: str  # HIGH / MEDIUM / LOW
    title: str
    description: str
    current_value: str = ""
    suggested_value: str = ""
    expected_impact: str = ""


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def build_pair_snapshot(
    symbol: str,
    indicators: Optional[Dict[str, Any]] = None,
    btc_closes: Optional[List[float]] = None,
    pair_closes: Optional[List[float]] = None,
    volume_24h_usd: float = 0.0,
    spread_pct: float = 0.0,
    pair_tier: str = "MIDCAP",
) -> PairSnapshot:
    """Build a market-structure snapshot for a single pair.

    Parameters
    ----------
    symbol:
        Trading pair (e.g. ``"ETHUSDT"``).
    indicators:
        Dict of pre-computed indicators with keys like ``adx_last``,
        ``ema9_last``, ``ema21_last``, ``bb_upper_last``, ``bb_lower_last``,
        ``bb_mid_last``, ``atr_last``, ``atr_percentile``.
    btc_closes:
        BTC close prices for correlation computation.
    pair_closes:
        This pair's close prices for correlation computation.
    volume_24h_usd:
        24-hour trading volume in USD.
    spread_pct:
        Current bid-ask spread percentage.
    pair_tier:
        MAJOR / MIDCAP / ALTCOIN.
    """
    snap = PairSnapshot(symbol=symbol, pair_tier=pair_tier)
    snap.volume_24h_usd = volume_24h_usd
    snap.spread_pct = spread_pct

    # Volatility
    if indicators:
        snap.atr_current = float(indicators.get("atr_last", 0.0) or 0.0)
        snap.atr_percentile = float(indicators.get("atr_percentile", 50.0) or 50.0)
        bb_upper = float(indicators.get("bb_upper_last", 0.0) or 0.0)
        bb_lower = float(indicators.get("bb_lower_last", 0.0) or 0.0)
        bb_mid = float(indicators.get("bb_mid_last", 1.0) or 1.0)
        if bb_mid > 0:
            snap.bb_width_pct = (bb_upper - bb_lower) / bb_mid * 100.0
        snap.adx_value = float(indicators.get("adx_last", 0.0) or 0.0)
        ema_fast = float(indicators.get("ema9_last", 0.0) or 0.0)
        ema_slow = float(indicators.get("ema21_last", 0.0) or 0.0)
        if ema_fast and ema_slow:
            if ema_fast > ema_slow * 1.001:
                snap.ema_trend = "BULLISH"
            elif ema_fast < ema_slow * 0.999:
                snap.ema_trend = "BEARISH"

    # Volatility label
    if snap.atr_percentile < _VOL_LOW_PERCENTILE:
        snap.volatility_label = "LOW"
    elif snap.atr_percentile > _VOL_EXTREME_PERCENTILE:
        snap.volatility_label = "EXTREME"
    elif snap.atr_percentile > _VOL_HIGH_PERCENTILE:
        snap.volatility_label = "HIGH"
    else:
        snap.volatility_label = "NORMAL"

    # Liquidity label
    if volume_24h_usd < _LIQ_THIN_VOL_USD or spread_pct > _LIQ_THIN_SPREAD_PCT:
        snap.liquidity_label = "THIN"
    elif volume_24h_usd > _LIQ_DEEP_VOL_USD and spread_pct < _LIQ_DEEP_SPREAD_PCT:
        snap.liquidity_label = "DEEP"
    else:
        snap.liquidity_label = "NORMAL"

    # Regime from ADX + BB width
    if snap.bb_width_pct >= 5.0:
        snap.regime = "VOLATILE"
    elif snap.bb_width_pct <= 1.2:
        snap.regime = "QUIET"
    elif snap.adx_value >= 25:
        snap.regime = "TRENDING_UP" if snap.ema_trend == "BULLISH" else "TRENDING_DOWN"
    else:
        snap.regime = "RANGING"

    # BTC correlation
    if btc_closes and pair_closes:
        corr = compute_btc_correlation(btc_closes, pair_closes)
        snap.btc_corr_short = corr.get("short", 0.0)
        snap.btc_corr_long = corr.get("long", 0.0)
        lead_lag = detect_lead_lag(btc_closes, pair_closes)
        snap.btc_role = str(lead_lag.get("role", "SYNC"))
        snap.btc_best_lag = int(lead_lag.get("best_lag", 0))
        # Classify as UNCORRELATED when correlation is weak
        if abs(snap.btc_corr_short) < 0.2 and abs(snap.btc_corr_long) < 0.2:
            snap.btc_role = "UNCORRELATED"

    return snap


# ---------------------------------------------------------------------------
# Signal quality computation
# ---------------------------------------------------------------------------


def compute_pair_signal_quality(
    tracker: Any,
    symbol: str,
    window_days: int = 30,
) -> PairSignalQuality:
    """Compute comprehensive signal quality metrics for a pair.

    Parameters
    ----------
    tracker:
        A :class:`~src.performance_tracker.PerformanceTracker` instance.
    symbol:
        Trading pair symbol.
    window_days:
        Lookback period.
    """
    quality = PairSignalQuality(symbol=symbol)
    pnl_list = tracker.get_pair_pnl_list(symbol, window_days=window_days)
    quality.total_signals = len(pnl_list)

    if quality.total_signals < _MIN_SIGNALS_FOR_QUALITY:
        quality.quality_label = "INSUFFICIENT_DATA"
        return quality

    quality.hit_rate = win_rate(pnl_list)
    quality.risk_reward = risk_reward_ratio(pnl_list)
    quality.profit_factor_val = profit_factor(pnl_list)
    quality.expectancy_val = expectancy(pnl_list)
    quality.sharpe = sharpe_ratio(pnl_list)
    quality.current_drawdown, quality.max_drawdown = calculate_drawdown_metrics(pnl_list)

    # MFE / MAE
    mfe_mae = tracker.get_pair_mfe_mae(symbol, window_days=window_days)
    mfe_list = mfe_mae.get("mfe", [])
    mae_list = mfe_mae.get("mae", [])
    if mfe_list and mae_list:
        analysis = mfe_mae_analysis(mfe_list, mae_list)
        quality.avg_mfe = analysis.get("avg_mfe", 0.0)
        quality.avg_mae = analysis.get("avg_mae", 0.0)

    # Consistency
    consistency = tracker.get_pair_consistency(symbol, window_days=window_days)
    quality.consistency_score = 100.0 - consistency.get("std_wr", 0.0) * 2.0
    quality.consistency_score = max(0.0, min(100.0, quality.consistency_score))
    quality.consistency_trend = consistency.get("trend", _DEFAULT_CONSISTENCY_TREND)

    # Quality classification
    weak_areas: List[str] = []
    if quality.hit_rate < _QUALITY_WEAK_HIT_RATE:
        weak_areas.append("low_hit_rate")
    if quality.max_drawdown > _QUALITY_CRITICAL_DD:
        weak_areas.append("high_drawdown")
    if quality.risk_reward < 0.8:
        weak_areas.append("poor_risk_reward")
    if quality.expectancy_val < 0:
        weak_areas.append("negative_expectancy")
    if not consistency.get("is_consistent", True):
        weak_areas.append("inconsistent")
    if quality.consistency_trend == "DEGRADING":
        weak_areas.append("degrading_performance")
    quality.weak_areas = weak_areas

    # Assign label
    if quality.hit_rate < _QUALITY_WEAK_HIT_RATE or quality.max_drawdown > _QUALITY_CRITICAL_DD:
        quality.quality_label = "CRITICAL"
    elif (
        quality.hit_rate >= _QUALITY_STRONG_HIT_RATE
        and quality.risk_reward >= _QUALITY_STRONG_RR
        and consistency.get("is_consistent", False)
    ):
        quality.quality_label = "STRONG"
    elif quality.hit_rate >= _QUALITY_ACCEPTABLE_HIT_RATE:
        quality.quality_label = "ACCEPTABLE"
    else:
        quality.quality_label = "WEAK"

    return quality


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------


def generate_pair_recommendations(
    symbol: str,
    snapshot: PairSnapshot,
    quality: PairSignalQuality,
    regime_stats: Dict[str, Dict[str, Any]],
    session_stats: Dict[str, Dict[str, Any]],
    weekday_stats: Dict[str, Dict[str, Any]],
    anomalies: Optional[List[Any]] = None,
) -> List[PairRecommendation]:
    """Generate actionable recommendations for a pair.

    Examines regime performance, session timing, BTC correlation, and
    signal quality to produce prioritised improvement suggestions.
    """
    recs: List[PairRecommendation] = []

    # --- Regime recommendations ---
    for regime, stats in regime_stats.items():
        count = stats.get("count", 0)
        wr = stats.get("win_rate", 0.0)
        if count >= 5 and wr < 35.0:
            recs.append(PairRecommendation(
                symbol=symbol,
                category="REGIME",
                priority="HIGH",
                title=f"Suppress signals in {regime}",
                description=(
                    f"{symbol} has a {wr:.1f}% win rate in {regime} regime "
                    f"over {count} signals — consider suppressing or adding "
                    f"confidence penalty for this regime."
                ),
                current_value=f"WR={wr:.1f}%",
                suggested_value="Suppress or -15pts penalty",
                expected_impact="Fewer losing trades in unfavourable regime",
            ))

    # --- Session timing recommendations ---
    best_session_wr = 0.0
    for _s, st in session_stats.items():
        if st.get("count", 0) >= 3:
            best_session_wr = max(best_session_wr, st.get("win_rate", 0.0))

    for session, stats in session_stats.items():
        count = stats.get("count", 0)
        wr = stats.get("win_rate", 0.0)
        if count >= 5 and wr < 30.0 and best_session_wr - wr > 20.0:
            recs.append(PairRecommendation(
                symbol=symbol,
                category="TIMING",
                priority="MEDIUM",
                title=f"Reduce {symbol} signals in {session}",
                description=(
                    f"Win rate in {session} is {wr:.1f}% vs best session "
                    f"{best_session_wr:.1f}%. Add confidence penalty or suppress."
                ),
                current_value=f"WR={wr:.1f}%",
                suggested_value=f"-10pts penalty in {session}",
                expected_impact="Avoid low-quality session entries",
            ))

    # --- Weekend recommendations ---
    weekend_signals = 0
    weekend_wins = 0
    weekend_losses = 0
    weekday_signals = 0
    weekday_wins = 0
    for _day, stats in weekday_stats.items():
        if stats.get("is_weekend", False):
            weekend_signals += stats.get("count", 0)
            weekend_wins += stats.get("wins", 0)
            weekend_losses += stats.get("losses", 0)
        else:
            weekday_signals += stats.get("count", 0)
            weekday_wins += stats.get("wins", 0)

    weekend_total = weekend_wins + weekend_losses
    weekday_total_wl = weekday_wins + (
        sum(s.get("losses", 0) for s in weekday_stats.values() if not s.get("is_weekend"))
    )
    weekend_wr = (weekend_wins / weekend_total * 100) if weekend_total > 0 else 50.0
    weekday_wr = (weekday_wins / weekday_total_wl * 100) if weekday_total_wl > 0 else 50.0

    if weekend_signals >= 3 and weekend_wr < 35.0 and weekday_wr - weekend_wr > 15.0:
        recs.append(PairRecommendation(
            symbol=symbol,
            category="TIMING",
            priority="MEDIUM",
            title=f"Weekend penalty for {symbol}",
            description=(
                f"Weekend WR={weekend_wr:.1f}% vs weekday WR={weekday_wr:.1f}%. "
                f"Add -15pts confidence penalty on weekends."
            ),
            current_value=f"Weekend WR={weekend_wr:.1f}%",
            suggested_value="-15pts weekend penalty",
            expected_impact="Reduce weekend losses",
        ))

    # --- BTC correlation recommendations ---
    if abs(snapshot.btc_corr_short) >= 0.7:
        recs.append(PairRecommendation(
            symbol=symbol,
            category="CORRELATION",
            priority="HIGH",
            title=f"High BTC correlation ({snapshot.btc_corr_short:.2f})",
            description=(
                f"{symbol} has {snapshot.btc_corr_short:.2f} correlation with BTC "
                f"(role: {snapshot.btc_role}). Signals should account for BTC direction."
            ),
            current_value=f"corr={snapshot.btc_corr_short:.2f}",
            suggested_value="Increase cross-asset penalty",
            expected_impact="Avoid signals against BTC trend",
        ))

    if snapshot.btc_role == "LEADER":
        recs.append(PairRecommendation(
            symbol=symbol,
            category="CORRELATION",
            priority="LOW",
            title=f"{symbol} leads BTC by {abs(snapshot.btc_best_lag)} candles",
            description=(
                f"{symbol} tends to move before BTC. Consider using as a "
                f"leading indicator for BTC-ecosystem signals."
            ),
            expected_impact="Informational — leading indicator",
        ))

    # --- Quality-based recommendations ---
    if quality.quality_label == "CRITICAL":
        recs.append(PairRecommendation(
            symbol=symbol,
            category="GENERAL",
            priority="HIGH",
            title=f"Critical signal quality for {symbol}",
            description=(
                f"Hit rate={quality.hit_rate:.1f}%, max DD={quality.max_drawdown:.1f}%, "
                f"weak areas: {', '.join(quality.weak_areas)}. "
                f"Consider suppressing this pair entirely."
            ),
            current_value=f"Quality={quality.quality_label}",
            suggested_value="Suppress or major threshold adjustment",
            expected_impact="Eliminate consistently losing pair",
        ))

    if "degrading_performance" in quality.weak_areas:
        recs.append(PairRecommendation(
            symbol=symbol,
            category="GENERAL",
            priority="HIGH",
            title=f"Declining performance for {symbol}",
            description=(
                f"Performance trend is DEGRADING over the analysis period. "
                f"Consistency trend shows weakening signal quality."
            ),
            expected_impact="Early warning of pair deterioration",
        ))

    if quality.avg_mfe > 0 and quality.expectancy_val > 0:
        if quality.avg_mfe > 2.0 * quality.expectancy_val:
            recs.append(PairRecommendation(
                symbol=symbol,
                category="THRESHOLD",
                priority="MEDIUM",
                title=f"MFE waste: extend TP for {symbol}",
                description=(
                    f"Avg MFE={quality.avg_mfe:.2f}% vs avg PnL={quality.expectancy_val:.2f}%. "
                    f"Price moves further than captured. Extend TP ratios."
                ),
                current_value=f"MFE={quality.avg_mfe:.2f}%",
                suggested_value="Extend TP3 ratio by 15%",
                expected_impact="Capture more of the move",
            ))

    # --- Volatility recommendations ---
    if snapshot.volatility_label == "EXTREME" and quality.quality_label != "STRONG":
        recs.append(PairRecommendation(
            symbol=symbol,
            category="THRESHOLD",
            priority="MEDIUM",
            title=f"Extreme volatility for {symbol}",
            description=(
                f"ATR is at {snapshot.atr_percentile:.0f}th percentile. "
                f"Consider widening SL or reducing position size."
            ),
            expected_impact="Reduce stop-outs from volatility spikes",
        ))

    if snapshot.liquidity_label == "THIN":
        recs.append(PairRecommendation(
            symbol=symbol,
            category="THRESHOLD",
            priority="MEDIUM",
            title=f"Thin liquidity for {symbol}",
            description=(
                f"Volume=${snapshot.volume_24h_usd/1e6:.1f}M, "
                f"spread={snapshot.spread_pct:.3f}%. Increase spread threshold "
                f"or reduce signal confidence."
            ),
            expected_impact="Avoid slippage-prone entries",
        ))

    return sorted(recs, key=lambda r: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(r.priority, 3))
