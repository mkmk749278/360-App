"""Per-pair anomaly detection engine.

Scans trading history to identify repeated failures, regime misalignment,
session underperformance, and other structural issues that degrade signal
quality.  Anomalies feed into the recommendation engine and can trigger
automatic signal suppression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.performance_metrics import is_breakeven_pnl
from src.utils import get_logger

log = get_logger("pair_anomaly_detector")

# Minimum signals required before an anomaly is flagged
_MIN_SIGNALS_FOR_ANOMALY = 5
_MIN_REGIME_SIGNALS = 5
_MIN_SESSION_SIGNALS = 5
_MIN_WEEKEND_SIGNALS = 3


@dataclass
class PairAnomaly:
    """A detected anomaly for a single pair."""

    symbol: str
    anomaly_type: str
    severity: str  # LOW / MEDIUM / HIGH / CRITICAL
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""


def detect_pair_anomalies(
    symbol: str,
    tracker: Any,
    quality: Any,
    snapshot: Any,
    window_days: int = 30,
) -> List[PairAnomaly]:
    """Run all anomaly detectors for a pair and return sorted results.

    Parameters
    ----------
    symbol:
        Trading pair (e.g. ``"BTCUSDT"``).
    tracker:
        :class:`~src.performance_tracker.PerformanceTracker` instance.
    quality:
        :class:`~src.pair_analyzer.PairSignalQuality` instance.
    snapshot:
        :class:`~src.pair_analyzer.PairSnapshot` instance.
    window_days:
        Lookback period for analysis.
    """
    anomalies: List[PairAnomaly] = []

    if quality.total_signals < _MIN_SIGNALS_FOR_ANOMALY:
        return anomalies

    anomalies.extend(_check_regime_misalignment(symbol, tracker, window_days))
    anomalies.extend(_check_session_underperformance(symbol, tracker, window_days))
    anomalies.extend(_check_weekend_weakness(symbol, tracker, window_days))
    anomalies.extend(_check_declining_performance(symbol, quality))
    anomalies.extend(_check_excessive_drawdown(symbol, quality))
    anomalies.extend(_check_low_hit_rate_regime(symbol, tracker, window_days))
    anomalies.extend(_check_mfe_waste(symbol, quality))
    anomalies.extend(_check_btc_correlation_ignored(symbol, snapshot, quality))
    anomalies.extend(_check_consecutive_failures(symbol, tracker, window_days))

    # Sort by severity: CRITICAL → HIGH → MEDIUM → LOW
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    anomalies.sort(key=lambda a: severity_order.get(a.severity, 4))

    return anomalies


# ---------------------------------------------------------------------------
# Individual anomaly detectors
# ---------------------------------------------------------------------------


def _check_regime_misalignment(
    symbol: str, tracker: Any, window_days: int,
) -> List[PairAnomaly]:
    """Flag pairs where >40% of signals occurred in incompatible regimes."""
    anomalies: List[PairAnomaly] = []
    regime_stats = tracker.get_pair_stats_by_regime(symbol, window_days=window_days)
    total_signals = sum(s.get("count", 0) for s in regime_stats.values())
    if total_signals < _MIN_SIGNALS_FOR_ANOMALY:
        return anomalies

    bad_regime_count = 0
    bad_regimes: List[str] = []
    for regime, stats in regime_stats.items():
        count = stats.get("count", 0)
        wr = stats.get("win_rate", 0.0)
        if count >= 3 and wr < 30.0:
            bad_regime_count += count
            bad_regimes.append(f"{regime}(WR={wr:.0f}%,n={count})")

    if total_signals > 0 and bad_regime_count / total_signals > 0.4:
        anomalies.append(PairAnomaly(
            symbol=symbol,
            anomaly_type="REGIME_MISALIGNMENT",
            severity="HIGH",
            description=(
                f"{bad_regime_count}/{total_signals} signals "
                f"({bad_regime_count/total_signals*100:.0f}%) fired in poor regimes: "
                f"{', '.join(bad_regimes)}"
            ),
            evidence={"bad_regimes": bad_regimes, "pct": bad_regime_count / total_signals},
            recommendation="Add regime-specific suppression or confidence penalty",
        ))
    return anomalies


def _check_session_underperformance(
    symbol: str, tracker: Any, window_days: int,
) -> List[PairAnomaly]:
    """Flag sessions with WR < 30% and at least N signals."""
    anomalies: List[PairAnomaly] = []
    session_stats = tracker.get_pair_stats_by_session(symbol, window_days=window_days)
    for session, stats in session_stats.items():
        count = stats.get("count", 0)
        wr = stats.get("win_rate", 0.0)
        if count >= _MIN_SESSION_SIGNALS and wr < 30.0:
            anomalies.append(PairAnomaly(
                symbol=symbol,
                anomaly_type="SESSION_UNDERPERFORMANCE",
                severity="MEDIUM",
                description=(
                    f"Win rate in {session} is {wr:.1f}% over {count} signals"
                ),
                evidence={"session": session, "win_rate": wr, "count": count},
                recommendation=f"Suppress or penalise signals in {session}",
            ))
    return anomalies


def _check_weekend_weakness(
    symbol: str, tracker: Any, window_days: int,
) -> List[PairAnomaly]:
    """Flag poor weekend performance."""
    anomalies: List[PairAnomaly] = []
    weekday_stats = tracker.get_pair_stats_by_weekday(symbol, window_days=window_days)
    weekend_wins = 0
    weekend_losses = 0
    for _day, stats in weekday_stats.items():
        if stats.get("is_weekend", False):
            weekend_wins += stats.get("wins", 0)
            weekend_losses += stats.get("losses", 0)

    total = weekend_wins + weekend_losses
    if total >= _MIN_WEEKEND_SIGNALS:
        wr = weekend_wins / total * 100
        if wr < 35.0:
            anomalies.append(PairAnomaly(
                symbol=symbol,
                anomaly_type="WEEKEND_WEAKNESS",
                severity="MEDIUM",
                description=f"Weekend WR={wr:.1f}% ({weekend_wins}W/{weekend_losses}L)",
                evidence={"weekend_wr": wr, "total": total},
                recommendation="Add weekend confidence penalty or suppress",
            ))
    return anomalies


def _check_declining_performance(
    symbol: str, quality: Any,
) -> List[PairAnomaly]:
    """Flag pairs with DEGRADING consistency trend."""
    anomalies: List[PairAnomaly] = []
    if quality.consistency_trend == "DEGRADING":
        anomalies.append(PairAnomaly(
            symbol=symbol,
            anomaly_type="DECLINING_PERFORMANCE",
            severity="HIGH",
            description=(
                f"Signal quality is degrading (consistency score: "
                f"{quality.consistency_score:.0f}/100)"
            ),
            evidence={
                "trend": quality.consistency_trend,
                "score": quality.consistency_score,
            },
            recommendation="Review pair logic; consider temporary suppression",
        ))
    return anomalies


def _check_excessive_drawdown(
    symbol: str, quality: Any,
) -> List[PairAnomaly]:
    """Flag pairs with excessive drawdown."""
    anomalies: List[PairAnomaly] = []
    if quality.current_drawdown > 10.0:
        anomalies.append(PairAnomaly(
            symbol=symbol,
            anomaly_type="EXCESSIVE_DRAWDOWN",
            severity="CRITICAL",
            description=(
                f"Current drawdown {quality.current_drawdown:.1f}% "
                f"(max={quality.max_drawdown:.1f}%)"
            ),
            evidence={
                "current_dd": quality.current_drawdown,
                "max_dd": quality.max_drawdown,
            },
            recommendation="Reduce position size or suppress temporarily",
        ))
    elif quality.max_drawdown > 15.0:
        anomalies.append(PairAnomaly(
            symbol=symbol,
            anomaly_type="EXCESSIVE_DRAWDOWN",
            severity="HIGH",
            description=f"Max drawdown reached {quality.max_drawdown:.1f}%",
            evidence={"max_dd": quality.max_drawdown},
            recommendation="Review SL placement and position sizing",
        ))
    return anomalies


def _check_low_hit_rate_regime(
    symbol: str, tracker: Any, window_days: int,
) -> List[PairAnomaly]:
    """Flag any regime with WR < 30% and sufficient samples."""
    anomalies: List[PairAnomaly] = []
    regime_stats = tracker.get_pair_stats_by_regime(symbol, window_days=window_days)
    for regime, stats in regime_stats.items():
        count = stats.get("count", 0)
        wr = stats.get("win_rate", 0.0)
        if count >= _MIN_REGIME_SIGNALS and wr < 30.0:
            anomalies.append(PairAnomaly(
                symbol=symbol,
                anomaly_type="LOW_HIT_RATE_REGIME",
                severity="HIGH",
                description=(
                    f"WR={wr:.1f}% in {regime} regime over {count} signals"
                ),
                evidence={"regime": regime, "win_rate": wr, "count": count},
                recommendation=f"Add hard suppression for {symbol} in {regime}",
            ))
    return anomalies


def _check_mfe_waste(symbol: str, quality: Any) -> List[PairAnomaly]:
    """Flag pairs leaving too much profit on the table (MFE >> realized PnL)."""
    anomalies: List[PairAnomaly] = []
    if (
        quality.avg_mfe > 0
        and quality.expectancy_val > 0
        and quality.avg_mfe > 2.0 * quality.expectancy_val
    ):
        anomalies.append(PairAnomaly(
            symbol=symbol,
            anomaly_type="MFE_WASTE",
            severity="MEDIUM",
            description=(
                f"Avg MFE={quality.avg_mfe:.2f}% vs avg PnL={quality.expectancy_val:.2f}%: "
                f"leaving profit on the table"
            ),
            evidence={
                "avg_mfe": quality.avg_mfe,
                "avg_pnl": quality.expectancy_val,
            },
            recommendation="Extend TP3 ratio to capture more of the move",
        ))
    return anomalies


def _check_btc_correlation_ignored(
    symbol: str, snapshot: Any, quality: Any,
) -> List[PairAnomaly]:
    """Flag high BTC correlation without accounting for it in quality."""
    anomalies: List[PairAnomaly] = []
    if (
        abs(snapshot.btc_corr_short) >= 0.7
        and quality.quality_label in ("WEAK", "CRITICAL")
    ):
        anomalies.append(PairAnomaly(
            symbol=symbol,
            anomaly_type="BTC_CORRELATION_IGNORED",
            severity="HIGH",
            description=(
                f"BTC correlation={snapshot.btc_corr_short:.2f} "
                f"(role={snapshot.btc_role}) but signal quality is "
                f"{quality.quality_label}"
            ),
            evidence={
                "btc_corr": snapshot.btc_corr_short,
                "role": snapshot.btc_role,
            },
            recommendation="Increase cross-asset gate strictness for this pair",
        ))
    return anomalies


def _check_consecutive_failures(
    symbol: str, tracker: Any, window_days: int,
) -> List[PairAnomaly]:
    """Flag pairs with streaks of 3+ consecutive losses in recent history."""
    anomalies: List[PairAnomaly] = []
    pnl_list = tracker.get_pair_pnl_list(symbol, window_days=window_days)
    if len(pnl_list) < 3:
        return anomalies

    max_streak = 0
    current_streak = 0
    for pnl in pnl_list:
        if pnl < 0 and not is_breakeven_pnl(pnl):
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    if max_streak >= 3:
        anomalies.append(PairAnomaly(
            symbol=symbol,
            anomaly_type="CONSECUTIVE_FAILURES",
            severity="HIGH" if max_streak >= 5 else "MEDIUM",
            description=f"{max_streak} consecutive losses detected",
            evidence={"max_streak": max_streak},
            recommendation=(
                "Investigate signal logic; consider cooling period after "
                f"{max_streak} consecutive losses"
            ),
        ))
    return anomalies
