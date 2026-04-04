"""Multi-Timeframe (MTF) Confluence Matrix.

Evaluates trend alignment across multiple timeframes (e.g. 1m, 15m, 1h).
A lower-timeframe signal is scored based on whether it aligns with the
higher-timeframe EMA/trend direction.

Typical usage
-------------
.. code-block:: python

    from src.mtf import compute_mtf_confluence, MTFResult

    # Each timeframe entry is a dict of {"ema_fast": float, "ema_slow": float,
    # "close": float}.  Timeframes should be ordered from lowest to highest.
    timeframes = {
        "1m":  {"ema_fast": 101.0, "ema_slow": 100.0, "close": 101.5},
        "15m": {"ema_fast": 102.0, "ema_slow": 101.0, "close": 102.0},
        "1h":  {"ema_fast": 103.0, "ema_slow": 101.5, "close": 103.5},
    }
    result = compute_mtf_confluence("LONG", timeframes)
    if result.is_aligned:
        print(f"All TFs aligned  score={result.score:.2f}")
    else:
        print(f"Misaligned: {result.reason}")

The module is **pure-function** – no I/O, no side-effects.  Wire it into
the signal validation pipeline after indicator calculations are available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.utils import get_logger

log = get_logger("mtf")

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Minimum confluence score (0-1) required to pass the MTF gate.
#: 0.5 means at least half the supplied timeframes must agree.
MTF_MIN_SCORE: float = 0.5

#: Score threshold above which the confluence is considered *strong*.
MTF_STRONG_SCORE: float = 0.8

#: Timeframe-proportional weights for MTF confluence scoring.
#: Higher timeframes carry more weight (institutional significance).
#: Timeframes not in this dict default to 1.0.
_TF_WEIGHTS: dict[str, float] = {
    "1m":  0.5,
    "5m":  1.0,
    "15m": 1.5,
    "1h":  2.0,
    "4h":  3.0,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeframeState:
    """Trend state derived for a single timeframe."""

    timeframe: str
    trend: str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    ema_fast: float
    ema_slow: float
    close: float


@dataclass
class MTFResult:
    """Output of :func:`compute_mtf_confluence`."""

    signal_direction: str               # "LONG" | "SHORT"
    score: float                        # 0.0 – 1.0  (aligned TFs / total TFs)
    aligned_count: float                # weighted TF alignment (includes 0.5 for NEUTRAL)
    total_count: int                    # total TFs evaluated
    is_aligned: bool                    # score >= MTF_MIN_SCORE
    is_strong: bool                     # score >= MTF_STRONG_SCORE
    timeframe_states: List[TimeframeState] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_trend(ema_fast: float, ema_slow: float, close: float) -> str:
    """Return "BULLISH", "BEARISH", or "NEUTRAL" for one timeframe."""
    if ema_fast > ema_slow and close > ema_fast:
        return "BULLISH"
    if ema_fast < ema_slow and close < ema_fast:
        return "BEARISH"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------


def compute_mtf_confluence(
    signal_direction: str,
    timeframes: Dict[str, Dict[str, float]],
    min_score: float = MTF_MIN_SCORE,
    tf_weight_overrides: Optional[Dict[str, float]] = None,
) -> MTFResult:
    """Evaluate trend alignment across multiple timeframes.

    Parameters
    ----------
    signal_direction:
        ``"LONG"`` or ``"SHORT"``.
    timeframes:
        Mapping of timeframe label → indicator dict.  Each dict **must**
        contain the keys ``"ema_fast"``, ``"ema_slow"``, and ``"close"``.
        Missing or malformed entries are skipped and logged.
    min_score:
        Minimum fraction of timeframes that must agree with the signal
        direction to be considered aligned.  Defaults to
        :data:`MTF_MIN_SCORE`.
    tf_weight_overrides:
        Optional mapping of timeframe label → weight override.  When
        provided, these weights replace the defaults from :data:`_TF_WEIGHTS`
        for the specified timeframes.  Use this to apply regime-specific
        higher/lower TF weight multipliers without modifying the global table.

    Returns
    -------
    :class:`MTFResult`
    """
    direction = signal_direction.upper()
    states: List[TimeframeState] = []
    aligned: float = 0.0
    weighted_total: float = 0.0

    for tf_label, data in timeframes.items():
        try:
            ema_fast = float(data["ema_fast"])
            ema_slow = float(data["ema_slow"])
            close = float(data["close"])
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("MTF: skipping timeframe {} – bad data: {}", tf_label, exc)
            continue

        trend = _classify_trend(ema_fast, ema_slow, close)
        states.append(TimeframeState(
            timeframe=tf_label,
            trend=trend,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            close=close,
        ))

        weight = (
            tf_weight_overrides[tf_label]
            if tf_weight_overrides and tf_label in tf_weight_overrides
            else _TF_WEIGHTS.get(tf_label, 1.0)
        )
        weighted_total += weight

        wanted = "BULLISH" if direction == "LONG" else "BEARISH"
        if trend == wanted:
            aligned += weight
        elif trend == "NEUTRAL":
            aligned += weight * 0.5  # Partial credit — not opposing the direction

    total = len(states)
    if total == 0:
        return MTFResult(
            signal_direction=direction,
            score=0.0,
            aligned_count=0,
            total_count=0,
            is_aligned=False,
            is_strong=False,
            timeframe_states=states,
            reason="no valid timeframe data provided",
        )

    score = aligned / weighted_total if weighted_total > 0 else 0.0
    is_aligned = score >= min_score
    is_strong = score >= MTF_STRONG_SCORE

    misaligned = [s.timeframe for s in states if s.trend != ("BULLISH" if direction == "LONG" else "BEARISH")]
    reason = ""
    if not is_aligned:
        reason = (
            f"MTF misaligned: {aligned}/{total} TFs agree with {direction}; "
            f"conflicting TFs: {misaligned}"
        )

    return MTFResult(
        signal_direction=direction,
        score=round(score, 4),
        aligned_count=aligned,
        total_count=total,
        is_aligned=is_aligned,
        is_strong=is_strong,
        timeframe_states=states,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# MTF confluence with staleness decay
# ---------------------------------------------------------------------------

# Timeframe duration in hours for staleness decay
_TF_DURATION_HOURS: dict[str, float] = {
    "1m": 1 / 60,
    "5m": 5 / 60,
    "15m": 0.25,
    "1h": 1.0,
    "4h": 4.0,
}


def compute_mtf_confluence_with_decay(
    signal_direction: str,
    timeframes: Dict[str, Dict[str, float]],
    min_score: float = MTF_MIN_SCORE,
    tf_weight_overrides: Optional[Dict[str, float]] = None,
    candle_ages_hours: Optional[Dict[str, float]] = None,
) -> MTFResult:
    """Evaluate MTF confluence with optional staleness decay on candle age.

    Behaves identically to :func:`compute_mtf_confluence` when
    *candle_ages_hours* is ``None``.  When provided, each timeframe's
    weight is reduced based on how stale the candle is relative to its
    duration (clamped to a minimum of 30 % weight).

    Parameters
    ----------
    signal_direction:
        ``"LONG"`` or ``"SHORT"``.
    timeframes:
        Same format as :func:`compute_mtf_confluence`.
    min_score:
        Minimum passing score.
    tf_weight_overrides:
        Optional per-timeframe weight overrides.
    candle_ages_hours:
        Maps timeframe label → hours since candle close.  Fresh candles
        (age ≈ 0) get full weight; a 4 h candle 3 h old decays to 62.5 %.
    """
    if candle_ages_hours is None:
        return compute_mtf_confluence(
            signal_direction, timeframes, min_score, tf_weight_overrides,
        )

    direction = signal_direction.upper()
    states: List[TimeframeState] = []
    aligned: float = 0.0
    weighted_total: float = 0.0

    for tf_label, data in timeframes.items():
        try:
            ema_fast = float(data["ema_fast"])
            ema_slow = float(data["ema_slow"])
            close = float(data["close"])
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("MTF-decay: skipping timeframe {} – bad data: {}", tf_label, exc)
            continue

        trend = _classify_trend(ema_fast, ema_slow, close)
        states.append(TimeframeState(
            timeframe=tf_label,
            trend=trend,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            close=close,
        ))

        base_weight = (
            tf_weight_overrides[tf_label]
            if tf_weight_overrides and tf_label in tf_weight_overrides
            else _TF_WEIGHTS.get(tf_label, 1.0)
        )

        # Apply staleness decay
        tf_duration = _TF_DURATION_HOURS.get(tf_label, 1.0)
        age = candle_ages_hours.get(tf_label, 0.0)
        decay = max(0.3, 1.0 - age / (tf_duration * 2.0))
        effective_weight = base_weight * decay

        weighted_total += effective_weight

        wanted = "BULLISH" if direction == "LONG" else "BEARISH"
        if trend == wanted:
            aligned += effective_weight
        elif trend == "NEUTRAL":
            aligned += effective_weight * 0.5

    total = len(states)
    if total == 0:
        return MTFResult(
            signal_direction=direction,
            score=0.0,
            aligned_count=0,
            total_count=0,
            is_aligned=False,
            is_strong=False,
            timeframe_states=states,
            reason="no valid timeframe data provided",
        )

    score = aligned / weighted_total if weighted_total > 0 else 0.0
    is_aligned = score >= min_score
    is_strong = score >= MTF_STRONG_SCORE

    misaligned = [s.timeframe for s in states if s.trend != ("BULLISH" if direction == "LONG" else "BEARISH")]
    reason = ""
    if not is_aligned:
        reason = (
            f"MTF misaligned: {aligned:.2f}/{total} TFs agree with {direction}; "
            f"conflicting TFs: {misaligned}"
        )

    return MTFResult(
        signal_direction=direction,
        score=round(score, 4),
        aligned_count=aligned,
        total_count=total,
        is_aligned=is_aligned,
        is_strong=is_strong,
        timeframe_states=states,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Channel-specific gate functions (PR_06)
# ---------------------------------------------------------------------------


def check_mtf_ema_alignment(
    higher_tf_indicators: dict,
    direction: str,
    strict: bool = True,
) -> tuple[bool, str, float]:
    """Check that EMA alignment on a higher timeframe supports the trade direction.

    Parameters
    ----------
    higher_tf_indicators:
        Indicator dict for the confirmation timeframe (e.g. 1h for a 5m scalp).
    direction:
        "LONG" or "SHORT".
    strict:
        When True, return (False, ...) on failure; else apply -10 pts penalty.
    """
    ema_fast = higher_tf_indicators.get("ema9_last")
    ema_slow = higher_tf_indicators.get("ema21_last")
    ema200 = higher_tf_indicators.get("ema200_last")

    if ema_fast is None or ema_slow is None:
        return True, "mtf_ema_no_data", 0.0   # Fail open on missing data

    aligned = (ema_fast > ema_slow) if direction == "LONG" else (ema_fast < ema_slow)

    # If EMA200 available, add extra confirmation weight
    if ema200 is not None:
        price_above_ema200 = ema_fast > ema200
        if direction == "LONG" and not price_above_ema200:
            aligned = False
        if direction == "SHORT" and price_above_ema200:
            aligned = False

    if aligned:
        return True, "mtf_ema_aligned", 0.0
    if strict:
        return False, "mtf_ema_opposed", 0.0
    return True, "mtf_ema_soft_fail", -10.0


def check_mtf_rsi(
    higher_tf_indicators: dict,
    direction: str,
    overbought: float = 70.0,
    oversold: float = 30.0,
) -> tuple[bool, str, float]:
    """Check RSI on higher timeframe is not in an extreme zone opposing the signal."""
    rsi_val = higher_tf_indicators.get("rsi_last")
    if rsi_val is None:
        return True, "mtf_rsi_no_data", 0.0
    if direction == "LONG" and rsi_val >= overbought:
        return False, f"mtf_rsi_overbought_{rsi_val:.1f}", 0.0
    if direction == "SHORT" and rsi_val <= oversold:
        return False, f"mtf_rsi_oversold_{rsi_val:.1f}", 0.0
    return True, "mtf_rsi_ok", 0.0


def check_mtf_adx(
    higher_tf_indicators: dict,
    min_adx: float = 20.0,
    max_adx: float = 65.0,
) -> tuple[bool, str, float]:
    """Check ADX on higher timeframe is within [min_adx, max_adx]."""
    adx_val = higher_tf_indicators.get("adx_last")
    if adx_val is None:
        return True, "mtf_adx_no_data", 0.0
    if adx_val < min_adx:
        return False, f"mtf_adx_weak_{adx_val:.1f}", 0.0
    if adx_val > max_adx:
        return False, f"mtf_adx_extreme_{adx_val:.1f}", 0.0
    return True, "mtf_adx_ok", 0.0


def mtf_gate_scalp_standard(
    indicators_1h: dict,
    direction: str,
    regime: str = "",
) -> tuple[bool, str, float]:
    """MTF gate for the SCALP standard path (5m signal → 1h confirmation).

    Strict in TRENDING/VOLATILE; soft penalty in RANGING/QUIET.
    Passes if EMA alignment OR RSI non-extreme on 1h.
    """
    strict = regime.upper() in ("TRENDING_UP", "TRENDING_DOWN", "VOLATILE")
    ema_ok, ema_reason, ema_adj = check_mtf_ema_alignment(indicators_1h, direction, strict=False)
    rsi_ok, rsi_reason, _ = check_mtf_rsi(indicators_1h, direction)

    # ema_adj < 0 indicates genuine misalignment (soft-fail path in check_mtf_ema_alignment);
    # ema_adj == 0 means either aligned or no-data (both treated as "ok" for this gate).
    ema_actually_ok = ema_adj == 0.0

    if ema_actually_ok and rsi_ok:
        return True, f"{ema_reason}+{rsi_reason}", 0.0
    if not ema_actually_ok and not rsi_ok:
        if strict:
            return False, f"{ema_reason}+{rsi_reason}", 0.0
        return True, "mtf_both_soft_fail", -10.0
    # One passes — partial confirmation
    return True, f"mtf_partial_{ema_reason}_{rsi_reason}", -5.0


def mtf_gate_scalp_range_fade(
    indicators_15m: dict,
    direction: str,
) -> tuple[bool, str, float]:
    """MTF gate for RANGE_FADE path (5m signal → 15m RSI confirmation).

    Requires the 15m RSI to clearly confirm the mean-reversion thesis:
    LONG needs RSI ≤ 40 (strongly oversold), SHORT needs RSI ≥ 60 (strongly
    overbought).  This prevents entries where the higher timeframe hasn't
    committed to the reversal yet.
    """
    rsi_val = indicators_15m.get("rsi_last")
    if rsi_val is None:
        return True, "mtf_15m_rsi_no_data", 0.0
    if direction == "LONG" and rsi_val > 40.0:
        return False, f"mtf_15m_rsi_not_oversold_{rsi_val:.1f}", 0.0
    if direction == "SHORT" and rsi_val < 60.0:
        return False, f"mtf_15m_rsi_not_overbought_{rsi_val:.1f}", 0.0
    return True, "mtf_15m_rsi_ok", 0.0


def mtf_gate_swing(
    indicators_4h: dict,
    direction: str,
) -> tuple[bool, str, float]:
    """MTF gate for SWING (1h signal → 4h EMA + ADX confirmation)."""
    ema_ok, ema_reason, ema_adj = check_mtf_ema_alignment(indicators_4h, direction, strict=True)
    adx_ok, adx_reason, _ = check_mtf_adx(indicators_4h, min_adx=18.0, max_adx=70.0)
    if ema_ok and adx_ok:
        return True, f"{ema_reason}+{adx_reason}", 0.0
    if not ema_ok:
        return False, ema_reason, 0.0
    # EMA ok but ADX fails — soft penalty
    return True, adx_reason, -5.0


def check_mtf_gate(
    signal_direction: str,
    timeframes: Dict[str, Dict[str, float]],
    min_score: float = MTF_MIN_SCORE,
    tf_weight_overrides: Optional[Dict[str, float]] = None,
) -> tuple[bool, str]:
    """Pipeline hook: return ``(allowed, reason)`` for the MTF confluence gate.

    Fails open (returns ``True``) when no valid timeframe data is provided,
    matching the behaviour of the order book and CVD filters.

    Parameters
    ----------
    signal_direction:
        ``"LONG"`` or ``"SHORT"``.
    timeframes:
        Same format as :func:`compute_mtf_confluence`.
    min_score:
        Minimum passing score.
    tf_weight_overrides:
        Optional per-timeframe weight overrides passed through to
        :func:`compute_mtf_confluence`.  Allows callers (e.g. the scanner's
        regime-weighted MTF gate) to adjust how much each timeframe
        contributes without modifying the global weight table.

    Returns
    -------
    ``(allowed, reason)`` – ``allowed`` is ``False`` only when sufficient
    data exists *and* the confluence score falls below *min_score*.
    """
    if not timeframes:
        return True, ""

    result = compute_mtf_confluence(signal_direction, timeframes, min_score, tf_weight_overrides)
    if result.total_count == 0:
        return True, ""

    if not result.is_aligned:
        return False, result.reason

    return True, ""


# ---------------------------------------------------------------------------
# MTF divergence detection
# ---------------------------------------------------------------------------

#: Lower timeframes used for divergence detection.
_LOWER_TFS: List[str] = ["1m", "5m"]
#: Higher timeframes used for divergence detection.
_HIGHER_TFS: List[str] = ["1h", "4h"]


def _infer_bias(indicators: dict) -> str:
    """Infer directional bias from an indicator dict.

    Returns ``"BULLISH"``, ``"BEARISH"``, or ``"NEUTRAL"`` based on
    momentum and EMA alignment.
    """
    momentum = indicators.get("momentum_last")
    ema9 = indicators.get("ema9_last")
    ema21 = indicators.get("ema21_last")
    rsi = indicators.get("rsi")

    bullish_signals = 0
    bearish_signals = 0

    if momentum is not None:
        if momentum > 0:
            bullish_signals += 1
        elif momentum < 0:
            bearish_signals += 1

    if ema9 is not None and ema21 is not None:
        if ema9 > ema21:
            bullish_signals += 1
        elif ema9 < ema21:
            bearish_signals += 1

    if rsi is not None:
        if rsi > 55:
            bullish_signals += 1
        elif rsi < 45:
            bearish_signals += 1

    if bullish_signals > bearish_signals:
        return "BULLISH"
    if bearish_signals > bullish_signals:
        return "BEARISH"
    return "NEUTRAL"


def detect_mtf_divergence(
    indicators_by_tf: Dict[str, dict],
    direction: str,
) -> dict:
    """Detect when lower timeframes diverge from higher timeframes.

    Parameters
    ----------
    indicators_by_tf:
        Mapping of timeframe label → indicator dict.  Expected keys in each
        indicator dict: ``rsi``, ``momentum_last``, ``ema9_last``,
        ``ema21_last``.
    direction:
        Signal direction: ``"LONG"`` or ``"SHORT"``.

    Returns
    -------
    dict
        ``{"divergent": bool, "lower_tf_bias": str, "higher_tf_bias": str,
        "severity": float, "recommendation": str}``
    """
    if not indicators_by_tf:
        return {
            "divergent": False,
            "lower_tf_bias": "NEUTRAL",
            "higher_tf_bias": "NEUTRAL",
            "severity": 0.0,
            "recommendation": "no data",
        }

    lower_biases: List[str] = []
    higher_biases: List[str] = []

    for tf in _LOWER_TFS:
        if tf in indicators_by_tf:
            lower_biases.append(_infer_bias(indicators_by_tf[tf]))

    for tf in _HIGHER_TFS:
        if tf in indicators_by_tf:
            higher_biases.append(_infer_bias(indicators_by_tf[tf]))

    if not lower_biases and not higher_biases:
        return {
            "divergent": False,
            "lower_tf_bias": "NEUTRAL",
            "higher_tf_bias": "NEUTRAL",
            "severity": 0.0,
            "recommendation": "insufficient timeframe data",
        }

    def _majority(biases: List[str]) -> str:
        if not biases:
            return "NEUTRAL"
        bull = sum(1 for b in biases if b == "BULLISH")
        bear = sum(1 for b in biases if b == "BEARISH")
        if bull > bear:
            return "BULLISH"
        if bear > bull:
            return "BEARISH"
        return "NEUTRAL"

    lower_bias = _majority(lower_biases)
    higher_bias = _majority(higher_biases)

    divergent = (
        lower_bias != "NEUTRAL"
        and higher_bias != "NEUTRAL"
        and lower_bias != higher_bias
    )

    # Severity: 0.0 when aligned, 0.3 when one is neutral, 1.0 when fully opposed
    if divergent:
        severity = 1.0
    elif lower_bias == "NEUTRAL" or higher_bias == "NEUTRAL":
        severity = 0.3
    else:
        severity = 0.0

    # Recommendation
    wanted = "BULLISH" if direction.upper() == "LONG" else "BEARISH"
    if not divergent:
        recommendation = "aligned"
    elif higher_bias == wanted:
        recommendation = "lower TFs opposing — consider waiting for realignment"
    else:
        recommendation = "higher TFs opposing — potential reversal signal"

    return {
        "divergent": divergent,
        "lower_tf_bias": lower_bias,
        "higher_tf_bias": higher_bias,
        "severity": severity,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Cross-TF volume delta aggregation
# ---------------------------------------------------------------------------


def compute_cross_tf_volume_delta(candles_by_tf: Dict[str, dict]) -> dict:
    """Aggregate volume delta across timeframes.

    Each entry in *candles_by_tf* should be a dict with at least
    ``buy_volume`` and ``sell_volume`` keys.  If these are missing, the
    timeframe is skipped.

    Parameters
    ----------
    candles_by_tf:
        Mapping of timeframe label → candle data dict.

    Returns
    -------
    dict
        ``{"net_delta": float, "aligned": bool, "alignment_score": float,
        "dominant_tf": str}``
    """
    if not candles_by_tf:
        return {
            "net_delta": 0.0,
            "aligned": False,
            "alignment_score": 0.0,
            "dominant_tf": "",
        }

    deltas: Dict[str, float] = {}
    for tf, data in candles_by_tf.items():
        buy_vol = data.get("buy_volume")
        sell_vol = data.get("sell_volume")
        if buy_vol is None or sell_vol is None:
            continue
        try:
            deltas[tf] = float(buy_vol) - float(sell_vol)
        except (TypeError, ValueError):
            continue

    if not deltas:
        return {
            "net_delta": 0.0,
            "aligned": False,
            "alignment_score": 0.0,
            "dominant_tf": "",
        }

    net_delta = sum(deltas.values())

    # Check alignment: all TFs agree on direction (positive or negative)
    positive = sum(1 for d in deltas.values() if d > 0)
    negative = sum(1 for d in deltas.values() if d < 0)
    total = len(deltas)
    aligned = (positive == total) or (negative == total)
    alignment_score = max(positive, negative) / total if total > 0 else 0.0

    # Dominant TF: the one with the largest absolute delta
    dominant_tf = max(deltas, key=lambda t: abs(deltas[t]))

    return {
        "net_delta": net_delta,
        "aligned": aligned,
        "alignment_score": round(alignment_score, 4),
        "dominant_tf": dominant_tf,
    }


# ---------------------------------------------------------------------------
# Channel-specific MTF gates: divergence and supertrend
# ---------------------------------------------------------------------------


def mtf_gate_scalp_divergence(
    indicators_by_tf: Dict[str, dict],
    direction: str,
) -> Tuple[bool, str]:
    """MTF gate specifically for divergence setups.

    More lenient than the standard gate since divergences by nature oppose
    the prevailing higher-TF trend.  Passes if at least one higher TF is
    neutral (not actively opposing) or if divergence severity is low.

    Parameters
    ----------
    indicators_by_tf:
        Mapping of timeframe label → indicator dict.
    direction:
        ``"LONG"`` or ``"SHORT"``.

    Returns
    -------
    Tuple[bool, str]
        ``(passed, reason)``
    """
    if not indicators_by_tf:
        return True, "mtf_divergence_no_data"

    div = detect_mtf_divergence(indicators_by_tf, direction)

    if not div["divergent"]:
        return True, "mtf_divergence_aligned"

    # Lenient: allow if severity is moderate (divergence setups are inherently
    # contrarian, so full opposition is expected)
    if div["severity"] <= 0.5:
        return True, f"mtf_divergence_mild_{div['severity']:.1f}"

    # Check if at least one higher TF is neutral — partial agreement is enough
    higher_neutral = False
    for tf in _HIGHER_TFS:
        if tf in indicators_by_tf:
            bias = _infer_bias(indicators_by_tf[tf])
            if bias == "NEUTRAL":
                higher_neutral = True
                break

    if higher_neutral:
        return True, "mtf_divergence_higher_neutral"

    return False, f"mtf_divergence_blocked_{div['higher_tf_bias']}_vs_{direction}"


def mtf_gate_scalp_supertrend(
    indicators_by_tf: Dict[str, dict],
    direction: str,
) -> Tuple[bool, str]:
    """MTF gate for supertrend setups.

    Requires at least 2 timeframes to agree on the signal direction.
    Uses EMA alignment and momentum to infer directional bias per TF.

    Parameters
    ----------
    indicators_by_tf:
        Mapping of timeframe label → indicator dict.
    direction:
        ``"LONG"`` or ``"SHORT"``.

    Returns
    -------
    Tuple[bool, str]
        ``(passed, reason)``
    """
    if not indicators_by_tf:
        return True, "mtf_supertrend_no_data"

    wanted = "BULLISH" if direction.upper() == "LONG" else "BEARISH"
    agreeing: List[str] = []
    opposing: List[str] = []

    for tf, indicators in indicators_by_tf.items():
        bias = _infer_bias(indicators)
        if bias == wanted:
            agreeing.append(tf)
        elif bias != "NEUTRAL":
            opposing.append(tf)

    if len(agreeing) >= 2:
        return True, f"mtf_supertrend_ok_{len(agreeing)}_agree"

    if len(agreeing) == 1 and not opposing:
        return True, f"mtf_supertrend_partial_{agreeing[0]}"

    return (
        False,
        f"mtf_supertrend_blocked_{len(agreeing)}_agree_{len(opposing)}_oppose",
    )
