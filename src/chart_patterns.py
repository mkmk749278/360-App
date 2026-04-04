"""Chart pattern detection — computationally cheap OHLCV pattern recognition.

Detects the following patterns from raw OHLCV numpy arrays:

* **Double Top** — two similar peaks separated by a valley (bearish reversal)
* **Double Bottom** — two similar troughs separated by a peak (bullish reversal)
* **Bollinger Band Squeeze Breakout** — contraction then expansion of BB width
* **Ascending / Descending Triangle** — converging high/low trendlines

Candlestick reversal/continuation patterns (PR_05):

* **Bullish / Bearish Engulfing** — 2-bar reversal (LONG / SHORT, +8 pts)
* **Hammer / Shooting Star** — pin bar reversal (LONG / SHORT, +6 pts)
* **Doji** — indecision candle (NEUTRAL, −5 pts)
* **Morning Star / Evening Star** — 3-bar reversal (LONG / SHORT, +10 pts)
* **Three White Soldiers / Three Black Crows** — continuation (LONG / SHORT, +7 pts)

Harmonic patterns:

* **Gartley** — bullish/bearish harmonic (X-A-B-C-D with 61.8/78.6 retracements)
* **Butterfly** — bullish/bearish harmonic (X-A-B-C-D with 78.6/127–162 extension)

Structural patterns:

* **Head & Shoulders / Inverse H&S** — three-peak/trough reversal
* **Rising Wedge** — converging upward trendlines (bearish)
* **Falling Wedge** — converging downward trendlines (bullish)

Scoring:

* **score_candlestick_patterns** — composite score across all candlestick detectors

All functions return ``None`` when the pattern is not detected, or a ``dict``
describing the pattern when it is.  No I/O, pure-compute.

Confidence values (0–1) in the returned dicts reflect how cleanly the price
action matches the idealised pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
from numpy.typing import NDArray

from src.indicators import bollinger_bands
from src.utils import get_logger

log = get_logger("chart_patterns")


# ---------------------------------------------------------------------------
# Double Top / Double Bottom
# ---------------------------------------------------------------------------

def detect_double_top(
    high: NDArray,
    lookback: int = 50,
    tolerance_pct: float = 1.0,
) -> Optional[Dict]:
    """Detect a double-top formation (bearish reversal).

    Parameters
    ----------
    high:
        Array of high prices.
    lookback:
        Number of most-recent candles to scan.
    tolerance_pct:
        Maximum percentage difference between the two peaks for them to be
        considered equal (e.g. 1.0 = peaks within 1% of each other).

    Returns
    -------
    dict or None
        ``{"pattern": "DOUBLE_TOP", "peak1_idx": int, "peak2_idx": int,
           "peak1": float, "peak2": float, "neckline": float,
           "confidence": float}``
        or ``None`` if the pattern is not detected.
    """
    arr = np.asarray(high, dtype=np.float64)
    n = len(arr)
    if n < lookback:
        return None

    window = arr[-lookback:]
    n_w = len(window)

    # Find all local maxima (peaks) in the window
    peaks: List[int] = []
    for i in range(1, n_w - 1):
        if window[i] >= window[i - 1] and window[i] >= window[i + 1]:
            peaks.append(i)

    if len(peaks) < 2:
        return None

    # Find the two highest peaks that are at least 10 candles apart
    peaks_sorted = sorted(peaks, key=lambda i: window[i], reverse=True)
    best: Optional[Dict] = None

    for idx_a in range(len(peaks_sorted)):
        for idx_b in range(idx_a + 1, len(peaks_sorted)):
            pa, pb = peaks_sorted[idx_a], peaks_sorted[idx_b]
            # Ensure minimum separation
            if abs(pa - pb) < 10:
                continue
            p1, p2 = (pa, pb) if pa < pb else (pb, pa)
            price1, price2 = window[p1], window[p2]

            # Check peaks are within tolerance
            diff_pct = abs(price1 - price2) / max(price1, price2) * 100.0
            if diff_pct > tolerance_pct:
                continue

            # Find valley between the two peaks (minimum between them)
            valley_val = float(np.min(window[p1:p2 + 1]))
            peak_avg = (price1 + price2) / 2.0
            valley_drop_pct = (peak_avg - valley_val) / peak_avg * 100.0
            if valley_drop_pct < 2.0:
                continue

            # Confidence: 1 minus the normalised peak difference (0→perfect)
            confidence = round(1.0 - diff_pct / tolerance_pct, 3)

            # Convert back to original array indices
            offset = n - lookback
            result = {
                "pattern": "DOUBLE_TOP",
                "peak1_idx": p1 + offset,
                "peak2_idx": p2 + offset,
                "peak1": float(price1),
                "peak2": float(price2),
                "neckline": valley_val,
                "confidence": confidence,
            }
            if best is None or confidence > best["confidence"]:
                best = result

    return best


def detect_double_bottom(
    low: NDArray,
    lookback: int = 50,
    tolerance_pct: float = 1.0,
) -> Optional[Dict]:
    """Detect a double-bottom formation (bullish reversal).

    Parameters
    ----------
    low:
        Array of low prices.
    lookback:
        Number of most-recent candles to scan.
    tolerance_pct:
        Maximum percentage difference between the two troughs.

    Returns
    -------
    dict or None
        ``{"pattern": "DOUBLE_BOTTOM", "trough1_idx": int, "trough2_idx": int,
           "trough1": float, "trough2": float, "neckline": float,
           "confidence": float}``
        or ``None`` if the pattern is not detected.
    """
    arr = np.asarray(low, dtype=np.float64)
    n = len(arr)
    if n < lookback:
        return None

    window = arr[-lookback:]
    n_w = len(window)

    # Find all local minima (troughs) in the window
    troughs: List[int] = []
    for i in range(1, n_w - 1):
        if window[i] <= window[i - 1] and window[i] <= window[i + 1]:
            troughs.append(i)

    if len(troughs) < 2:
        return None

    troughs_sorted = sorted(troughs, key=lambda i: window[i])
    best: Optional[Dict] = None

    for idx_a in range(len(troughs_sorted)):
        for idx_b in range(idx_a + 1, len(troughs_sorted)):
            ta, tb = troughs_sorted[idx_a], troughs_sorted[idx_b]
            if abs(ta - tb) < 10:
                continue
            t1, t2 = (ta, tb) if ta < tb else (tb, ta)
            price1, price2 = window[t1], window[t2]

            diff_pct = abs(price1 - price2) / max(abs(price1), abs(price2), 1e-10) * 100.0
            if diff_pct > tolerance_pct:
                continue

            # Peak between the troughs must be at least 2% above
            peak_val = float(np.max(window[t1:t2 + 1]))
            trough_avg = (price1 + price2) / 2.0
            peak_rise_pct = (peak_val - trough_avg) / max(abs(trough_avg), 1e-10) * 100.0
            if peak_rise_pct < 2.0:
                continue

            confidence = round(1.0 - diff_pct / tolerance_pct, 3)
            offset = n - lookback
            result = {
                "pattern": "DOUBLE_BOTTOM",
                "trough1_idx": t1 + offset,
                "trough2_idx": t2 + offset,
                "trough1": float(price1),
                "trough2": float(price2),
                "neckline": peak_val,
                "confidence": confidence,
            }
            if best is None or confidence > best["confidence"]:
                best = result

    return best


# ---------------------------------------------------------------------------
# Bollinger Band Squeeze Breakout
# ---------------------------------------------------------------------------

def detect_bollinger_squeeze(
    close: NDArray,
    period: int = 20,
    squeeze_threshold: float = 0.02,
) -> Optional[Dict]:
    """Detect a Bollinger Band squeeze followed by an expansion (breakout).

    Parameters
    ----------
    close:
        Array of closing prices.
    period:
        Bollinger Band period (default 20).
    squeeze_threshold:
        Maximum BB width (``(upper−lower)/middle``) that qualifies as
        squeezed.  Default 0.02 (2%).

    Returns
    -------
    dict or None
        ``{"pattern": "BB_SQUEEZE", "squeeze_width": float,
           "expansion_direction": "UP" | "DOWN", "confidence": float}``
        or ``None`` if the pattern is not detected.
    """
    arr = np.asarray(close, dtype=np.float64)
    if len(arr) < period + 10:
        return None

    upper, mid, lower = bollinger_bands(arr, period)

    # Compute BB width for all valid candles
    with np.errstate(divide="ignore", invalid="ignore"):
        width = np.where(mid != 0, (upper - lower) / mid, np.nan)

    valid_width = width[~np.isnan(width)]
    if len(valid_width) < 10:
        return None

    # Check that the width contracted below threshold in the last 10 candles
    recent_width = valid_width[-10:]
    min_width = float(np.min(recent_width))
    if min_width >= squeeze_threshold:
        return None

    # Check that width is now expanding (most recent > minimum in the window)
    current_width = float(valid_width[-1])
    squeeze_width = min_width

    # Direction: did price close above upper band or below lower band?
    last_close = float(arr[-1])
    last_upper = float(upper[-1]) if not np.isnan(upper[-1]) else float("inf")
    last_lower = float(lower[-1]) if not np.isnan(lower[-1]) else float("-inf")

    if current_width <= min_width * 1.05:
        # Width not yet expanding — still in squeeze, no breakout yet
        return None

    if last_close > last_upper:
        direction = "UP"
    elif last_close < last_lower:
        direction = "DOWN"
    else:
        direction = "UP" if arr[-1] > arr[-2] else "DOWN"

    # Confidence: how far did width expand relative to squeeze depth
    expansion_pct = (current_width - squeeze_width) / max(squeeze_threshold, 1e-10)
    confidence = round(min(expansion_pct, 1.0), 3)

    return {
        "pattern": "BB_SQUEEZE",
        "squeeze_width": round(squeeze_width, 5),
        "expansion_direction": direction,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Ascending / Descending Triangle
# ---------------------------------------------------------------------------

def detect_triangle(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    lookback: int = 50,
) -> Optional[Dict]:
    """Detect an ascending or descending triangle pattern.

    * **Ascending triangle**: flat resistance (highs converging horizontally)
      with rising support (lows trending upward).
    * **Descending triangle**: flat support with falling resistance.

    Parameters
    ----------
    high:
        Array of high prices.
    low:
        Array of low prices.
    close:
        Array of close prices.
    lookback:
        Number of most-recent candles to analyse.

    Returns
    -------
    dict or None
        ``{"pattern": "ASCENDING_TRIANGLE" | "DESCENDING_TRIANGLE",
           "resistance": float, "support": float, "confidence": float}``
        or ``None`` if neither pattern is detected.
    """
    h = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)
    n = len(h)
    if n < lookback:
        return None

    h_w = h[-lookback:]
    lo_w = lo[-lookback:]
    x = np.arange(len(h_w), dtype=np.float64)

    # Fit linear regression to highs and lows separately
    high_slope, high_intercept = np.polyfit(x, h_w, 1)
    low_slope, low_intercept = np.polyfit(x, lo_w, 1)

    resistance = float(high_intercept + high_slope * (len(h_w) - 1))
    support = float(low_intercept + low_slope * (len(h_w) - 1))

    # Normalise slopes relative to price
    mid_price = float(np.mean(np.concatenate([h_w, lo_w])))
    if mid_price <= 0:
        return None
    norm_high_slope = high_slope / mid_price * lookback
    norm_low_slope = low_slope / mid_price * lookback

    # Ascending triangle: flat or slight resistance (|high_slope| < threshold)
    # and rising support (positive low_slope)
    flat_threshold = 0.005  # < 0.5% drift over lookback candles = "flat"
    if abs(norm_high_slope) < flat_threshold and norm_low_slope > flat_threshold:
        confidence = round(min(norm_low_slope / 0.02, 1.0), 3)
        return {
            "pattern": "ASCENDING_TRIANGLE",
            "resistance": resistance,
            "support": support,
            "confidence": confidence,
        }

    # Descending triangle: falling resistance and flat support
    if norm_high_slope < -flat_threshold and abs(norm_low_slope) < flat_threshold:
        confidence = round(min(abs(norm_high_slope) / 0.02, 1.0), 3)
        return {
            "pattern": "DESCENDING_TRIANGLE",
            "resistance": resistance,
            "support": support,
            "confidence": confidence,
        }

    return None


# ---------------------------------------------------------------------------
# Aggregate helper — detects all patterns in one pass
# ---------------------------------------------------------------------------

def detect_patterns(candles: Dict) -> List[Dict]:
    """Run all pattern detectors on a single-timeframe candle dict.

    Parameters
    ----------
    candles:
        Dict with ``"high"``, ``"low"``, ``"close"`` keys (numpy arrays or
        lists).  Missing keys are handled gracefully.

    Returns
    -------
    list of dict
        List of detected pattern dicts (may be empty).  Each dict contains
        at minimum ``"pattern"`` and ``"confidence"`` keys.
    """
    results: List[Dict] = []
    try:
        h = np.asarray(candles.get("high", []), dtype=np.float64).ravel()
        lo = np.asarray(candles.get("low", []), dtype=np.float64).ravel()
        c = np.asarray(candles.get("close", []), dtype=np.float64).ravel()

        for detector, args in [
            (detect_double_top, (h,)),
            (detect_double_bottom, (lo,)),
            (detect_bollinger_squeeze, (c,)),
            (detect_triangle, (h, lo, c)),
        ]:
            try:
                result = detector(*args)  # type: ignore[operator]
                if result is not None:
                    results.append(result)
            except Exception as exc:
                log.debug("Pattern detector error: {}", exc)
    except Exception as exc:
        log.debug("detect_patterns failed: {}", exc)
    return results


# ---------------------------------------------------------------------------
# PR_05 — Candlestick Pattern Engine
# ---------------------------------------------------------------------------

@dataclass
class PatternResult:
    """Result of a single candlestick pattern detection.

    Attributes
    ----------
    name:
        Pattern identifier, e.g. ``"BULLISH_ENGULFING"``, ``"HAMMER"``.
    direction:
        ``"LONG"``, ``"SHORT"``, or ``"NEUTRAL"``.
    confidence_bonus:
        Points added (positive) or subtracted (negative) from the signal score.
    """

    name: str
    direction: str
    confidence_bonus: float


# -- Private helpers --------------------------------------------------------

def _cp_body(open_: float, close: float) -> float:
    return abs(close - open_)


def _cp_range(high: float, low: float) -> float:
    return high - low if high > low else 1e-9


def _cp_upper_wick(open_: float, high: float, close: float) -> float:
    return high - max(open_, close)


def _cp_lower_wick(open_: float, low: float, close: float) -> float:
    return min(open_, close) - low


# -- Candlestick detectors --------------------------------------------------

def detect_engulfing(
    opens: NDArray,
    highs: NDArray,
    lows: NDArray,
    closes: NDArray,
) -> List[PatternResult]:
    """Detect bullish/bearish engulfing on the last two candles.

    Parameters
    ----------
    opens, highs, lows, closes:
        OHLC arrays (numpy or list).  Must contain at least 2 elements.

    Returns
    -------
    list of PatternResult
        Zero, one, or two results (bullish and/or bearish may both fire on
        pathological data, though in practice at most one fires).
    """
    o = np.asarray(opens, dtype=np.float64).ravel()
    c = np.asarray(closes, dtype=np.float64).ravel()
    if len(c) < 2:
        return []
    o1, c1 = float(o[-2]), float(c[-2])
    o2, c2 = float(o[-1]), float(c[-1])
    results: List[PatternResult] = []
    # Bullish engulfing: prior candle bearish, current candle bullish and body fully engulfs
    if c1 < o1 and c2 > o2 and c2 > o1 and o2 < c1:
        results.append(PatternResult("BULLISH_ENGULFING", "LONG", 8.0))
    # Bearish engulfing: prior candle bullish, current candle bearish and body fully engulfs
    if c1 > o1 and c2 < o2 and c2 < o1 and o2 > c1:
        results.append(PatternResult("BEARISH_ENGULFING", "SHORT", 8.0))
    return results


def detect_pin_bar(
    opens: NDArray,
    highs: NDArray,
    lows: NDArray,
    closes: NDArray,
) -> List[PatternResult]:
    """Detect hammer (bullish pin bar) and shooting star (bearish pin bar).

    Parameters
    ----------
    opens, highs, lows, closes:
        OHLC arrays.  Only the last candle is inspected.

    Returns
    -------
    list of PatternResult
    """
    o_arr = np.asarray(opens, dtype=np.float64).ravel()
    h_arr = np.asarray(highs, dtype=np.float64).ravel()
    lo_arr = np.asarray(lows, dtype=np.float64).ravel()
    c_arr = np.asarray(closes, dtype=np.float64).ravel()
    if len(c_arr) < 1:
        return []
    o, h, lo, c = float(o_arr[-1]), float(h_arr[-1]), float(lo_arr[-1]), float(c_arr[-1])
    body = _cp_body(o, c)
    candle_range = _cp_range(h, lo)
    lower_wick = _cp_lower_wick(o, lo, c)
    upper_wick = _cp_upper_wick(o, h, c)
    results: List[PatternResult] = []
    if candle_range > 0:
        # Hammer: long lower wick (≥2× body), short upper wick (<body)
        if lower_wick >= body * 2.0 and upper_wick < body:
            results.append(PatternResult("HAMMER", "LONG", 6.0))
        # Shooting star: long upper wick (≥2× body), short lower wick (<body)
        if upper_wick >= body * 2.0 and lower_wick < body:
            results.append(PatternResult("SHOOTING_STAR", "SHORT", 6.0))
    return results


def detect_doji(
    opens: NDArray,
    highs: NDArray,
    lows: NDArray,
    closes: NDArray,
    body_threshold_pct: float = 0.1,
) -> List[PatternResult]:
    """Detect a doji candle (body < *body_threshold_pct* of total range).

    A doji signals indecision and applies a confidence *penalty* (negative bonus).

    Parameters
    ----------
    opens, highs, lows, closes:
        OHLC arrays.  Only the last candle is inspected.
    body_threshold_pct:
        Maximum body-to-range ratio that qualifies as a doji (default 0.10).

    Returns
    -------
    list of PatternResult
        Empty list when no doji; single ``PatternResult("DOJI", "NEUTRAL", -5.0)``
        when detected.
    """
    o_arr = np.asarray(opens, dtype=np.float64).ravel()
    h_arr = np.asarray(highs, dtype=np.float64).ravel()
    lo_arr = np.asarray(lows, dtype=np.float64).ravel()
    c_arr = np.asarray(closes, dtype=np.float64).ravel()
    if len(c_arr) < 1:
        return []
    o, h, lo, c = float(o_arr[-1]), float(h_arr[-1]), float(lo_arr[-1]), float(c_arr[-1])
    body = _cp_body(o, c)
    candle_range = _cp_range(h, lo)
    if candle_range > 0 and body / candle_range < body_threshold_pct:
        return [PatternResult("DOJI", "NEUTRAL", -5.0)]
    return []


def detect_morning_evening_star(
    opens: NDArray,
    highs: NDArray,
    lows: NDArray,
    closes: NDArray,
) -> List[PatternResult]:
    """Detect 3-bar morning star (LONG) and evening star (SHORT).

    Parameters
    ----------
    opens, highs, lows, closes:
        OHLC arrays.  Must contain at least 3 elements.

    Returns
    -------
    list of PatternResult
    """
    o_arr = np.asarray(opens, dtype=np.float64).ravel()
    c_arr = np.asarray(closes, dtype=np.float64).ravel()
    if len(c_arr) < 3:
        return []
    o1, c1 = float(o_arr[-3]), float(c_arr[-3])
    o2, c2 = float(o_arr[-2]), float(c_arr[-2])
    o3, c3 = float(o_arr[-1]), float(c_arr[-1])
    results: List[PatternResult] = []
    body1 = _cp_body(o1, c1)
    body2 = _cp_body(o2, c2)
    # Morning star: large bearish → small indecision → large bullish, closes above midpoint
    if (c1 < o1 and body2 < body1 * 0.5 and c3 > o3 and c3 > (o1 + c1) / 2):
        results.append(PatternResult("MORNING_STAR", "LONG", 10.0))
    # Evening star: large bullish → small indecision → large bearish, closes below midpoint
    if (c1 > o1 and body2 < body1 * 0.5 and c3 < o3 and c3 < (o1 + c1) / 2):
        results.append(PatternResult("EVENING_STAR", "SHORT", 10.0))
    return results


def detect_three_soldiers_crows(
    opens: NDArray,
    closes: NDArray,
) -> List[PatternResult]:
    """Detect three white soldiers (LONG) and three black crows (SHORT).

    Parameters
    ----------
    opens, closes:
        Open and close arrays.  Must contain at least 3 elements.

    Returns
    -------
    list of PatternResult
    """
    o_arr = np.asarray(opens, dtype=np.float64).ravel()
    c_arr = np.asarray(closes, dtype=np.float64).ravel()
    if len(c_arr) < 3:
        return []
    c1, c2, c3 = float(c_arr[-3]), float(c_arr[-2]), float(c_arr[-1])
    o1, o2, o3 = float(o_arr[-3]), float(o_arr[-2]), float(o_arr[-1])
    results: List[PatternResult] = []
    # Three white soldiers: 3 consecutive bullish candles, each closes higher
    if c3 > c2 > c1 and o3 > o2 > o1 and c1 > o1 and c2 > o2 and c3 > o3:
        results.append(PatternResult("THREE_WHITE_SOLDIERS", "LONG", 7.0))
    # Three black crows: 3 consecutive bearish candles, each closes lower
    if c3 < c2 < c1 and o3 < o2 < o1 and c1 < o1 and c2 < o2 and c3 < o3:
        results.append(PatternResult("THREE_BLACK_CROWS", "SHORT", 7.0))
    return results


def detect_all_patterns(
    opens: NDArray,
    highs: NDArray,
    lows: NDArray,
    closes: NDArray,
    volume_arr: Optional[NDArray] = None,
) -> List[PatternResult]:
    """Run all candlestick pattern detectors and return combined results.

    Parameters
    ----------
    opens, highs, lows, closes:
        OHLC arrays (numpy or list).
    volume_arr:
        Optional volume array (currently unused; reserved for future volume-
        confirmation filters).

    Returns
    -------
    list of PatternResult
        All detected patterns, potentially empty.  Each element has ``name``,
        ``direction`` (``"LONG"``, ``"SHORT"``, or ``"NEUTRAL"``), and
        ``confidence_bonus`` attributes.
    """
    results: List[PatternResult] = []
    try:
        for fn in (detect_engulfing, detect_pin_bar, detect_doji, detect_morning_evening_star):
            try:
                results.extend(fn(opens, highs, lows, closes))
            except Exception as exc:
                log.debug("Candlestick detector {} error: {}", fn.__name__, exc)
        try:
            results.extend(detect_three_soldiers_crows(opens, closes))
        except Exception as exc:
            log.debug("Candlestick detector detect_three_soldiers_crows error: {}", exc)
    except Exception as exc:
        log.debug("detect_all_patterns failed: {}", exc)
    return results


def pattern_confidence_bonus(patterns: List[Dict], direction: str) -> float:
    """Compute a confidence bonus based on detected confirming patterns.

    Parameters
    ----------
    patterns:
        List of detected pattern dicts from :func:`detect_patterns`.
    direction:
        ``"LONG"`` or ``"SHORT"`` — signal direction to align against.

    Returns
    -------
    float
        Confidence bonus in the range [0, 5].  Confirming patterns (e.g.
        double bottom for LONG, double top for SHORT) each contribute up to
        +3 points; contradicting patterns each contribute −1.5 points.
        The total is clamped to [0, 5].
    """
    bonus = 0.0
    bullish_patterns = {"DOUBLE_BOTTOM", "ASCENDING_TRIANGLE"}
    bearish_patterns = {"DOUBLE_TOP", "DESCENDING_TRIANGLE"}

    for p in patterns:
        name = p.get("pattern", "")
        conf = float(p.get("confidence", 0.5))
        if direction == "LONG":
            if name in bullish_patterns:
                bonus += conf * 3.0
            elif name in bearish_patterns:
                bonus -= 1.5
        elif direction == "SHORT":
            if name in bearish_patterns:
                bonus += conf * 3.0
            elif name in bullish_patterns:
                bonus -= 1.5
        # BB_SQUEEZE is direction-neutral (direction comes from expansion_direction)
        if name == "BB_SQUEEZE":
            exp_dir = p.get("expansion_direction", "")
            if (direction == "LONG" and exp_dir == "UP") or (
                direction == "SHORT" and exp_dir == "DOWN"
            ):
                bonus += conf * 2.0

    return round(max(0.0, min(bonus, 5.0)), 2)


# ---------------------------------------------------------------------------
# Swing-point helpers (shared by harmonic & structural patterns)
# ---------------------------------------------------------------------------

def _find_swing_highs(high: NDArray, order: int = 5) -> List[int]:
    """Return indices of swing highs (local maxima with *order* bars on each side)."""
    arr = np.asarray(high, dtype=np.float64).ravel()
    swings: List[int] = []
    for i in range(order, len(arr) - order):
        if all(arr[i] >= arr[i - j] for j in range(1, order + 1)) and all(
            arr[i] >= arr[i + j] for j in range(1, order + 1)
        ):
            swings.append(i)
    return swings


def _find_swing_lows(low: NDArray, order: int = 5) -> List[int]:
    """Return indices of swing lows (local minima with *order* bars on each side)."""
    arr = np.asarray(low, dtype=np.float64).ravel()
    swings: List[int] = []
    for i in range(order, len(arr) - order):
        if all(arr[i] <= arr[i - j] for j in range(1, order + 1)) and all(
            arr[i] <= arr[i + j] for j in range(1, order + 1)
        ):
            swings.append(i)
    return swings


def _merge_swing_points(
    high: NDArray, low: NDArray, order: int = 5,
) -> List[tuple]:
    """Return swing points as ``(index, price, 'H'|'L')`` sorted by index."""
    h = np.asarray(high, dtype=np.float64).ravel()
    lo = np.asarray(low, dtype=np.float64).ravel()
    points: List[tuple] = []
    for i in _find_swing_highs(h, order):
        points.append((i, float(h[i]), "H"))
    for i in _find_swing_lows(lo, order):
        points.append((i, float(lo[i]), "L"))
    points.sort(key=lambda p: p[0])
    return points


def _ratio_within(actual: float, expected: float, tolerance: float = 0.05) -> bool:
    """Check if *actual* ratio is within ±*tolerance* of *expected*."""
    return abs(actual - expected) <= tolerance


def _ratio_in_range(
    actual: float, lo: float, hi: float, tolerance: float = 0.05,
) -> bool:
    """Check if *actual* ratio is within [lo − tol, hi + tol]."""
    return (lo - tolerance) <= actual <= (hi + tolerance)


# ---------------------------------------------------------------------------
# Harmonic Patterns — Gartley
# ---------------------------------------------------------------------------

def detect_gartley_pattern(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    lookback: int = 100,
) -> Optional[Dict]:
    """Detect a Gartley harmonic pattern (X-A-B-C-D).

    Bullish Gartley
    ~~~~~~~~~~~~~~~
    XA leg moves **up**, then:
    * AB retraces **61.8 %** of XA
    * BC retraces **38.2 – 88.6 %** of AB
    * CD completes at **78.6 %** retracement of XA

    Bearish Gartley
    ~~~~~~~~~~~~~~~~
    XA leg moves **down**, same Fibonacci ratios inverted.

    Parameters
    ----------
    high, low, close:
        OHLCV price arrays (numpy).
    lookback:
        Number of most-recent candles to scan for the pattern.

    Returns
    -------
    dict or None
        ``{"pattern": "GARTLEY_BULLISH" | "GARTLEY_BEARISH",
           "confidence": float, "completion_price": float,
           "target": float, "stop_loss": float}``
        or ``None`` if the pattern is not detected.
    """
    h = np.asarray(high, dtype=np.float64).ravel()
    lo = np.asarray(low, dtype=np.float64).ravel()
    n = len(h)
    if n < lookback:
        return None

    start = max(0, n - lookback)
    h_w = h[start:]
    lo_w = lo[start:]

    swings = _merge_swing_points(h_w, lo_w, order=3)
    if len(swings) < 5:
        return None

    tol = 0.05
    best: Optional[Dict] = None

    for i in range(len(swings) - 4):
        X, A, B, C, D = swings[i : i + 5]

        xa = A[1] - X[1]
        if abs(xa) < 1e-9:
            continue

        ab = B[1] - A[1]
        bc = C[1] - B[1]

        ab_ratio = abs(ab / xa)
        bc_ratio = abs(bc / ab) if abs(ab) > 1e-9 else 999.0
        d_retracement = abs(D[1] - A[1]) / abs(xa)

        if not _ratio_within(ab_ratio, 0.618, tol):
            continue
        if not _ratio_in_range(bc_ratio, 0.382, 0.886, tol):
            continue
        if not _ratio_within(d_retracement, 0.786, tol):
            continue

        # Directions must alternate
        if xa > 0 and ab > 0:
            continue
        if xa < 0 and ab < 0:
            continue

        bullish = xa > 0
        pattern_name = "GARTLEY_BULLISH" if bullish else "GARTLEY_BEARISH"

        # Confidence based on how close ratios are to ideal
        err_ab = abs(ab_ratio - 0.618) / 0.618
        err_d = abs(d_retracement - 0.786) / 0.786
        confidence = round(max(0.0, min(1.0 - (err_ab + err_d), 1.0)), 3)

        completion = float(D[1])
        ad_range = abs(A[1] - D[1])
        if bullish:
            target = float(completion + ad_range * 0.618)
            stop_loss = float(X[1] - ad_range * 0.1)
        else:
            target = float(completion - ad_range * 0.618)
            stop_loss = float(X[1] + ad_range * 0.1)

        result = {
            "pattern": pattern_name,
            "confidence": confidence,
            "completion_price": completion,
            "target": round(target, 5),
            "stop_loss": round(stop_loss, 5),
        }
        if best is None or confidence > best["confidence"]:
            best = result

    return best


# ---------------------------------------------------------------------------
# Harmonic Patterns — Butterfly
# ---------------------------------------------------------------------------

def detect_butterfly_pattern(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    lookback: int = 100,
) -> Optional[Dict]:
    """Detect a Butterfly harmonic pattern (X-A-B-C-D).

    Bullish Butterfly
    ~~~~~~~~~~~~~~~~~
    XA leg moves **up**, then:
    * AB retraces **78.6 %** of XA
    * BC retraces **38.2 – 88.6 %** of AB
    * CD extends **127.2 – 161.8 %** of XA (beyond X)

    Bearish Butterfly
    ~~~~~~~~~~~~~~~~~
    XA leg moves **down**, same ratios inverted.

    Parameters
    ----------
    high, low, close:
        OHLCV price arrays (numpy).
    lookback:
        Number of most-recent candles to scan for the pattern.

    Returns
    -------
    dict or None
        ``{"pattern": "BUTTERFLY_BULLISH" | "BUTTERFLY_BEARISH",
           "confidence": float, "completion_price": float,
           "target": float, "stop_loss": float}``
        or ``None`` if the pattern is not detected.
    """
    h = np.asarray(high, dtype=np.float64).ravel()
    lo = np.asarray(low, dtype=np.float64).ravel()
    n = len(h)
    if n < lookback:
        return None

    start = max(0, n - lookback)
    h_w = h[start:]
    lo_w = lo[start:]

    swings = _merge_swing_points(h_w, lo_w, order=3)
    if len(swings) < 5:
        return None

    tol = 0.05
    best: Optional[Dict] = None

    for i in range(len(swings) - 4):
        X, A, B, C, D = swings[i : i + 5]

        xa = A[1] - X[1]
        if abs(xa) < 1e-9:
            continue

        ab = B[1] - A[1]
        bc = C[1] - B[1]

        ab_ratio = abs(ab / xa)
        bc_ratio = abs(bc / ab) if abs(ab) > 1e-9 else 999.0
        # CD extends beyond X: measure D relative to X as ratio of |XA|
        d_extension = abs(D[1] - A[1]) / abs(xa)

        if not _ratio_within(ab_ratio, 0.786, tol):
            continue
        if not _ratio_in_range(bc_ratio, 0.382, 0.886, tol):
            continue
        if not _ratio_in_range(d_extension, 1.272, 1.618, tol):
            continue

        if xa > 0 and ab > 0:
            continue
        if xa < 0 and ab < 0:
            continue

        bullish = xa > 0
        pattern_name = "BUTTERFLY_BULLISH" if bullish else "BUTTERFLY_BEARISH"

        err_ab = abs(ab_ratio - 0.786) / 0.786
        mid_ext = (1.272 + 1.618) / 2.0
        err_d = abs(d_extension - mid_ext) / mid_ext
        confidence = round(max(0.0, min(1.0 - (err_ab + err_d), 1.0)), 3)

        completion = float(D[1])
        ad_range = abs(A[1] - D[1])
        if bullish:
            target = float(completion + ad_range * 0.618)
            stop_loss = float(D[1] - ad_range * 0.1)
        else:
            target = float(completion - ad_range * 0.618)
            stop_loss = float(D[1] + ad_range * 0.1)

        result = {
            "pattern": pattern_name,
            "confidence": confidence,
            "completion_price": completion,
            "target": round(target, 5),
            "stop_loss": round(stop_loss, 5),
        }
        if best is None or confidence > best["confidence"]:
            best = result

    return best


# ---------------------------------------------------------------------------
# Candlestick Pattern Scoring
# ---------------------------------------------------------------------------

def score_candlestick_patterns(
    open_arr: NDArray,
    high: NDArray,
    low: NDArray,
    close: NDArray,
    volume: Optional[NDArray] = None,
) -> Dict[str, object]:
    """Run ALL candlestick pattern detectors and produce a composite score.

    Parameters
    ----------
    open_arr, high, low, close:
        OHLC arrays (numpy or list).
    volume:
        Optional volume array.  When the pattern candle has above-average
        volume the raw score is boosted by 20 %.

    Returns
    -------
    dict
        ``{"total_score": float, "patterns_detected": list[str],
           "direction_bias": str, "pattern_count": int,
           "strongest_pattern": str}``

        *total_score* ranges from approximately −20 to +30.
        *direction_bias* is ``"BULLISH"``, ``"BEARISH"``, or ``"NEUTRAL"``.
    """
    o = np.asarray(open_arr, dtype=np.float64).ravel()
    h = np.asarray(high, dtype=np.float64).ravel()
    lo = np.asarray(low, dtype=np.float64).ravel()
    c = np.asarray(close, dtype=np.float64).ravel()

    # Score weights per pattern name
    _WEIGHTS: Dict[str, float] = {
        "MORNING_STAR": 10.0,
        "EVENING_STAR": -10.0,
        "BULLISH_ENGULFING": 8.0,
        "BEARISH_ENGULFING": -8.0,
        "THREE_WHITE_SOLDIERS": 7.0,
        "THREE_BLACK_CROWS": -7.0,
        "HAMMER": 6.0,
        "SHOOTING_STAR": -6.0,
        "DOJI": -5.0,
    }

    all_results: List[PatternResult] = detect_all_patterns(o, h, lo, c)

    total_score = 0.0
    patterns_detected: List[str] = []
    strongest_name = ""
    strongest_abs = 0.0

    for pr in all_results:
        weight = _WEIGHTS.get(pr.name, 0.0)
        total_score += weight
        patterns_detected.append(pr.name)
        if abs(weight) > strongest_abs:
            strongest_abs = abs(weight)
            strongest_name = pr.name

    # Volume boost: if volume provided and last candle is above average
    if volume is not None and len(patterns_detected) > 0:
        vol = np.asarray(volume, dtype=np.float64).ravel()
        if len(vol) >= 2:
            avg_vol = float(np.mean(vol))
            if avg_vol > 0 and float(vol[-1]) > avg_vol:
                total_score *= 1.2

    total_score = round(max(-20.0, min(total_score, 30.0)), 2)

    if total_score > 0:
        direction_bias = "BULLISH"
    elif total_score < 0:
        direction_bias = "BEARISH"
    else:
        direction_bias = "NEUTRAL"

    return {
        "total_score": total_score,
        "patterns_detected": patterns_detected,
        "direction_bias": direction_bias,
        "pattern_count": len(patterns_detected),
        "strongest_pattern": strongest_name,
    }


# ---------------------------------------------------------------------------
# Head & Shoulders
# ---------------------------------------------------------------------------

def detect_head_and_shoulders(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    lookback: int = 60,
) -> Optional[Dict]:
    """Detect a head-and-shoulders or inverse head-and-shoulders pattern.

    Classic H&S (bearish reversal)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Three peaks where the middle peak (head) is the highest and the two
    outer peaks (shoulders) are lower and roughly equal.

    Inverse H&S (bullish reversal)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Three troughs where the middle trough (head) is the lowest and the two
    outer troughs (shoulders) are higher and roughly equal.

    Parameters
    ----------
    high, low, close:
        Price arrays (numpy).
    lookback:
        Number of most-recent candles to scan.

    Returns
    -------
    dict or None
        ``{"pattern": "HEAD_AND_SHOULDERS" | "INVERSE_HEAD_AND_SHOULDERS",
           "neckline": float, "target": float, "confidence": float}``
        or ``None`` if the pattern is not detected.
    """
    h = np.asarray(high, dtype=np.float64).ravel()
    lo = np.asarray(low, dtype=np.float64).ravel()
    n = len(h)
    if n < lookback:
        return None

    start = max(0, n - lookback)
    h_w = h[start:]
    lo_w = lo[start:]

    best: Optional[Dict] = None

    # --- Classic H&S (peaks) ---
    peaks = _find_swing_highs(h_w, order=3)
    if len(peaks) >= 3:
        for i in range(len(peaks) - 2):
            ls_idx, head_idx, rs_idx = peaks[i], peaks[i + 1], peaks[i + 2]
            ls_price = float(h_w[ls_idx])
            head_price = float(h_w[head_idx])
            rs_price = float(h_w[rs_idx])

            # Head must be higher than both shoulders
            if head_price <= ls_price or head_price <= rs_price:
                continue

            # Shoulders roughly equal (within 5% of each other)
            shoulder_avg = (ls_price + rs_price) / 2.0
            if shoulder_avg <= 0:
                continue
            diff_pct = abs(ls_price - rs_price) / shoulder_avg
            if diff_pct > 0.05:
                continue

            # Neckline: average of the troughs between shoulders and head
            trough_left = float(np.min(lo_w[ls_idx:head_idx + 1]))
            trough_right = float(np.min(lo_w[head_idx:rs_idx + 1]))
            neckline = (trough_left + trough_right) / 2.0

            head_height = head_price - neckline
            target = neckline - head_height

            confidence = round(max(0.0, min(1.0 - diff_pct, 1.0)), 3)
            result = {
                "pattern": "HEAD_AND_SHOULDERS",
                "neckline": round(neckline, 5),
                "target": round(target, 5),
                "confidence": confidence,
            }
            if best is None or confidence > best["confidence"]:
                best = result

    # --- Inverse H&S (troughs) ---
    troughs = _find_swing_lows(lo_w, order=3)
    if len(troughs) >= 3:
        for i in range(len(troughs) - 2):
            ls_idx, head_idx, rs_idx = troughs[i], troughs[i + 1], troughs[i + 2]
            ls_price = float(lo_w[ls_idx])
            head_price = float(lo_w[head_idx])
            rs_price = float(lo_w[rs_idx])

            # Head must be lower than both shoulders
            if head_price >= ls_price or head_price >= rs_price:
                continue

            shoulder_avg = (ls_price + rs_price) / 2.0
            if shoulder_avg <= 0:
                continue
            diff_pct = abs(ls_price - rs_price) / shoulder_avg
            if diff_pct > 0.05:
                continue

            peak_left = float(np.max(h_w[ls_idx:head_idx + 1]))
            peak_right = float(np.max(h_w[head_idx:rs_idx + 1]))
            neckline = (peak_left + peak_right) / 2.0

            head_depth = neckline - head_price
            target = neckline + head_depth

            confidence = round(max(0.0, min(1.0 - diff_pct, 1.0)), 3)
            result = {
                "pattern": "INVERSE_HEAD_AND_SHOULDERS",
                "neckline": round(neckline, 5),
                "target": round(target, 5),
                "confidence": confidence,
            }
            if best is None or confidence > best["confidence"]:
                best = result

    return best


# ---------------------------------------------------------------------------
# Rising Wedge (bearish)
# ---------------------------------------------------------------------------

def detect_rising_wedge(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    lookback: int = 40,
) -> Optional[Dict]:
    """Detect a rising-wedge pattern (bearish).

    Both highs and lows are making higher highs / higher lows, but the
    highs are rising **slower** than the lows — the two trendlines converge
    upward.

    Parameters
    ----------
    high, low, close:
        Price arrays (numpy).
    lookback:
        Number of most-recent candles to analyse.

    Returns
    -------
    dict or None
        ``{"pattern": "RISING_WEDGE", "breakout_level": float,
           "confidence": float}``
        or ``None`` if the pattern is not detected.
    """
    h = np.asarray(high, dtype=np.float64).ravel()
    lo = np.asarray(low, dtype=np.float64).ravel()
    n = len(h)
    if n < lookback:
        return None

    h_w = h[-lookback:]
    lo_w = lo[-lookback:]
    x = np.arange(lookback, dtype=np.float64)

    high_slope, high_intercept = np.polyfit(x, h_w, 1)
    low_slope, low_intercept = np.polyfit(x, lo_w, 1)

    mid_price = float(np.mean(np.concatenate([h_w, lo_w])))
    if mid_price <= 0:
        return None

    norm_high = high_slope / mid_price * lookback
    norm_low = low_slope / mid_price * lookback

    # Both slopes must be positive (rising)
    if norm_high <= 0 or norm_low <= 0:
        return None

    # Lows must rise faster than highs (converging)
    if norm_low <= norm_high:
        return None

    # Both must be meaningfully rising
    if norm_high < 0.002 or norm_low < 0.002:
        return None

    convergence = (norm_low - norm_high) / norm_low
    confidence = round(max(0.0, min(convergence, 1.0)), 3)

    breakout_level = float(low_intercept + low_slope * (lookback - 1))

    return {
        "pattern": "RISING_WEDGE",
        "breakout_level": round(breakout_level, 5),
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Falling Wedge (bullish)
# ---------------------------------------------------------------------------

def detect_falling_wedge(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    lookback: int = 40,
) -> Optional[Dict]:
    """Detect a falling-wedge pattern (bullish).

    Both highs and lows are making lower highs / lower lows, but the
    lows are falling **slower** than the highs — the two trendlines
    converge downward.

    Parameters
    ----------
    high, low, close:
        Price arrays (numpy).
    lookback:
        Number of most-recent candles to analyse.

    Returns
    -------
    dict or None
        ``{"pattern": "FALLING_WEDGE", "breakout_level": float,
           "confidence": float}``
        or ``None`` if the pattern is not detected.
    """
    h = np.asarray(high, dtype=np.float64).ravel()
    lo = np.asarray(low, dtype=np.float64).ravel()
    n = len(h)
    if n < lookback:
        return None

    h_w = h[-lookback:]
    lo_w = lo[-lookback:]
    x = np.arange(lookback, dtype=np.float64)

    high_slope, high_intercept = np.polyfit(x, h_w, 1)
    low_slope, low_intercept = np.polyfit(x, lo_w, 1)

    mid_price = float(np.mean(np.concatenate([h_w, lo_w])))
    if mid_price <= 0:
        return None

    norm_high = high_slope / mid_price * lookback
    norm_low = low_slope / mid_price * lookback

    # Both slopes must be negative (falling)
    if norm_high >= 0 or norm_low >= 0:
        return None

    # Highs must fall faster than lows (converging)
    if abs(norm_high) <= abs(norm_low):
        return None

    # Both must be meaningfully falling
    if abs(norm_high) < 0.002 or abs(norm_low) < 0.002:
        return None

    convergence = (abs(norm_high) - abs(norm_low)) / abs(norm_high)
    confidence = round(max(0.0, min(convergence, 1.0)), 3)

    breakout_level = float(high_intercept + high_slope * (lookback - 1))

    return {
        "pattern": "FALLING_WEDGE",
        "breakout_level": round(breakout_level, 5),
        "confidence": confidence,
    }
