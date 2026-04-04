"""Volatility metrics helpers for dynamic SL/TP calculation.

Provides regime-aware volatility analysis used by the dynamic SL/TP
system to adapt stop-loss and take-profit levels based on current
market conditions.

PR 02 Implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from src.utils import get_logger

log = get_logger("volatility_metrics")


@dataclass
class VolatilityProfile:
    """Volatility analysis result for a single pair."""

    atr_current: float = 0.0
    atr_percentile: float = 50.0       # 0-100 rolling percentile
    bb_width_pct: float = 2.0          # Bollinger Band width as pct
    regime: str = ""                    # Market regime string
    pair_tier: str = "MIDCAP"          # MAJOR / MIDCAP / ALTCOIN
    historical_hit_rate: float = 0.5   # 0-1 historical win rate


# SL multipliers by regime — QUIET gets wider SL (avoid noise stop-outs),
# TRENDING gets tighter SL (clear direction, protect profits faster).
_REGIME_SL_MULTIPLIER = {
    "TRENDING_UP": 0.85,    # Tighter SL in trends
    "TRENDING_DOWN": 0.85,
    "RANGING": 1.0,         # Default
    "VOLATILE": 1.15,       # Slightly wider for volatile
    "QUIET": 1.25,          # Wider SL to survive noise
}

# TP multipliers by regime — TRENDING gets extended TP (ride the trend),
# QUIET gets compressed TP (take profits quickly in low-vol).
_REGIME_TP_MULTIPLIER = {
    "TRENDING_UP": 1.20,    # Extended TP to ride trends
    "TRENDING_DOWN": 1.20,
    "RANGING": 1.0,         # Default
    "VOLATILE": 0.90,       # Compressed TP, take profits quickly
    "QUIET": 0.80,          # Tight TP in quiet markets
}

# Pair tier SL adjustments (majors need tighter, altcoins wider).
_TIER_SL_ADJUSTMENT = {
    "MAJOR": 0.90,
    "MIDCAP": 1.0,
    "ALTCOIN": 1.20,
}


def compute_regime_sl_multiplier(regime: str) -> float:
    """Return the SL width multiplier for the given regime.

    A value >1.0 widens the SL; <1.0 tightens it.
    """
    return _REGIME_SL_MULTIPLIER.get(regime.upper(), 1.0)


def compute_regime_tp_multiplier(regime: str) -> float:
    """Return the TP ratio multiplier for the given regime.

    A value >1.0 extends TP targets; <1.0 compresses them.
    """
    return _REGIME_TP_MULTIPLIER.get(regime.upper(), 1.0)


def compute_volatility_adjusted_sl(
    base_sl_distance: float,
    profile: VolatilityProfile,
) -> float:
    """Compute regime- and volatility-adjusted stop-loss distance.

    Parameters
    ----------
    base_sl_distance:
        Raw SL distance from the channel evaluator.
    profile:
        Volatility analysis for the pair.

    Returns
    -------
    float
        Adjusted SL distance.
    """
    regime_mult = compute_regime_sl_multiplier(profile.regime)
    tier_mult = _TIER_SL_ADJUSTMENT.get(profile.pair_tier, 1.0)

    # ATR percentile adjustment: high ATR → widen SL slightly
    atr_adj = 1.0
    if profile.atr_percentile > 75:
        atr_adj = 1.0 + (profile.atr_percentile - 75) / 100.0  # up to +25%
    elif profile.atr_percentile < 25:
        atr_adj = 1.0 - (25 - profile.atr_percentile) / 200.0  # up to -12.5%

    # Hit rate adjustment: poor hit rate → widen SL for more room
    hr_adj = 1.0
    if profile.historical_hit_rate < 0.4:
        hr_adj = 1.1  # +10% SL width for poor performers
    elif profile.historical_hit_rate > 0.7:
        hr_adj = 0.95  # tighten for consistent winners

    adjusted = base_sl_distance * regime_mult * tier_mult * atr_adj * hr_adj
    log.debug(
        "Dynamic SL: base={:.6f} regime_mult={:.2f} tier={:.2f} "
        "atr_adj={:.2f} hr_adj={:.2f} → {:.6f}",
        base_sl_distance, regime_mult, tier_mult, atr_adj, hr_adj, adjusted,
    )
    return adjusted


def compute_volatility_adjusted_tp_ratios(
    base_ratios: list[float],
    profile: VolatilityProfile,
) -> list[float]:
    """Compute regime- and volatility-adjusted TP ratio multipliers.

    Parameters
    ----------
    base_ratios:
        Base R-multiple ratios (e.g. ``[1.5, 2.5, 4.0]``).
    profile:
        Volatility analysis for the pair.

    Returns
    -------
    list[float]
        Adjusted TP ratios.
    """
    regime_mult = compute_regime_tp_multiplier(profile.regime)

    # High hit rate → stretch TP to capture more; low → compress for safety
    hr_mult = 1.0
    if profile.historical_hit_rate > 0.65:
        hr_mult = 1.05
    elif profile.historical_hit_rate < 0.35:
        hr_mult = 0.90

    adjusted = [round(r * regime_mult * hr_mult, 4) for r in base_ratios]
    log.debug(
        "Dynamic TP ratios: base={} regime_mult={:.2f} hr_mult={:.2f} → {}",
        base_ratios, regime_mult, hr_mult, adjusted,
    )
    return adjusted


def calculate_dynamic_sl_tp(
    pair: str,
    regime: str,
    volatility_pct: float,
    hit_rate: float,
    base_sl_distance: float,
    base_tp_ratios: list[float],
    pair_tier: str = "MIDCAP",
    atr_percentile: float = 50.0,
) -> Tuple[float, list[float]]:
    """Calculate dynamic SL distance and TP ratios.

    Convenience function that wraps the volatility-adjusted computations
    for use by the trade execution pipeline.

    Parameters
    ----------
    pair:
        Symbol name (for logging).
    regime:
        Current market regime string.
    volatility_pct:
        BB width or similar volatility measure (percentage).
    hit_rate:
        Historical hit rate for this pair/channel (0-1).
    base_sl_distance:
        Raw SL distance from channel evaluator.
    base_tp_ratios:
        Base TP R-multiple ratios.
    pair_tier:
        Pair tier classification.
    atr_percentile:
        Current ATR rolling percentile (0-100).

    Returns
    -------
    tuple[float, list[float]]
        ``(adjusted_sl_distance, adjusted_tp_ratios)``
    """
    profile = VolatilityProfile(
        atr_percentile=atr_percentile,
        bb_width_pct=volatility_pct,
        regime=regime,
        pair_tier=pair_tier,
        historical_hit_rate=hit_rate,
    )

    adj_sl = compute_volatility_adjusted_sl(base_sl_distance, profile)
    adj_tp = compute_volatility_adjusted_tp_ratios(base_tp_ratios, profile)

    log.debug(
        "Dynamic SL/TP for {}: regime={} tier={} sl={:.6f} tp={}",
        pair, regime, pair_tier, adj_sl, adj_tp,
    )
    return adj_sl, adj_tp


# ---------------------------------------------------------------------------
# GARCH-like volatility forecasting (EWMA / RiskMetrics approximation)
# ---------------------------------------------------------------------------


class GarchLikeForecaster:
    """Simple EWMA-based volatility forecaster (lightweight GARCH(1,1) approximation).

    Uses the exponentially weighted moving average variance estimator
    popularised by J.P. Morgan's RiskMetrics methodology:

        σ²_t = α · r²_{t-1} + β · σ²_{t-1}

    Parameters
    ----------
    alpha:
        Weight for the latest squared return (shock weight).
    beta:
        Persistence weight for the previous variance estimate.
    """

    def __init__(self, alpha: float = 0.06, beta: float = 0.94) -> None:
        self.alpha = alpha
        self.beta = beta
        self._variance: float = 1.0
        self._n_updates: int = 0

    def update(self, return_pct: float) -> float:
        """Update the variance forecast with a new return observation.

        Parameters
        ----------
        return_pct:
            Percentage return for the latest period.

        Returns
        -------
        float
            Updated annualised volatility forecast (sqrt of variance).
        """
        self._variance = self.alpha * (return_pct ** 2) + self.beta * self._variance
        self._n_updates += 1
        return self.forecast()

    def forecast(self) -> float:
        """Return the current volatility forecast (std-dev, same units as input returns)."""
        return float(np.sqrt(max(self._variance, 0.0)))

    def get_confidence_interval(self, n_periods: int = 1) -> Tuple[float, float]:
        """Return a 95 % confidence interval for the cumulative volatility over *n_periods*.

        Parameters
        ----------
        n_periods:
            Number of periods ahead.

        Returns
        -------
        Tuple[float, float]
            ``(lower, upper)`` bounds of the 95 % CI.
        """
        n_periods = max(1, n_periods)
        vol = self.forecast() * np.sqrt(n_periods)
        # 95 % CI ≈ ±1.96 σ
        return (-1.96 * vol, 1.96 * vol)


def forecast_volatility(returns: list, horizon: int = 5) -> dict:
    """Fit an EWMA volatility model and forecast ahead.

    Parameters
    ----------
    returns:
        List of return percentages (most recent last).
    horizon:
        Number of periods to forecast ahead.

    Returns
    -------
    dict
        ``{"current_vol", "forecast_vol", "vol_trend", "vol_percentile"}``
    """
    if not returns:
        return {
            "current_vol": 0.0,
            "forecast_vol": 0.0,
            "vol_trend": "STABLE",
            "vol_percentile": 50.0,
        }

    forecaster = GarchLikeForecaster()
    vol_history: list[float] = []
    for r in returns:
        forecaster.update(float(r))
        vol_history.append(forecaster.forecast())

    current_vol = vol_history[-1] if vol_history else 0.0
    # EWMA forecast is constant for future periods (variance is persistent)
    forecast_vol = forecaster.forecast() * float(np.sqrt(max(1, horizon)))

    # Trend detection: compare recent vol to earlier vol
    if len(vol_history) >= 10:
        recent_avg = float(np.mean(vol_history[-5:]))
        earlier_avg = float(np.mean(vol_history[-10:-5]))
        if earlier_avg > 0:
            change = (recent_avg - earlier_avg) / earlier_avg
            if change > 0.10:
                vol_trend = "INCREASING"
            elif change < -0.10:
                vol_trend = "DECREASING"
            else:
                vol_trend = "STABLE"
        else:
            vol_trend = "STABLE"
    else:
        vol_trend = "STABLE"

    # Percentile of current vol vs full history
    if len(vol_history) >= 2:
        vol_percentile = float(
            np.sum(np.array(vol_history) <= current_vol) / len(vol_history) * 100.0
        )
    else:
        vol_percentile = 50.0

    return {
        "current_vol": round(current_vol, 6),
        "forecast_vol": round(forecast_vol, 6),
        "vol_trend": vol_trend,
        "vol_percentile": round(vol_percentile, 2),
    }


def compute_volatility_regime_sl_adjustment(vol_forecast: float, vol_current: float) -> float:
    """Return a SL width multiplier based on forecasted vs current volatility.

    Parameters
    ----------
    vol_forecast:
        Forecasted volatility.
    vol_current:
        Current (realised) volatility.

    Returns
    -------
    float
        Multiplier: 1.15 (widen), 0.90 (tighten), or 1.0 (no change).
    """
    if vol_current <= 0:
        return 1.0
    ratio = (vol_forecast - vol_current) / vol_current
    if ratio > 0.20:
        return 1.15  # widen SL by 15 %
    if ratio < -0.20:
        return 0.90  # tighten SL by 10 %
    return 1.0
