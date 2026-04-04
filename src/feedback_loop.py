"""Post-Trade ML Feedback Loop.

Tracks completed trade outcomes and derives adaptive confidence adjustments
so that historically underperforming setup/channel combinations are
penalised while consistently winning ones receive a small boost.

This module is **stateful**: a :class:`FeedbackLoop` instance is held on
the :class:`~src.scanner.Scanner` and updated externally (from the trade
monitor) via :meth:`FeedbackLoop.record_outcome`.

Design notes
------------
* Outcomes are stored in a bounded :class:`collections.deque` (default 500).
* Weight adjustments are recomputed after every new outcome recording.
* The public :meth:`FeedbackLoop.get_confidence_adjustment` method is the
  only entry point used by the scanner hot path.
* The module is intentionally dependency-free beyond the standard library so
  it can be imported without any external packages.

Typical usage
-------------
.. code-block:: python

    from src.feedback_loop import FeedbackLoop, TradeOutcome

    loop = FeedbackLoop()

    # … at trade close …
    loop.record_outcome(TradeOutcome(
        symbol="SOLUSDT",
        channel="360_SCALP",
        direction="LONG",
        setup_class="SWEEP_REVERSAL",
        market_state="TRENDING",
        component_scores={"market": 20.0, "setup": 18.0, "execution": 14.0,
                          "risk": 12.0, "context": 8.0},
        confidence=72.5,
        r_multiple=1.8,
        outcome="TP2",
        hold_duration_seconds=240.0,
        timestamp=time.monotonic(),
    ))

    # … at next signal …
    adj = loop.get_confidence_adjustment({"market": 22.0, ...}, "360_SCALP")
    final_confidence = base_confidence + adj  # clamped externally
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
import asyncio as _asyncio
import json as _json
import os as _os
from typing import Dict, Optional

from src.utils import get_logger

log = get_logger("feedback_loop")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Win outcomes — trades that hit at least TP1.
_WIN_OUTCOMES: frozenset[str] = frozenset({"TP1", "TP2", "TP3"})

#: Win-rate below this → penalise the setup/channel combination.
_PENALTY_WIN_RATE: float = 0.40

#: Win-rate above this → reward the setup/channel combination.
_BOOST_WIN_RATE: float = 0.70

#: Confidence penalty applied when win rate is below :data:`_PENALTY_WIN_RATE`.
_SETUP_PENALTY: float = -8.0

#: Confidence boost applied when win rate exceeds :data:`_BOOST_WIN_RATE`.
_SETUP_BOOST: float = +5.0

#: Execution score below which a penalty is applied when historical lose rate > 60%.
_EXEC_PENALTY_THRESHOLD: float = 14.0
_EXEC_LOSE_RATE_THRESHOLD: float = 0.60
_EXEC_PENALTY: float = -3.0

#: Market score above which a boost is applied when historical win rate > 65%.
_MARKET_BOOST_THRESHOLD: float = 22.0
_MARKET_WIN_RATE_THRESHOLD: float = 0.65
_MARKET_BOOST: float = +2.0

#: Clamp range for the total confidence adjustment returned by
#: :meth:`FeedbackLoop.get_confidence_adjustment`.
_ADJ_MIN: float = -15.0
_ADJ_MAX: float = +15.0

#: Minimum number of outcomes in a group before we trust its statistics.
_MIN_SAMPLE_SIZE: int = 5

#: Half-life for exponential time-decay of outcomes (5 days in seconds).
#: Recent outcomes weigh more than older ones when computing win rates.
_DECAY_HALF_LIFE_SECONDS: float = 5 * 24 * 3600


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TradeOutcome:
    """Record of a completed trade used for feedback analysis.

    Attributes
    ----------
    symbol:
        Trading pair (e.g. ``"SOLUSDT"``).
    channel:
        Scanner channel name (e.g. ``"360_SCALP"``).
    direction:
        ``"LONG"`` or ``"SHORT"``.
    setup_class:
        The :class:`~src.signal_quality.SetupClass` value string
        (e.g. ``"SWEEP_REVERSAL"``).
    market_state:
        Market phase at signal time (e.g. ``"TRENDING"``).
    component_scores:
        Dict mapping component name → score (market, setup, execution, risk, context).
    confidence:
        Final confidence value at signal dispatch.
    r_multiple:
        Realised R-multiple (negative for losses).
    outcome:
        One of ``"TP1"``, ``"TP2"``, ``"TP3"``, ``"SL"``, ``"EXPIRED"``,
        ``"INVALIDATED"``.
    hold_duration_seconds:
        How long the trade was held.
    timestamp:
        ``time.monotonic()`` value when the outcome was recorded.
    """

    symbol: str
    channel: str
    direction: str
    setup_class: str
    market_state: str
    component_scores: Dict[str, float]
    confidence: float
    r_multiple: float
    outcome: str
    hold_duration_seconds: float
    timestamp: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class FeedbackLoop:
    """Adaptive feedback engine that tunes confidence based on past outcomes.

    Parameters
    ----------
    max_history:
        Maximum number of :class:`TradeOutcome` records to retain.  Older
        entries are evicted automatically once the deque is full.
    """

    def __init__(self, max_history: int = 500) -> None:
        self._outcomes: deque[TradeOutcome] = deque(maxlen=max_history)
        # (channel, setup_class) → confidence adjustment
        self._weight_adjustments: Dict[tuple[str, str], float] = {}
        # Aggregated component-level statistics — recomputed in _recompute_weights
        self._exec_penalty_channels: set[str] = set()
        self._market_boost_channels: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(self, outcome: TradeOutcome) -> None:
        """Record a completed trade and recompute weight adjustments.

        Parameters
        ----------
        outcome:
            Completed :class:`TradeOutcome` instance.
        """
        self._outcomes.append(outcome)
        self._recompute_weights()
        log.debug(
            "Feedback: recorded {} {} {} → {}  (R={:.2f}, total history={})",
            outcome.symbol, outcome.channel, outcome.setup_class,
            outcome.outcome, outcome.r_multiple, len(self._outcomes),
        )

    def get_confidence_adjustment(
        self,
        component_scores: Dict[str, float],
        channel: str,
        setup_class: str = "",
    ) -> float:
        """Return a confidence adjustment based on historical patterns.

        Parameters
        ----------
        component_scores:
            Current signal component scores (market, setup, execution, risk, context).
        channel:
            Channel name (e.g. ``"360_SCALP"``).
        setup_class:
            Setup class string.  When empty, only component-level adjustments
            are applied (setup-level lookup is skipped).

        Returns
        -------
        float
            Adjustment in the range ``[-10, +10]``.
        """
        adj = 0.0

        # Setup/channel-level adjustment
        if setup_class:
            adj += self._weight_adjustments.get((channel, setup_class), 0.0)

        # Component-level adjustments (execution quality signal)
        # Default of 999.0 is intentionally high: when execution score is absent,
        # we do not penalise (fail-open semantics for missing data).
        exec_score = component_scores.get("execution", 999.0)
        if exec_score < _EXEC_PENALTY_THRESHOLD and channel in self._exec_penalty_channels:
            adj += _EXEC_PENALTY
            log.debug(
                "Feedback exec penalty for channel {}: execution={:.1f} < {:.1f}",
                channel, exec_score, _EXEC_PENALTY_THRESHOLD,
            )

        # Market score boost
        market_score = component_scores.get("market", 0.0)
        if market_score > _MARKET_BOOST_THRESHOLD and channel in self._market_boost_channels:
            adj += _MARKET_BOOST
            log.debug(
                "Feedback market boost for channel {}: market={:.1f} > {:.1f}",
                channel, market_score, _MARKET_BOOST_THRESHOLD,
            )

        clamped = max(_ADJ_MIN, min(_ADJ_MAX, adj))
        log.debug(
            "Feedback adjustment for {} / {}: raw={:.1f} → clamped={:.1f}",
            channel, setup_class, adj, clamped,
        )
        return clamped

    def get_setup_win_rate(self, setup_class: str, channel: str) -> float:
        """Return the historical win rate for *setup_class* in *channel*.

        Returns ``0.5`` (neutral) when there is insufficient history.
        Uses exponential time-decay so recent outcomes weigh more heavily.
        """
        group = [
            o for o in self._outcomes
            if o.setup_class == setup_class and o.channel == channel
        ]
        if len(group) < _MIN_SAMPLE_SIZE:
            return 0.5
        total_weight = sum(self._time_weight(r) for r in group)
        win_weight = sum(self._time_weight(r) for r in group if r.outcome in _WIN_OUTCOMES)
        return win_weight / total_weight if total_weight > 0 else 0.5

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _time_weight(self, outcome: TradeOutcome) -> float:
        """Exponential decay weight — recent outcomes matter more.

        Outcomes decay with a half-life of :data:`_DECAY_HALF_LIFE_SECONDS`
        (7 days by default), so a 7-day-old outcome has weight 0.5 and a
        14-day-old outcome has weight 0.25.
        """
        age = time.monotonic() - outcome.timestamp
        return math.exp(-math.log(2) * age / _DECAY_HALF_LIFE_SECONDS)

    def _recompute_weights(self) -> None:
        """Analyse recent outcomes and update the stored weight adjustments."""
        # Build groups keyed by (channel, setup_class)
        groups: Dict[tuple[str, str], list[TradeOutcome]] = {}
        for o in self._outcomes:
            key = (o.channel, o.setup_class)
            groups.setdefault(key, []).append(o)

        new_adjustments: Dict[tuple[str, str], float] = {}
        for (channel, setup_class), records in groups.items():
            if len(records) < _MIN_SAMPLE_SIZE:
                continue
            total_weight = sum(self._time_weight(r) for r in records)
            win_weight = sum(self._time_weight(r) for r in records if r.outcome in _WIN_OUTCOMES)
            win_rate = win_weight / total_weight if total_weight > 0 else 0.5
            if win_rate < _PENALTY_WIN_RATE:
                new_adjustments[(channel, setup_class)] = _SETUP_PENALTY
            elif win_rate > _BOOST_WIN_RATE:
                new_adjustments[(channel, setup_class)] = _SETUP_BOOST

        self._weight_adjustments = new_adjustments

        # Recompute component-level penalty sets
        exec_penalty_channels: set[str] = set()
        market_boost_channels: set[str] = set()

        # Group by channel for component analysis
        channels: Dict[str, list[TradeOutcome]] = {}
        for o in self._outcomes:
            channels.setdefault(o.channel, []).append(o)

        for channel, records in channels.items():
            if len(records) < _MIN_SAMPLE_SIZE:
                continue
            # Execution penalty: low execution score historically loses > 60 %
            low_exec = [r for r in records if r.component_scores.get("execution", 999) < _EXEC_PENALTY_THRESHOLD]
            if low_exec:
                loses = sum(1 for r in low_exec if r.outcome not in _WIN_OUTCOMES)
                if loses / len(low_exec) > _EXEC_LOSE_RATE_THRESHOLD:
                    exec_penalty_channels.add(channel)

            # Market boost: high market score historically wins > 65 %
            high_market = [r for r in records if r.component_scores.get("market", 0) > _MARKET_BOOST_THRESHOLD]
            if high_market:
                wins = sum(1 for r in high_market if r.outcome in _WIN_OUTCOMES)
                if wins / len(high_market) > _MARKET_WIN_RATE_THRESHOLD:
                    market_boost_channels.add(channel)

        self._exec_penalty_channels = exec_penalty_channels
        self._market_boost_channels = market_boost_channels

        log.debug(
            "Feedback weights recomputed: {} group adjustments, "
            "exec-penalty channels={}, market-boost channels={}",
            len(self._weight_adjustments),
            exec_penalty_channels,
            market_boost_channels,
        )

    # ------------------------------------------------------------------
    # Enhanced feedback methods (PR: Feedback Loop Integration)
    # ------------------------------------------------------------------

    def reward_signal(
        self,
        symbol: str,
        channel: str,
        setup_class: str,
        r_multiple: float = 1.5,
        outcome: str = "TP1",
    ) -> None:
        """Shortcut to record a winning trade outcome.

        Parameters
        ----------
        symbol:
            Trading pair.
        channel:
            Channel name.
        setup_class:
            Setup class string.
        r_multiple:
            Realised R-multiple (positive).
        outcome:
            Win outcome label (default ``"TP1"``).
        """
        self.record_outcome(TradeOutcome(
            symbol=symbol,
            channel=channel,
            direction="LONG",
            setup_class=setup_class,
            market_state="TRENDING",
            component_scores={},
            confidence=70.0,
            r_multiple=abs(r_multiple),
            outcome=outcome,
            hold_duration_seconds=0.0,
        ))

    def punish_signal(
        self,
        symbol: str,
        channel: str,
        setup_class: str,
        r_multiple: float = -1.0,
        outcome: str = "SL",
    ) -> None:
        """Shortcut to record a losing trade outcome.

        Parameters
        ----------
        symbol:
            Trading pair.
        channel:
            Channel name.
        setup_class:
            Setup class string.
        r_multiple:
            Realised R-multiple (negative).
        outcome:
            Loss outcome label (default ``"SL"``).
        """
        self.record_outcome(TradeOutcome(
            symbol=symbol,
            channel=channel,
            direction="LONG",
            setup_class=setup_class,
            market_state="TRENDING",
            component_scores={},
            confidence=70.0,
            r_multiple=-abs(r_multiple),
            outcome=outcome,
            hold_duration_seconds=0.0,
        ))

    def get_feedback_metrics(self) -> Dict[str, object]:
        """Return aggregated feedback metrics for analytics.

        Returns
        -------
        Dict
            Contains overall win rate, per-channel stats, and per-setup
            stats for dashboard and analytics integration.
        """
        total = len(self._outcomes)
        if total == 0:
            return {
                "total_outcomes": 0,
                "overall_win_rate": 0.0,
                "avg_r_multiple": 0.0,
                "per_channel": {},
                "per_setup": {},
            }

        wins = sum(1 for o in self._outcomes if o.outcome in _WIN_OUTCOMES)
        avg_r = sum(o.r_multiple for o in self._outcomes) / total

        # Per-channel metrics
        per_channel: Dict[str, Dict[str, float]] = {}
        channel_groups: Dict[str, list[TradeOutcome]] = {}
        for o in self._outcomes:
            channel_groups.setdefault(o.channel, []).append(o)
        for ch, records in channel_groups.items():
            ch_wins = sum(1 for r in records if r.outcome in _WIN_OUTCOMES)
            ch_total = len(records)
            per_channel[ch] = {
                "total": ch_total,
                "win_rate": ch_wins / ch_total if ch_total > 0 else 0.0,
                "avg_r_multiple": sum(r.r_multiple for r in records) / ch_total,
            }

        # Per-setup metrics
        per_setup: Dict[str, Dict[str, float]] = {}
        setup_groups: Dict[str, list[TradeOutcome]] = {}
        for o in self._outcomes:
            setup_groups.setdefault(o.setup_class, []).append(o)
        for setup, records in setup_groups.items():
            s_wins = sum(1 for r in records if r.outcome in _WIN_OUTCOMES)
            s_total = len(records)
            per_setup[setup] = {
                "total": s_total,
                "win_rate": s_wins / s_total if s_total > 0 else 0.0,
                "avg_r_multiple": sum(r.r_multiple for r in records) / s_total,
            }

        return {
            "total_outcomes": total,
            "overall_win_rate": wins / total if total > 0 else 0.0,
            "avg_r_multiple": avg_r,
            "per_channel": per_channel,
            "per_setup": per_setup,
        }

    def get_retraining_data(self) -> list[Dict]:
        """Export outcome data for offline retraining.

        Returns
        -------
        list[Dict]
            List of dicts with outcome features suitable for ML training.
        """
        data = []
        for o in self._outcomes:
            data.append({
                "symbol": o.symbol,
                "channel": o.channel,
                "direction": o.direction,
                "setup_class": o.setup_class,
                "market_state": o.market_state,
                "confidence": o.confidence,
                "r_multiple": o.r_multiple,
                "outcome": o.outcome,
                "hold_duration_seconds": o.hold_duration_seconds,
                "is_win": o.outcome in _WIN_OUTCOMES,
                **{f"score_{k}": v for k, v in o.component_scores.items()},
            })
        return data

    def should_retrain(self, min_new_outcomes: int = 50) -> bool:
        """Check whether enough new data has accumulated for retraining.

        Parameters
        ----------
        min_new_outcomes:
            Minimum number of outcomes required to trigger a retrain.

        Returns
        -------
        bool
            ``True`` when the outcome history has at least
            ``min_new_outcomes`` records.
        """
        return len(self._outcomes) >= min_new_outcomes

    # ------------------------------------------------------------------
    # Persistent storage (PR: Feedback Loop Integration)
    # ------------------------------------------------------------------

    _FEEDBACK_DATA_PATH: str = "data/feedback_outcomes.json"

    def save_outcomes(self, path: Optional[str] = None) -> None:
        """Persist all recorded outcomes to a JSON file.

        Parameters
        ----------
        path:
            File path to write.  Defaults to ``data/feedback_outcomes.json``.
        """
        path = path or self._FEEDBACK_DATA_PATH
        data = self.get_retraining_data()
        try:
            dir_name = _os.path.dirname(path)
            if dir_name:
                _os.makedirs(dir_name, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(data, fh, indent=2, default=str)
            log.info("Saved {} feedback outcomes to {}", len(data), path)
        except OSError as exc:
            log.warning("Failed to save feedback outcomes: {}", exc)

    def load_outcomes(self, path: Optional[str] = None) -> int:
        """Load previously saved outcomes from a JSON file.

        Loaded outcomes are appended via :meth:`record_outcome` so that
        weight adjustments are recomputed automatically.

        Parameters
        ----------
        path:
            File path to read.  Defaults to ``data/feedback_outcomes.json``.

        Returns
        -------
        int
            Number of outcomes loaded.
        """
        path = path or self._FEEDBACK_DATA_PATH
        if not _os.path.isfile(path):
            log.debug("No feedback file at {} – skipping load", path)
            return 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = _json.load(fh)
            if not isinstance(data, list):
                log.warning("Feedback file {} has unexpected format", path)
                return 0
            count = 0
            for record in data:
                try:
                    outcome = TradeOutcome(
                        symbol=record.get("symbol", ""),
                        channel=record.get("channel", ""),
                        direction=record.get("direction", "LONG"),
                        setup_class=record.get("setup_class", ""),
                        market_state=record.get("market_state", ""),
                        component_scores={
                            k.replace("score_", ""): v
                            for k, v in record.items()
                            if k.startswith("score_")
                        },
                        confidence=float(record.get("confidence", 70.0)),
                        r_multiple=float(record.get("r_multiple", 0.0)),
                        outcome=record.get("outcome", "SL"),
                        hold_duration_seconds=float(
                            record.get("hold_duration_seconds", 0.0)
                        ),
                    )
                    self._outcomes.append(outcome)
                    count += 1
                except (TypeError, ValueError, KeyError) as exc:
                    log.debug("Skipping malformed feedback record: {}", exc)
            if count > 0:
                self._recompute_weights()
            log.info("Loaded {} feedback outcomes from {}", count, path)
            return count
        except (OSError, _json.JSONDecodeError) as exc:
            log.warning("Failed to load feedback outcomes: {}", exc)
            return 0

    # ------------------------------------------------------------------
    # Online learning / periodic retraining (PR: Feedback Loop Integration)
    # ------------------------------------------------------------------

    def apply_online_update(self) -> Dict[str, float]:
        """Apply an online learning update based on recent outcomes.

        Recomputes weight adjustments from the current outcome history
        and returns the updated adjustment map.  This is a lightweight
        alternative to full model retraining — it simply re-analyses the
        outcome deque and refreshes the internal weight tables.

        Returns
        -------
        Dict[str, float]
            Mapping of ``"channel|setup_class"`` → adjustment value.
        """
        self._recompute_weights()
        result: Dict[str, float] = {}
        for (channel, setup_class), adj in self._weight_adjustments.items():
            result[f"{channel}|{setup_class}"] = adj
        log.info(
            "Online update applied: {} weight adjustments",
            len(result),
        )
        return result

    async def run_periodic_retraining(
        self,
        interval_seconds: float = 3600.0,
        min_outcomes: int = 50,
        save_path: Optional[str] = None,
    ) -> None:
        """Async loop that periodically retrains and persists outcomes.

        Runs indefinitely, checking every *interval_seconds* whether
        enough new outcomes have accumulated for a retraining pass.
        When triggered, recomputes weights and saves the outcome history
        to disk.

        Parameters
        ----------
        interval_seconds:
            Seconds between retraining checks.
        min_outcomes:
            Minimum outcomes required to trigger a retrain.
        save_path:
            Optional file path for persistence.
        """
        while True:
            await _asyncio.sleep(interval_seconds)
            if self.should_retrain(min_new_outcomes=min_outcomes):
                log.info(
                    "Periodic retraining triggered ({} outcomes)",
                    len(self._outcomes),
                )
                self.apply_online_update()
                self.save_outcomes(path=save_path)
            else:
                log.debug(
                    "Periodic retraining skipped ({} < {} outcomes)",
                    len(self._outcomes), min_outcomes,
                )


# ---------------------------------------------------------------------------
# Setup-specific tracking and adaptive gates
# ---------------------------------------------------------------------------

from typing import List, Tuple  # noqa: E402
import hashlib as _hashlib  # noqa: E402


class SetupWinRateTracker:
    """Tracks win rate per (setup_class, regime) combination.

    Records individual trade outcomes and provides aggregated statistics
    for setup/regime pairs to support adaptive confidence adjustments.
    """

    def __init__(self) -> None:
        # key = (setup_class, regime) → list of (won, pnl_pct)
        self._records: Dict[Tuple[str, str], list] = {}

    def record_outcome(
        self, setup_class: str, regime: str, won: bool, pnl_pct: float
    ) -> None:
        """Record a trade outcome for a setup/regime pair."""
        key = (setup_class, regime)
        self._records.setdefault(key, []).append((won, pnl_pct))

    def get_setup_win_rate(
        self, setup_class: str, regime: str
    ) -> Optional[float]:
        """Return the win rate for *setup_class* in *regime*, or ``None`` if < 10 samples."""
        samples = self._records.get((setup_class, regime), [])
        if len(samples) < 10:
            return None
        wins = sum(1 for won, _ in samples if won)
        return wins / len(samples)

    def get_best_setups(
        self, regime: str, min_samples: int = 10
    ) -> List[Tuple[str, float]]:
        """Return setups sorted by win rate (best first) for *regime*."""
        results: List[Tuple[str, float]] = []
        for (sc, reg), samples in self._records.items():
            if reg != regime or len(samples) < min_samples:
                continue
            wr = sum(1 for won, _ in samples if won) / len(samples)
            results.append((sc, wr))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def get_worst_setups(
        self, regime: str, min_samples: int = 10
    ) -> List[Tuple[str, float]]:
        """Return setups sorted by win rate (worst first) for *regime*."""
        results: List[Tuple[str, float]] = []
        for (sc, reg), samples in self._records.items():
            if reg != regime or len(samples) < min_samples:
                continue
            wr = sum(1 for won, _ in samples if won) / len(samples)
            results.append((sc, wr))
        results.sort(key=lambda x: x[1])
        return results

    def get_setup_adjustment(self, setup_class: str, regime: str) -> float:
        """Return a confidence adjustment based on historical win rate.

        Returns
        -------
        float
            Adjustment in points: +5, +2, 0, -3, or -8.
            Returns 0.0 if fewer than 10 samples are available.
        """
        wr = self.get_setup_win_rate(setup_class, regime)
        if wr is None:
            return 0.0
        if wr >= 0.65:
            return 5.0
        if wr >= 0.55:
            return 2.0
        if wr >= 0.45:
            return 0.0
        if wr >= 0.35:
            return -3.0
        return -8.0


class AdaptiveGateThresholds:
    """Tracks gate firing patterns and adjusts thresholds adaptively.

    A gate that blocks too many eventual winners is loosened; a gate
    that passes too many eventual losers is tightened.  Adjustments
    are clamped to ±20 % of the base threshold.
    """

    def __init__(self) -> None:
        # gate_name → list of (fired, signal_won)
        self._records: Dict[str, list] = {}

    def record_gate_outcome(
        self, gate_name: str, fired: bool, signal_won: Optional[bool] = None
    ) -> None:
        """Record whether a gate fired and (optionally) the signal outcome."""
        self._records.setdefault(gate_name, []).append((fired, signal_won))

    def get_adjusted_threshold(
        self, gate_name: str, base_threshold: float
    ) -> float:
        """Return an adjusted threshold for *gate_name*.

        Logic
        -----
        * If the gate fires on >60 % of signals that would have won →
          loosen (reduce) threshold by 10 %.
        * If the gate passes >70 % of signals that lose →
          tighten (increase) threshold by 10 %.
        * Adjustments clamped to ±20 % of *base_threshold*.
        * Minimum 30 samples before any adjustment is made.
        """
        records = self._records.get(gate_name, [])
        # Only consider records with known outcomes
        known = [(fired, won) for fired, won in records if won is not None]
        if len(known) < 30:
            return base_threshold

        # Check over-filtering: gate fires on winners
        winners = [(fired, won) for fired, won in known if won]
        if winners:
            fired_on_winners = sum(1 for fired, _ in winners if fired)
            if fired_on_winners / len(winners) > 0.60:
                # Too aggressive → loosen by 10 %, clamped to -20 %
                adjustment = max(-0.20, -0.10)
                return round(base_threshold * (1.0 + adjustment), 6)

        # Check under-filtering: gate passes losers
        losers = [(fired, won) for fired, won in known if not won]
        if losers:
            passed_losers = sum(1 for fired, _ in losers if not fired)
            if passed_losers / len(losers) > 0.70:
                # Too lenient → tighten by 10 %, clamped to +20 %
                adjustment = min(0.20, 0.10)
                return round(base_threshold * (1.0 + adjustment), 6)

        return base_threshold


class ABTestManager:
    """Simple A/B testing framework for signal processing variants.

    Allows registering experiments with named variants, deterministically
    assigning signals to variants, and tracking per-variant outcomes.
    """

    def __init__(self) -> None:
        # experiment_name → list of variant names
        self._experiments: Dict[str, List[str]] = {}
        # (experiment_name, variant) → list of (won, pnl_pct)
        self._outcomes: Dict[Tuple[str, str], list] = {}

    def register_experiment(self, name: str, variants: List[str]) -> None:
        """Register an experiment with the given variant names.

        Parameters
        ----------
        name:
            Unique experiment identifier.
        variants:
            List of variant labels (e.g. ``["current", "new_weights"]``).
        """
        self._experiments[name] = list(variants)
        for v in variants:
            self._outcomes.setdefault((name, v), [])

    def get_variant(self, experiment_name: str, signal_id: str) -> str:
        """Deterministically assign *signal_id* to a variant.

        Uses a hash of the signal ID to ensure consistent assignment
        across calls for the same signal.

        Returns the first variant if the experiment is unknown.
        """
        variants = self._experiments.get(experiment_name)
        if not variants:
            return ""
        digest = int(_hashlib.sha256(signal_id.encode()).hexdigest(), 16)
        return variants[digest % len(variants)]

    def record_outcome(
        self, experiment_name: str, variant: str, won: bool, pnl_pct: float
    ) -> None:
        """Record the outcome for a signal assigned to *variant*."""
        self._outcomes.setdefault((experiment_name, variant), []).append(
            (won, pnl_pct)
        )

    def get_results(self, experiment_name: str) -> Dict[str, dict]:
        """Return per-variant aggregate statistics.

        Returns
        -------
        Dict[str, dict]
            Mapping of variant → ``{"n": int, "win_rate": float, "avg_pnl": float}``.
        """
        variants = self._experiments.get(experiment_name, [])
        results: Dict[str, dict] = {}
        for v in variants:
            records = self._outcomes.get((experiment_name, v), [])
            n = len(records)
            if n == 0:
                results[v] = {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0}
                continue
            wins = sum(1 for won, _ in records if won)
            avg_pnl = sum(pnl for _, pnl in records) / n
            results[v] = {
                "n": n,
                "win_rate": round(wins / n, 4),
                "avg_pnl": round(avg_pnl, 4),
            }
        return results

    def get_winner(
        self, experiment_name: str, min_samples: int = 50
    ) -> Optional[str]:
        """Return the best-performing variant, or ``None`` if insufficient data.

        A variant must have at least *min_samples* outcomes to be eligible.
        The winner is determined by highest win rate.
        """
        results = self.get_results(experiment_name)
        eligible = {
            v: stats
            for v, stats in results.items()
            if stats["n"] >= min_samples
        }
        if not eligible:
            return None
        return max(eligible, key=lambda v: eligible[v]["win_rate"])
