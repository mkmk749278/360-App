"""Per-pair analysis report generator.

Orchestrates the full analysis pipeline and produces structured reports
in multiple formats: plain-text summary, Telegram message, and JSON.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from src.pair_analyzer import (
    PairRecommendation,
    PairSignalQuality,
    PairSnapshot,
    build_pair_snapshot,
    compute_pair_signal_quality,
    generate_pair_recommendations,
)
from src.pair_anomaly_detector import PairAnomaly, detect_pair_anomalies
from src.utils import get_logger

log = get_logger("pair_analysis_report")


@dataclass
class PairAnalysisResult:
    """Complete analysis result for a single pair."""

    symbol: str
    snapshot: PairSnapshot
    quality: PairSignalQuality
    regime_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    session_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    weekday_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    anomalies: List[PairAnomaly] = field(default_factory=list)
    recommendations: List[PairRecommendation] = field(default_factory=list)


@dataclass
class FullAnalysisReport:
    """Aggregate report across all analysed pairs."""

    generated_at: str = ""
    total_pairs_analyzed: int = 0
    pair_results: Dict[str, PairAnalysisResult] = field(default_factory=dict)
    # Aggregated summaries
    quality_distribution: Dict[str, int] = field(default_factory=dict)
    all_anomalies: List[PairAnomaly] = field(default_factory=list)
    top_recommendations: List[PairRecommendation] = field(default_factory=list)
    # Impact assessment
    pairs_to_suppress: List[str] = field(default_factory=list)
    estimated_bad_signal_reduction_pct: float = 0.0


def run_pair_analysis(
    tracker: Any,
    symbols: List[str],
    window_days: int = 30,
    snapshots: Optional[Dict[str, PairSnapshot]] = None,
) -> FullAnalysisReport:
    """Run the complete per-pair analysis pipeline.

    Parameters
    ----------
    tracker:
        :class:`~src.performance_tracker.PerformanceTracker` instance.
    symbols:
        List of symbols to analyse (e.g. from tracker.get_all_traded_symbols()).
    window_days:
        Lookback period for historical analysis.
    snapshots:
        Optional pre-built pair snapshots.  When ``None``, minimal
        snapshots are constructed from historical data only.

    Returns
    -------
    :class:`FullAnalysisReport` with all per-pair results and summaries.
    """
    report = FullAnalysisReport()
    report.generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    quality_dist: Dict[str, int] = {}
    all_anomalies: List[PairAnomaly] = []
    all_recommendations: List[PairRecommendation] = []
    suppress_candidates: List[str] = []

    total_signals_all = 0
    total_bad_signals = 0

    for symbol in symbols:
        # Build or reuse snapshot
        snap = (snapshots or {}).get(symbol) or PairSnapshot(symbol=symbol)

        # Compute quality
        quality = compute_pair_signal_quality(tracker, symbol, window_days=window_days)

        # Gather per-pair analytics
        regime_stats = tracker.get_pair_stats_by_regime(symbol, window_days=window_days)
        session_stats = tracker.get_pair_stats_by_session(symbol, window_days=window_days)
        weekday_stats = tracker.get_pair_stats_by_weekday(symbol, window_days=window_days)

        # Detect anomalies
        anomalies = detect_pair_anomalies(
            symbol=symbol,
            tracker=tracker,
            quality=quality,
            snapshot=snap,
            window_days=window_days,
        )

        # Generate recommendations
        recommendations = generate_pair_recommendations(
            symbol=symbol,
            snapshot=snap,
            quality=quality,
            regime_stats=regime_stats,
            session_stats=session_stats,
            weekday_stats=weekday_stats,
            anomalies=anomalies,
        )

        result = PairAnalysisResult(
            symbol=symbol,
            snapshot=snap,
            quality=quality,
            regime_stats=regime_stats,
            session_stats=session_stats,
            weekday_stats=weekday_stats,
            anomalies=anomalies,
            recommendations=recommendations,
        )
        report.pair_results[symbol] = result

        # Aggregate
        label = quality.quality_label
        quality_dist[label] = quality_dist.get(label, 0) + 1
        all_anomalies.extend(anomalies)
        all_recommendations.extend(recommendations)

        # Impact estimation
        total_signals_all += quality.total_signals
        if quality.quality_label == "CRITICAL":
            suppress_candidates.append(symbol)
            total_bad_signals += quality.total_signals
        elif quality.quality_label == "WEAK":
            # Count the proportion of signals in bad regimes/sessions
            for _regime, stats in regime_stats.items():
                if stats.get("count", 0) >= 5 and stats.get("win_rate", 0.0) < 35.0:
                    total_bad_signals += stats.get("count", 0)

    report.total_pairs_analyzed = len(symbols)
    report.quality_distribution = quality_dist
    report.all_anomalies = sorted(
        all_anomalies,
        key=lambda a: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(a.severity, 4),
    )
    report.top_recommendations = sorted(
        all_recommendations,
        key=lambda r: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(r.priority, 3),
    )[:20]
    report.pairs_to_suppress = suppress_candidates

    if total_signals_all > 0:
        report.estimated_bad_signal_reduction_pct = round(
            total_bad_signals / total_signals_all * 100, 1
        )

    return report


# ---------------------------------------------------------------------------
# Report formatters
# ---------------------------------------------------------------------------


def format_telegram_summary(report: FullAnalysisReport) -> str:
    """Format the analysis report as a compact Telegram message."""
    lines = [
        "📊 *Per-Pair Analysis Report*",
        f"Generated: {report.generated_at}",
        f"Pairs analysed: {report.total_pairs_analyzed}",
        "",
    ]

    # Quality distribution
    lines.append("*Signal Quality Distribution:*")
    for label, count in sorted(report.quality_distribution.items()):
        emoji = {"STRONG": "🟢", "ACCEPTABLE": "🟡", "WEAK": "🟠", "CRITICAL": "🔴"}.get(
            label, "⚪"
        )
        lines.append(f"  {emoji} {label}: {count}")
    lines.append("")

    # Impact
    if report.pairs_to_suppress:
        lines.append(f"🚫 *Pairs to suppress:* {', '.join(report.pairs_to_suppress)}")
    lines.append(
        f"📉 *Est. bad signal reduction:* {report.estimated_bad_signal_reduction_pct:.1f}%"
    )
    lines.append("")

    # Top anomalies (max 5)
    if report.all_anomalies:
        lines.append("⚠️ *Top Anomalies:*")
        for a in report.all_anomalies[:5]:
            sev_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}.get(
                a.severity, "⚪"
            )
            lines.append(f"  {sev_emoji} [{a.symbol}] {a.description}")
        lines.append("")

    # Top recommendations (max 5)
    if report.top_recommendations:
        lines.append("💡 *Top Recommendations:*")
        for r in report.top_recommendations[:5]:
            lines.append(f"  • [{r.symbol}] {r.title}")
        lines.append("")

    return "\n".join(lines)


def format_detailed_report(report: FullAnalysisReport) -> str:
    """Format a detailed plain-text report."""
    lines = [
        "=" * 70,
        "PER-PAIR ANALYSIS REPORT",
        f"Generated: {report.generated_at}",
        f"Pairs analysed: {report.total_pairs_analyzed}",
        "=" * 70,
        "",
    ]

    # Quality distribution
    lines.append("SIGNAL QUALITY DISTRIBUTION")
    lines.append("-" * 40)
    for label, count in sorted(report.quality_distribution.items()):
        lines.append(f"  {label:20s}: {count}")
    lines.append("")

    # Impact summary
    lines.append("IMPACT ASSESSMENT")
    lines.append("-" * 40)
    lines.append(f"  Pairs to suppress:           {len(report.pairs_to_suppress)}")
    if report.pairs_to_suppress:
        lines.append(f"  Suppress list:               {', '.join(report.pairs_to_suppress)}")
    lines.append(
        f"  Est. bad signal reduction:   {report.estimated_bad_signal_reduction_pct:.1f}%"
    )
    lines.append(f"  Total anomalies detected:    {len(report.all_anomalies)}")
    lines.append(f"  Total recommendations:       {len(report.top_recommendations)}")
    lines.append("")

    # Per-pair detail
    for symbol, result in sorted(report.pair_results.items()):
        q = result.quality
        s = result.snapshot
        lines.append(f"{'─' * 60}")
        lines.append(f"PAIR: {symbol} ({s.pair_tier})")
        lines.append(f"{'─' * 60}")
        lines.append(f"  Quality:      {q.quality_label} | Hit Rate: {q.hit_rate:.1f}%")
        lines.append(f"  R:R Ratio:    {q.risk_reward:.2f} | Sharpe: {q.sharpe:.2f}")
        lines.append(f"  Expectancy:   {q.expectancy_val:+.3f}% | PF: {q.profit_factor_val:.2f}")
        lines.append(f"  Max DD:       {q.max_drawdown:.1f}% | Current DD: {q.current_drawdown:.1f}%")
        lines.append(f"  Consistency:  {q.consistency_score:.0f}/100 ({q.consistency_trend})")
        lines.append(f"  Signals:      {q.total_signals}")
        lines.append(f"  Volatility:   {s.volatility_label} (ATR pctl: {s.atr_percentile:.0f})")
        lines.append(f"  Liquidity:    {s.liquidity_label}")
        lines.append(f"  Regime:       {s.regime}")
        lines.append(f"  BTC Corr:     short={s.btc_corr_short:.2f} long={s.btc_corr_long:.2f}")
        lines.append(f"  BTC Role:     {s.btc_role} (lag={s.btc_best_lag})")
        if q.weak_areas:
            lines.append(f"  Weak Areas:   {', '.join(q.weak_areas)}")

        # Regime stats
        if result.regime_stats:
            lines.append("  Regime Performance:")
            for regime, stats in result.regime_stats.items():
                lines.append(
                    f"    {regime:18s}: WR={stats['win_rate']:5.1f}% "
                    f"n={stats['count']:3d} avgPnL={stats['avg_pnl']:+.2f}%"
                )

        # Session stats
        if result.session_stats:
            lines.append("  Session Performance:")
            for session, stats in result.session_stats.items():
                lines.append(
                    f"    {session:20s}: WR={stats['win_rate']:5.1f}% "
                    f"n={stats['count']:3d} avgPnL={stats['avg_pnl']:+.2f}%"
                )

        # Anomalies
        if result.anomalies:
            lines.append("  Anomalies:")
            for a in result.anomalies:
                lines.append(f"    [{a.severity}] {a.anomaly_type}: {a.description}")

        # Recommendations
        if result.recommendations:
            lines.append("  Recommendations:")
            for r in result.recommendations:
                lines.append(f"    [{r.priority}] {r.title}")

        lines.append("")

    # Anomaly summary
    if report.all_anomalies:
        lines.append("=" * 70)
        lines.append("ALL ANOMALIES (sorted by severity)")
        lines.append("=" * 70)
        for a in report.all_anomalies:
            lines.append(f"  [{a.severity}] {a.symbol} — {a.anomaly_type}: {a.description}")
        lines.append("")

    # Top recommendations
    if report.top_recommendations:
        lines.append("=" * 70)
        lines.append("TOP RECOMMENDATIONS")
        lines.append("=" * 70)
        for i, r in enumerate(report.top_recommendations, 1):
            lines.append(f"  {i:2d}. [{r.priority}] {r.symbol}: {r.title}")
            lines.append(f"      {r.description}")
            if r.expected_impact:
                lines.append(f"      Impact: {r.expected_impact}")
        lines.append("")

    return "\n".join(lines)


def export_json(report: FullAnalysisReport) -> str:
    """Export the full report as a JSON string."""

    def _serialize(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        return str(obj)

    data = {
        "generated_at": report.generated_at,
        "total_pairs_analyzed": report.total_pairs_analyzed,
        "quality_distribution": report.quality_distribution,
        "pairs_to_suppress": report.pairs_to_suppress,
        "estimated_bad_signal_reduction_pct": report.estimated_bad_signal_reduction_pct,
        "pair_results": {
            sym: _serialize(result) for sym, result in report.pair_results.items()
        },
        "anomaly_count": len(report.all_anomalies),
        "recommendation_count": len(report.top_recommendations),
    }
    return json.dumps(data, indent=2, default=str)
