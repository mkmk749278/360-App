"""Correlation-aware position limiting.

Prevents the system from filling all concurrent signal slots with
highly correlated positions (e.g., all LONG on BTC-correlated alts).

Also provides rolling Pearson correlation vs BTC and lead/lag detection.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from src.utils import get_logger

log = get_logger("correlation")

# Maximum number of same-direction positions allowed within a single
# correlation group.  Env-overridable.
MAX_SAME_DIRECTION_PER_GROUP: int = int(
    os.getenv("MAX_SAME_DIRECTION_PER_GROUP", "3")
)

# Correlation groups – symbols that tend to move together.
# A symbol can appear in multiple groups.
CORRELATION_GROUPS: Dict[str, List[str]] = {
    "BTC_ECOSYSTEM": [
        "BTCUSDT", "BTCBUSD", "WBTCUSDT",
    ],
    "MAJOR_ALTS": [
        "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
        "AVAXUSDT", "DOTUSDT", "MATICUSDT", "LINKUSDT",
        "NEARUSDT", "ATOMUSDT",
    ],
    "MEME": [
        "DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT",
    ],
    "DEFI": [
        "UNIUSDT", "AAVEUSDT", "MKRUSDT", "COMPUSDT",
        "SUSHIUSDT", "CRVUSDT",
    ],
    "LAYER2": [
        "ARBUSDT", "OPUSDT", "STXUSDT", "IMXUSDT",
    ],
}

# Build reverse lookup: symbol → set of group names
_SYMBOL_TO_GROUPS: Dict[str, Set[str]] = {}
for _group_name, _symbols in CORRELATION_GROUPS.items():
    for _sym in _symbols:
        _SYMBOL_TO_GROUPS.setdefault(_sym, set()).add(_group_name)


def get_correlation_groups(symbol: str) -> Set[str]:
    """Return the set of correlation group names that *symbol* belongs to."""
    return _SYMBOL_TO_GROUPS.get(symbol, set())


def check_correlation_limit(
    symbol: str,
    direction: str,
    active_positions: Dict[str, Tuple[str, str]],
    max_per_group: int = MAX_SAME_DIRECTION_PER_GROUP,
) -> Tuple[bool, str]:
    """Check whether adding a new position would exceed correlation limits.

    Parameters
    ----------
    symbol:
        The symbol of the new signal (e.g. ``"SOLUSDT"``).
    direction:
        ``"LONG"`` or ``"SHORT"``.
    active_positions:
        Dict mapping signal_id → (symbol, direction) for all currently
        active signals.
    max_per_group:
        Maximum same-direction positions allowed per correlation group.

    Returns
    -------
    (allowed, reason)
        ``allowed`` is True if the position can be opened.
        ``reason`` explains why it was blocked (empty if allowed).
    """
    new_groups = get_correlation_groups(symbol)
    if not new_groups:
        return True, ""

    # Count existing same-direction positions per group
    group_counts: Dict[str, int] = {}
    for _sid, (pos_symbol, pos_direction) in active_positions.items():
        if pos_direction != direction:
            continue
        pos_groups = get_correlation_groups(pos_symbol)
        for g in pos_groups:
            group_counts[g] = group_counts.get(g, 0) + 1

    # Check if adding this signal would exceed the limit in any shared group
    for g in new_groups:
        current = group_counts.get(g, 0)
        if current >= max_per_group:
            return False, (
                f"Correlation limit: {current}/{max_per_group} {direction} positions "
                f"already open in group '{g}'"
            )

    return True, ""


# ---------------------------------------------------------------------------
# Rolling BTC correlation  (Rec 6)
# ---------------------------------------------------------------------------

# Default window sizes for rolling correlation.
_SHORT_WINDOW: int = 50
_LONG_WINDOW: int = 200
try:
    _SHORT_WINDOW = int(os.getenv("CORR_SHORT_WINDOW", "50"))
    _LONG_WINDOW = int(os.getenv("CORR_LONG_WINDOW", "200"))
except (ValueError, TypeError):
    log.warning("Invalid CORR_SHORT_WINDOW/CORR_LONG_WINDOW env var; using defaults")

# Maximum lags (candles) checked for cross-correlation lead/lag analysis.
_MAX_LAG: int = 5
try:
    _MAX_LAG = int(os.getenv("CORR_MAX_LAG", "5"))
except (ValueError, TypeError):
    log.warning("Invalid CORR_MAX_LAG env var; using default")

# Minimum number of data points required for correlation calculation.
_MIN_DATA_POINTS: int = 5


def rolling_pearson(
    x: List[float],
    y: List[float],
    window: int = _SHORT_WINDOW,
) -> float:
    """Compute the trailing rolling Pearson correlation between two series.

    Returns the correlation of the last *window* observations.  If fewer
    than *window* values are available, all available values are used.
    Returns 0.0 when there is insufficient data (< 5 points) or zero
    variance.
    """
    min_len = min(len(x), len(y))
    if min_len < _MIN_DATA_POINTS:
        return 0.0

    n = min(window, min_len)
    xa = np.asarray(x[-n:], dtype=np.float64)
    ya = np.asarray(y[-n:], dtype=np.float64)

    x_std = np.std(xa)
    y_std = np.std(ya)
    if x_std == 0 or y_std == 0:
        return 0.0

    corr = float(np.corrcoef(xa, ya)[0, 1])
    return corr if np.isfinite(corr) else 0.0


def compute_btc_correlation(
    btc_closes: List[float],
    pair_closes: List[float],
    short_window: int = _SHORT_WINDOW,
    long_window: int = _LONG_WINDOW,
) -> Dict[str, float]:
    """Compute short and long rolling Pearson correlation vs BTC.

    Returns
    -------
    dict with keys ``"short"`` (50-candle) and ``"long"`` (200-candle).
    """
    return {
        "short": rolling_pearson(btc_closes, pair_closes, short_window),
        "long": rolling_pearson(btc_closes, pair_closes, long_window),
    }


# ---------------------------------------------------------------------------
# Lead / Lag detection  (Rec 9)
# ---------------------------------------------------------------------------


def detect_lead_lag(
    btc_closes: List[float],
    pair_closes: List[float],
    max_lag: int = _MAX_LAG,
    min_length: int = 30,
) -> Dict[str, object]:
    """Detect whether *pair* leads or lags BTC via cross-correlation.

    Computes the cross-correlation at lags ``-max_lag … +max_lag`` and
    returns the lag with the highest absolute correlation.

    Returns
    -------
    dict with:
        ``best_lag``  – positive means pair *lags* BTC, negative means
                        pair *leads* BTC.
        ``best_corr`` – Pearson correlation at ``best_lag``.
        ``role``      – ``"LEADER"``, ``"LAGGER"``, or ``"SYNC"``.
    """
    min_len = min(len(btc_closes), len(pair_closes))
    if min_len < max(min_length, max_lag + 5):
        return {"best_lag": 0, "best_corr": 0.0, "role": "SYNC"}

    btc = np.asarray(btc_closes[-min_len:], dtype=np.float64)
    pair = np.asarray(pair_closes[-min_len:], dtype=np.float64)

    # Use returns for stationarity
    btc_ret = np.diff(btc) / (btc[:-1] + 1e-12)
    pair_ret = np.diff(pair) / (pair[:-1] + 1e-12)

    best_lag = 0
    best_corr = 0.0

    for lag in range(-max_lag, max_lag + 1):
        if lag == 0:
            a, b = btc_ret, pair_ret
        elif lag > 0:
            # pair lags BTC by `lag` candles
            a = btc_ret[:-lag]
            b = pair_ret[lag:]
        else:
            # pair leads BTC by `|lag|` candles
            a = btc_ret[-lag:]
            b = pair_ret[:lag]

        if len(a) < 10 or len(b) < 10:
            continue
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]

        std_a, std_b = np.std(a), np.std(b)
        if std_a == 0 or std_b == 0:
            continue

        c = float(np.corrcoef(a, b)[0, 1])
        if np.isfinite(c) and abs(c) > abs(best_corr):
            best_corr = c
            best_lag = lag

    if best_lag < 0:
        role = "LEADER"
    elif best_lag > 0:
        role = "LAGGER"
    else:
        role = "SYNC"

    return {"best_lag": best_lag, "best_corr": round(best_corr, 4), "role": role}


# ---------------------------------------------------------------------------
# Convenience: correlation penalty for cross-asset gate  (Rec 7)
# ---------------------------------------------------------------------------


# Correlation penalty thresholds and ranges for graduated penalties.
_PENALTY_HIGH_CORR: float = 0.8     # Above this: maximum penalty
_PENALTY_MED_CORR: float = 0.5      # Above this: partial penalty
_PENALTY_LOW_CORR: float = 0.2      # Below this: no penalty
_PENALTY_MAX: float = -15.0          # Penalty at high correlation
_PENALTY_MID: float = -5.0           # Penalty at medium correlation


def correlation_confidence_penalty(btc_correlation: float) -> float:
    """Return a confidence penalty based on dynamic BTC correlation.

    High-corr pairs get a large penalty (up to -15) when BTC is dumping;
    low-corr pairs get little or no penalty.

    Parameters
    ----------
    btc_correlation:
        Rolling Pearson correlation vs BTC (−1 to +1).

    Returns
    -------
    Penalty as a **non-positive** float (0.0 means no penalty).
    """
    abs_corr = abs(btc_correlation)
    if abs_corr >= _PENALTY_HIGH_CORR:
        return _PENALTY_MAX
    if abs_corr >= _PENALTY_MED_CORR:
        # Linear interpolation: _PENALTY_MID at 0.5, _PENALTY_MAX at 0.8
        frac = (abs_corr - _PENALTY_MED_CORR) / (_PENALTY_HIGH_CORR - _PENALTY_MED_CORR)
        return _PENALTY_MID + frac * (_PENALTY_MAX - _PENALTY_MID)
    if abs_corr >= _PENALTY_LOW_CORR:
        # Linear interpolation: 0 at 0.2, _PENALTY_MID at 0.5
        frac = (abs_corr - _PENALTY_LOW_CORR) / (_PENALTY_MED_CORR - _PENALTY_LOW_CORR)
        return frac * _PENALTY_MID
    return 0.0
