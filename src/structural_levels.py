"""Structural level detection for SL/TP placement.

Identifies key price levels from market structure (swing highs/lows,
round numbers, and VPOC/volume clusters) to place SL and TP at
meaningful levels where price is likely to react.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np


# ---------------------------------------------------------------------------
# Swing highs / lows
# ---------------------------------------------------------------------------

def find_swing_levels(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    lookback: int = 20,
) -> Dict[str, List[float]]:
    """Return recent swing highs and swing lows.

    A swing high is a candle whose high is the local maximum within ±3 candles.
    A swing low is a candle whose low is the local minimum within ±3 candles.

    Only the last *lookback* candles are scanned (the most recent structure).
    """
    swing_highs: List[float] = []
    swing_lows: List[float] = []
    window = 3

    n = len(highs)
    if n < 2 * window + 1:
        return {"swing_highs": swing_highs, "swing_lows": swing_lows}

    start = max(window, n - lookback)
    end = n - window

    for i in range(start, end):
        # Swing high: highs[i] >= all highs in [i-window .. i+window]
        if highs[i] == np.max(highs[i - window : i + window + 1]):
            swing_highs.append(float(highs[i]))
        # Swing low: lows[i] <= all lows in [i-window .. i+window]
        if lows[i] == np.min(lows[i - window : i + window + 1]):
            swing_lows.append(float(lows[i]))

    return {"swing_highs": swing_highs, "swing_lows": swing_lows}


# ---------------------------------------------------------------------------
# Round numbers
# ---------------------------------------------------------------------------

def find_round_numbers(price: float, count: int = 5) -> List[float]:
    """Return the *count* nearest round numbers above and below *price*.

    The rounding step depends on the price magnitude:
    * price > 1000  →  step = 100
    * price > 100   →  step = 10
    * price > 10    →  step = 1
    * price > 1     →  step = 0.1
    * price <= 1    →  step = 0.01
    """
    if price > 1000:
        step = 100.0
    elif price > 100:
        step = 10.0
    elif price > 10:
        step = 1.0
    elif price > 1:
        step = 0.1
    else:
        step = 0.01

    base = (price // step) * step
    levels: List[float] = []
    for offset in range(-count, count + 1):
        levels.append(round(base + offset * step, 8))
    return sorted(set(levels))


# ---------------------------------------------------------------------------
# Structural SL adjustment
# ---------------------------------------------------------------------------

def find_structural_sl(
    direction: str,
    entry: float,
    atr_sl: float,
    swing_levels: Dict[str, List[float]],
    round_numbers: List[float],
    atr_val: float,
    min_atr_mult: float = 0.7,
    max_atr_mult: float = 1.3,
) -> float:
    """Adjust the ATR-based SL to a nearby structural level.

    For LONG trades the SL must sit below *entry*.  We look for the nearest
    swing low or round number between ``entry - atr_val * max_atr_mult`` and
    ``entry - atr_val * min_atr_mult`` and place the SL just below it (0.1 %
    buffer).

    For SHORT trades, mirror logic using swing highs above entry.

    If no structural level is found within the acceptable range the original
    *atr_sl* is returned unchanged.
    """
    direction_str = str(direction).upper()
    buffer_pct = 0.001  # 0.1 %

    if "LONG" in direction_str:
        lower_bound = entry - atr_val * max_atr_mult
        upper_bound = entry - atr_val * min_atr_mult
        candidates = swing_levels.get("swing_lows", []) + round_numbers
        valid = [lvl for lvl in candidates if lower_bound <= lvl <= upper_bound]
        if valid:
            best = max(valid)  # closest to entry → tightest SL
            return round(best * (1.0 - buffer_pct), 8)
    else:
        lower_bound = entry + atr_val * min_atr_mult
        upper_bound = entry + atr_val * max_atr_mult
        candidates = swing_levels.get("swing_highs", []) + round_numbers
        valid = [lvl for lvl in candidates if lower_bound <= lvl <= upper_bound]
        if valid:
            best = min(valid)  # closest to entry → tightest SL
            return round(best * (1.0 + buffer_pct), 8)

    return atr_sl


# ---------------------------------------------------------------------------
# Structural TP adjustment
# ---------------------------------------------------------------------------

def find_structural_tp(
    direction: str,
    entry: float,
    atr_tp: float,
    swing_levels: Dict[str, List[float]],
    round_numbers: List[float],
    atr_val: float,
) -> float:
    """Adjust TP1 to a nearby structural level.

    For LONG trades, look for the nearest resistance (swing high or round
    number) within 0.8–1.2 × the ATR TP distance.  If a structural level is
    *closer* than the ATR-based TP we take profit early (before resistance).
    If it is farther we keep the ATR-based TP to avoid reducing the target
    unnecessarily.

    For SHORT trades, mirror logic with swing lows as support.
    """
    direction_str = str(direction).upper()
    tp_dist = abs(atr_tp - entry)

    if "LONG" in direction_str:
        lower_bound = entry + tp_dist * 0.8
        upper_bound = entry + tp_dist * 1.2
        candidates = swing_levels.get("swing_highs", []) + round_numbers
        valid = [lvl for lvl in candidates if lower_bound <= lvl <= upper_bound]
        if valid:
            best = min(valid)  # closest resistance → take profit before it
            if best <= atr_tp:
                return round(best, 8)
    else:
        lower_bound = entry - tp_dist * 1.2
        upper_bound = entry - tp_dist * 0.8
        candidates = swing_levels.get("swing_lows", []) + round_numbers
        valid = [lvl for lvl in candidates if lower_bound <= lvl <= upper_bound]
        if valid:
            best = max(valid)  # closest support → take profit before it
            if best >= atr_tp:
                return round(best, 8)

    return atr_tp
