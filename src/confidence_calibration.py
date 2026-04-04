"""Confidence Calibration — map raw confidence scores to estimated win probabilities.

Provides a hybrid calibration approach: hardcoded calibration curves are used
when historical outcome data is insufficient, then smoothly transitions to
data-driven calibration as outcomes accumulate.

Typical usage
-------------
.. code-block:: python

    from src.confidence_calibration import ConfidenceCalibrator, wilson_lower_bound

    cal = ConfidenceCalibrator(min_samples=20)
    calibrated = cal.calibrate(raw_confidence=72.5, channel="spot")
    cal.record_outcome(confidence_at_signal=72.5, won=True, channel="spot")
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from src.utils import get_logger

log = get_logger("confidence_calibration")

# Hardcoded calibration curve based on typical crypto-scalping system
# performance.  Maps raw confidence bucket → estimated actual win rate.
_HARDCODED_CURVE: Dict[int, float] = {
    50: 0.35,
    55: 0.40,
    60: 0.45,
    65: 0.52,
    70: 0.58,
    75: 0.65,
    80: 0.72,
    85: 0.78,
    90: 0.83,
    95: 0.88,
    100: 0.92,
}

_CURVE_KEYS = sorted(_HARDCODED_CURVE.keys())

_CONFIDENCE_SCALE = 100.0
_ALPHA_START = 0.8
_ALPHA_MIN = 0.3
_ALPHA_DECAY_RANGE = _ALPHA_START - _ALPHA_MIN  # 0.5
_DECAY_SAMPLES = 200.0


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    """Compute the lower bound of a Wilson score confidence interval.

    Useful for ranking items by positive proportion when sample sizes vary.
    Returns 0.0 when *total* is zero.

    Parameters
    ----------
    wins:
        Number of positive outcomes.
    total:
        Total number of observations.
    z:
        Z-score for the desired confidence level (default 1.96 → 95 %).
    """
    if total == 0:
        return 0.0
    p_hat = wins / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = p_hat + z2 / (2.0 * total)
    spread = z * math.sqrt((p_hat * (1.0 - p_hat) + z2 / (4.0 * total)) / total)
    return (centre - spread) / denominator


def _interpolate_curve(raw_confidence: float) -> float:
    """Linearly interpolate the hardcoded calibration curve.

    Values below the minimum bucket clamp to its win rate; values above
    the maximum bucket clamp to its win rate.
    """
    if raw_confidence <= _CURVE_KEYS[0]:
        return _HARDCODED_CURVE[_CURVE_KEYS[0]]
    if raw_confidence >= _CURVE_KEYS[-1]:
        return _HARDCODED_CURVE[_CURVE_KEYS[-1]]

    for i in range(len(_CURVE_KEYS) - 1):
        lo, hi = _CURVE_KEYS[i], _CURVE_KEYS[i + 1]
        if lo <= raw_confidence <= hi:
            t = (raw_confidence - lo) / (hi - lo)
            return _HARDCODED_CURVE[lo] + t * (_HARDCODED_CURVE[hi] - _HARDCODED_CURVE[lo])

    return _HARDCODED_CURVE[_CURVE_KEYS[-1]]


@dataclass
class _BucketStats:
    """Accumulates win/loss outcomes for a single confidence bucket."""

    wins: int = 0
    total: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total > 0 else 0.0


class ConfidenceCalibrator:
    """Hybrid hardcoded / data-driven confidence calibrator.

    While fewer than *min_samples* total outcomes have been recorded the
    calibrator relies on the hardcoded curve.  As outcomes accumulate the
    blending weight (``alpha``) decays from 0.8 toward 0.3, progressively
    favouring the empirical win rate.

    Parameters
    ----------
    min_samples:
        Minimum total outcomes before data-driven calibration activates.
    """

    def __init__(self, min_samples: int = 20) -> None:
        self._min_samples = min_samples
        self._global_stats: _BucketStats = _BucketStats()
        self._bucket_stats: Dict[int, _BucketStats] = defaultdict(_BucketStats)
        self._channel_stats: Dict[str, Dict[int, _BucketStats]] = defaultdict(
            lambda: defaultdict(_BucketStats)
        )

    @staticmethod
    def _bucket_key(confidence: float) -> int:
        """Round confidence to the nearest 5-point bucket."""
        return max(50, min(100, int(round(confidence / 5.0) * 5)))

    def _compute_alpha(self) -> float:
        """Blending weight for raw confidence vs. calibrated value.

        Starts at 0.8 (mostly raw) and decays toward 0.3 as sample count
        grows past *min_samples*.  The decay is linear over 200 samples
        beyond the minimum.
        """
        n = self._global_stats.total
        if n < self._min_samples:
            return _ALPHA_START
        excess = n - self._min_samples
        return _ALPHA_START - _ALPHA_DECAY_RANGE * min(excess / _DECAY_SAMPLES, 1.0)

    def calibrate(self, raw_confidence: float, channel: str = "") -> float:
        """Return a calibrated confidence score.

        When insufficient data is available the hardcoded curve is used
        exclusively.  Otherwise:

            calibrated = raw × α + bucket_win_rate × 100 × (1 − α)

        Parameters
        ----------
        raw_confidence:
            Original confidence score (0–100).
        channel:
            Optional channel identifier for channel-specific calibration.
        """
        bucket = self._bucket_key(raw_confidence)
        alpha = self._compute_alpha()

        bucket_win_rate = _interpolate_curve(raw_confidence)

        if self._global_stats.total >= self._min_samples:
            stats = self._bucket_stats.get(bucket)
            if stats and stats.total >= 3:
                bucket_win_rate = stats.win_rate

            if channel:
                ch_stats = self._channel_stats.get(channel, {}).get(bucket)
                if ch_stats and ch_stats.total >= 3:
                    bucket_win_rate = ch_stats.win_rate

        calibrated = raw_confidence * alpha + bucket_win_rate * _CONFIDENCE_SCALE * (1.0 - alpha)
        calibrated = max(0.0, min(100.0, calibrated))

        log.debug(
            "calibrate raw={:.1f} bucket={} alpha={:.2f} win_rate={:.3f} → {:.1f}",
            raw_confidence, bucket, alpha, bucket_win_rate, calibrated,
        )
        return calibrated

    def record_outcome(
        self, confidence_at_signal: float, won: bool, channel: str = ""
    ) -> None:
        """Record a trade outcome for future data-driven calibration.

        Parameters
        ----------
        confidence_at_signal:
            The raw confidence at the time the signal was generated.
        won:
            Whether the trade was profitable.
        channel:
            Optional channel identifier.
        """
        bucket = self._bucket_key(confidence_at_signal)
        w = 1 if won else 0

        self._global_stats.wins += w
        self._global_stats.total += 1

        self._bucket_stats[bucket].wins += w
        self._bucket_stats[bucket].total += 1

        if channel:
            self._channel_stats[channel][bucket].wins += w
            self._channel_stats[channel][bucket].total += 1

        log.debug(
            "outcome recorded: conf={:.1f} bucket={} won={} total={}",
            confidence_at_signal, bucket, won, self._global_stats.total,
        )

    def get_calibration_stats(self) -> dict:
        """Return current calibration statistics.

        Returns
        -------
        dict
            Keys: ``total_outcomes``, ``global_win_rate``, ``alpha``,
            ``using_data_driven``, ``bucket_stats``, ``channel_stats``.
        """
        bucket_data: Dict[int, dict] = {}
        for bk, bs in sorted(self._bucket_stats.items()):
            bucket_data[bk] = {
                "wins": bs.wins,
                "total": bs.total,
                "win_rate": round(bs.win_rate, 4),
                "wilson_lb": round(wilson_lower_bound(bs.wins, bs.total), 4),
            }

        channel_data: Dict[str, Dict[int, dict]] = {}
        for ch, buckets in self._channel_stats.items():
            channel_data[ch] = {}
            for bk, bs in sorted(buckets.items()):
                channel_data[ch][bk] = {
                    "wins": bs.wins,
                    "total": bs.total,
                    "win_rate": round(bs.win_rate, 4),
                }

        return {
            "total_outcomes": self._global_stats.total,
            "global_win_rate": round(self._global_stats.win_rate, 4),
            "alpha": round(self._compute_alpha(), 4),
            "using_data_driven": self._global_stats.total >= self._min_samples,
            "bucket_stats": bucket_data,
            "channel_stats": channel_data,
        }
