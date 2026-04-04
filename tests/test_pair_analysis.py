"""Tests for the per-pair analysis engine (pair_analyzer, pair_anomaly_detector, pair_analysis_report).

Covers:
* PerformanceTracker new methods: get_pair_stats_by_regime, get_pair_stats_by_session,
  get_pair_stats_by_weekday, get_pair_consistency, get_pair_pnl_list, get_pair_mfe_mae
* PairSnapshot builder
* PairSignalQuality computation
* Recommendation engine
* Anomaly detection
* Report generation (Telegram, detailed, JSON)
* Integration: full pipeline from records → report
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

import pytest

from src.pair_analyzer import (
    PairRecommendation,
    PairSignalQuality,
    PairSnapshot,
    build_pair_snapshot,
    compute_pair_signal_quality,
    generate_pair_recommendations,
)
from src.pair_anomaly_detector import (
    PairAnomaly,
    detect_pair_anomalies,
)
from src.pair_analysis_report import (
    FullAnalysisReport,
    PairAnalysisResult,
    export_json,
    format_detailed_report,
    format_telegram_summary,
    run_pair_analysis,
)
from src.performance_tracker import PerformanceTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tracker(tmp_path: Any) -> PerformanceTracker:
    """Create a fresh tracker with a temp storage path."""
    return PerformanceTracker(storage_path=str(tmp_path / "test_perf.json"))


def _record(
    tracker: PerformanceTracker,
    symbol: str = "BTCUSDT",
    channel: str = "360_SCALP",
    pnl_pct: float = 1.0,
    hit_tp: int = 1,
    hit_sl: bool = False,
    market_phase: str = "TRENDING_UP",
    session_name: str = "NY_LONDON_OVERLAP",
    timestamp: float = 0.0,
    mfe: float = 0.0,
    mae: float = 0.0,
) -> None:
    """Record a signal outcome with sensible defaults."""
    tracker.record_outcome(
        signal_id=f"sig-{time.monotonic_ns()}",
        channel=channel,
        symbol=symbol,
        direction="LONG",
        entry=100.0,
        hit_tp=hit_tp,
        hit_sl=hit_sl,
        pnl_pct=pnl_pct,
        confidence=70.0,
        market_phase=market_phase,
        session_name=session_name,
        max_favorable_excursion_pct=mfe,
        max_adverse_excursion_pct=mae,
    )
    # Override timestamp if specified
    if timestamp > 0:
        tracker._records[-1].timestamp = timestamp


def _fill_tracker_with_data(tracker: PerformanceTracker) -> None:
    """Fill tracker with realistic multi-pair data for integration tests."""
    now = time.time()

    # BTC — STRONG pair: 70% win rate
    for i in range(10):
        ts = now - (30 - i) * 86400
        win = i % 10 < 7  # 7 out of 10 = 70%
        _record(
            tracker,
            symbol="BTCUSDT",
            pnl_pct=1.5 if win else -0.8,
            hit_tp=2 if win else 0,
            hit_sl=not win,
            market_phase="TRENDING_UP" if i < 5 else "RANGING",
            session_name="NY_LONDON_OVERLAP" if i % 2 == 0 else "ASIAN_SESSION",
            timestamp=ts,
            mfe=2.0 if win else 0.5,
            mae=0.3 if win else 0.8,
        )

    # ETH — ACCEPTABLE pair: 50% win rate
    for i in range(10):
        ts = now - (30 - i) * 86400
        win = i % 2 == 0  # 50%
        _record(
            tracker,
            symbol="ETHUSDT",
            pnl_pct=1.0 if win else -1.0,
            hit_tp=1 if win else 0,
            hit_sl=not win,
            market_phase="RANGING",
            session_name="LONDON_OPEN",
            timestamp=ts,
            mfe=1.5 if win else 0.3,
            mae=0.4 if win else 1.0,
        )

    # DOGE — CRITICAL pair: 20% win rate
    for i in range(10):
        ts = now - (30 - i) * 86400
        win = i < 2  # Only 2 out of 10 = 20%
        _record(
            tracker,
            symbol="DOGEUSDT",
            pnl_pct=0.5 if win else -1.5,
            hit_tp=1 if win else 0,
            hit_sl=not win,
            market_phase="VOLATILE",
            session_name="ASIAN_DEAD_ZONE",
            timestamp=ts,
            mfe=0.8 if win else 0.2,
            mae=0.5 if win else 1.5,
        )

    # SOL — WEAK pair: 35% win rate, declining
    for i in range(10):
        ts = now - (30 - i) * 86400
        win = i < 3 or (i == 5)  # 4 out of 10 = 40%, but wins at start
        _record(
            tracker,
            symbol="SOLUSDT",
            pnl_pct=1.2 if win else -1.0,
            hit_tp=1 if win else 0,
            hit_sl=not win,
            market_phase="TRENDING_DOWN" if i > 5 else "TRENDING_UP",
            session_name="NY_SESSION",
            timestamp=ts,
            mfe=2.5 if win else 0.3,
            mae=0.4 if win else 1.0,
        )


# ===========================================================================
# PerformanceTracker extended methods
# ===========================================================================


class TestPerformanceTrackerExtended:
    """Tests for per-pair regime, session, weekday, consistency methods."""

    def test_get_pair_stats_by_regime(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _record(tracker, symbol="BTCUSDT", market_phase="TRENDING_UP", pnl_pct=1.0)
        _record(tracker, symbol="BTCUSDT", market_phase="TRENDING_UP", pnl_pct=0.5)
        _record(tracker, symbol="BTCUSDT", market_phase="RANGING", pnl_pct=-0.5, hit_sl=True, hit_tp=0)
        _record(tracker, symbol="ETHUSDT", market_phase="TRENDING_UP", pnl_pct=0.8)

        result = tracker.get_pair_stats_by_regime("BTCUSDT")
        assert "TRENDING_UP" in result
        assert "RANGING" in result
        assert result["TRENDING_UP"]["wins"] == 2
        assert result["RANGING"]["losses"] == 1

    def test_get_pair_stats_by_regime_empty(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        result = tracker.get_pair_stats_by_regime("UNKNOWN")
        assert result == {}

    def test_get_pair_stats_by_session(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _record(tracker, symbol="BTCUSDT", session_name="NY_LONDON_OVERLAP", pnl_pct=1.0)
        _record(tracker, symbol="BTCUSDT", session_name="ASIAN_SESSION", pnl_pct=-0.5, hit_sl=True, hit_tp=0)
        result = tracker.get_pair_stats_by_session("BTCUSDT")
        assert "NY_LONDON_OVERLAP" in result
        assert "ASIAN_SESSION" in result
        assert result["NY_LONDON_OVERLAP"]["wins"] == 1

    def test_get_pair_stats_by_weekday(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        import datetime as _dt

        # Record a Monday signal
        mon = _dt.datetime(2026, 3, 30, 12, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
        _record(tracker, symbol="BTCUSDT", pnl_pct=1.0, timestamp=mon)

        # Record a Saturday signal
        sat = _dt.datetime(2026, 3, 28, 12, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
        _record(tracker, symbol="BTCUSDT", pnl_pct=-0.5, hit_sl=True, hit_tp=0, timestamp=sat)

        result = tracker.get_pair_stats_by_weekday("BTCUSDT")
        assert "Mon" in result
        assert "Sat" in result
        assert result["Sat"]["is_weekend"] is True
        assert result["Mon"]["is_weekend"] is False

    def test_get_pair_consistency(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        for i in range(14):
            ts = now - (30 - i) * 86400
            _record(tracker, symbol="BTCUSDT", pnl_pct=1.0 if i % 2 == 0 else -0.5,
                    hit_tp=1 if i % 2 == 0 else 0,
                    hit_sl=i % 2 != 0, timestamp=ts)

        result = tracker.get_pair_consistency("BTCUSDT", window_days=30)
        assert "chunks" in result
        assert "avg_wr" in result
        assert "std_wr" in result
        assert result["trend"] in ("IMPROVING", "DEGRADING", "STABLE")
        assert isinstance(result["is_consistent"], bool)

    def test_get_pair_consistency_empty(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        result = tracker.get_pair_consistency("UNKNOWN")
        assert result["chunks"] == []
        assert result["trend"] == "STABLE"
        assert result["is_consistent"] is True

    def test_get_pair_pnl_list(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _record(tracker, symbol="BTCUSDT", pnl_pct=1.0)
        _record(tracker, symbol="BTCUSDT", pnl_pct=-0.5, hit_sl=True, hit_tp=0)
        _record(tracker, symbol="ETHUSDT", pnl_pct=0.8)

        pnls = tracker.get_pair_pnl_list("BTCUSDT")
        assert len(pnls) == 2
        assert pnls[0] == 1.0
        assert pnls[1] == -0.5

    def test_get_pair_mfe_mae(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _record(tracker, symbol="BTCUSDT", mfe=2.0, mae=0.5)
        _record(tracker, symbol="BTCUSDT", mfe=1.5, mae=0.3)

        result = tracker.get_pair_mfe_mae("BTCUSDT")
        assert len(result["mfe"]) == 2
        assert len(result["mae"]) == 2
        assert result["mfe"][0] == 2.0

    def test_get_all_traded_symbols(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _record(tracker, symbol="BTCUSDT")
        _record(tracker, symbol="ETHUSDT")
        _record(tracker, symbol="BTCUSDT")

        symbols = tracker.get_all_traded_symbols()
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
        assert len(symbols) == 2

    def test_windowed_pair_stats_by_regime(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        # Old record (40 days ago)
        _record(tracker, symbol="BTCUSDT", market_phase="VOLATILE",
                pnl_pct=-2.0, hit_sl=True, hit_tp=0, timestamp=now - 40 * 86400)
        # Recent record
        _record(tracker, symbol="BTCUSDT", market_phase="TRENDING_UP",
                pnl_pct=1.0, timestamp=now - 5 * 86400)

        result_7d = tracker.get_pair_stats_by_regime("BTCUSDT", window_days=7)
        assert "TRENDING_UP" in result_7d
        assert "VOLATILE" not in result_7d

        result_all = tracker.get_pair_stats_by_regime("BTCUSDT")
        assert "VOLATILE" in result_all


# ===========================================================================
# PairSnapshot builder
# ===========================================================================


class TestPairSnapshot:
    """Tests for build_pair_snapshot."""

    def test_basic_snapshot(self) -> None:
        snap = build_pair_snapshot("BTCUSDT", pair_tier="MAJOR")
        assert snap.symbol == "BTCUSDT"
        assert snap.pair_tier == "MAJOR"
        assert snap.volatility_label == "NORMAL"

    def test_volatility_labels(self) -> None:
        # LOW volatility
        snap = build_pair_snapshot(
            "TEST",
            indicators={"atr_percentile": 10.0, "bb_upper_last": 1.01, "bb_lower_last": 0.99,
                         "bb_mid_last": 1.0, "adx_last": 15.0},
        )
        assert snap.volatility_label == "LOW"

        # EXTREME
        snap = build_pair_snapshot(
            "TEST",
            indicators={"atr_percentile": 97.0, "bb_upper_last": 1.05, "bb_lower_last": 0.95,
                         "bb_mid_last": 1.0, "adx_last": 30.0},
        )
        assert snap.volatility_label == "EXTREME"

    def test_liquidity_labels(self) -> None:
        # THIN
        snap = build_pair_snapshot("TEST", volume_24h_usd=1_000_000, spread_pct=0.05)
        assert snap.liquidity_label == "THIN"

        # DEEP
        snap = build_pair_snapshot("TEST", volume_24h_usd=100_000_000, spread_pct=0.005)
        assert snap.liquidity_label == "DEEP"

    def test_btc_correlation(self) -> None:
        import numpy as np
        btc_closes = list(np.cumsum(np.random.randn(100)) + 100)
        pair_closes = [b * 0.5 + np.random.randn() * 0.1 for b in btc_closes]

        snap = build_pair_snapshot(
            "ETHUSDT",
            btc_closes=btc_closes,
            pair_closes=pair_closes,
        )
        # Should detect some correlation
        assert snap.btc_corr_short != 0.0
        assert snap.btc_role in ("LEADER", "LAGGER", "SYNC", "UNCORRELATED")

    def test_regime_from_indicators(self) -> None:
        # VOLATILE (BB width >= 5%)
        snap = build_pair_snapshot(
            "TEST",
            indicators={
                "bb_upper_last": 105.0, "bb_lower_last": 95.0,
                "bb_mid_last": 100.0, "adx_last": 30.0,
                "ema9_last": 101.0, "ema21_last": 100.0,
            },
        )
        assert snap.regime == "VOLATILE"

        # QUIET (BB width <= 1.2%)
        snap = build_pair_snapshot(
            "TEST",
            indicators={
                "bb_upper_last": 100.6, "bb_lower_last": 99.4,
                "bb_mid_last": 100.0, "adx_last": 10.0,
            },
        )
        assert snap.regime == "QUIET"

    def test_ema_trend(self) -> None:
        snap = build_pair_snapshot(
            "TEST",
            indicators={
                "ema9_last": 105.0, "ema21_last": 100.0,
                "bb_upper_last": 102.0, "bb_lower_last": 98.0,
                "bb_mid_last": 100.0, "adx_last": 30.0,
            },
        )
        assert snap.ema_trend == "BULLISH"


# ===========================================================================
# PairSignalQuality
# ===========================================================================


class TestPairSignalQuality:
    """Tests for compute_pair_signal_quality."""

    def test_insufficient_data(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _record(tracker, symbol="BTCUSDT", pnl_pct=1.0)  # Only 1 signal
        quality = compute_pair_signal_quality(tracker, "BTCUSDT")
        assert quality.quality_label == "INSUFFICIENT_DATA"

    def test_strong_quality(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        # 8 wins, 2 losses = 80% win rate
        for i in range(10):
            win = i < 8
            _record(
                tracker, symbol="BTCUSDT",
                pnl_pct=1.5 if win else -0.8,
                hit_tp=2 if win else 0,
                hit_sl=not win,
                timestamp=now - (10 - i) * 86400,
            )
        quality = compute_pair_signal_quality(tracker, "BTCUSDT")
        assert quality.hit_rate > 55.0
        assert quality.risk_reward > 1.0
        assert quality.quality_label in ("STRONG", "ACCEPTABLE")

    def test_critical_quality(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        # 1 win, 9 losses = 10% win rate → CRITICAL
        for i in range(10):
            win = i == 0
            _record(
                tracker, symbol="DOGEUSDT",
                pnl_pct=0.5 if win else -2.0,
                hit_tp=1 if win else 0,
                hit_sl=not win,
                timestamp=now - (10 - i) * 86400,
            )
        quality = compute_pair_signal_quality(tracker, "DOGEUSDT")
        assert quality.hit_rate < 35.0
        assert quality.quality_label == "CRITICAL"
        assert "low_hit_rate" in quality.weak_areas

    def test_weak_areas_detected(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        # Negative expectancy
        for i in range(10):
            _record(
                tracker, symbol="XRPUSDT",
                pnl_pct=-0.1,
                hit_tp=0, hit_sl=True,
                timestamp=now - (10 - i) * 86400,
            )
        quality = compute_pair_signal_quality(tracker, "XRPUSDT")
        assert "negative_expectancy" in quality.weak_areas


# ===========================================================================
# Recommendation engine
# ===========================================================================


class TestRecommendations:
    """Tests for generate_pair_recommendations."""

    def test_regime_recommendation(self) -> None:
        snap = PairSnapshot(symbol="ETHUSDT")
        quality = PairSignalQuality(symbol="ETHUSDT", total_signals=20, hit_rate=50.0)
        regime_stats = {
            "RANGING": {"count": 8, "win_rate": 25.0, "wins": 2, "losses": 6, "avg_pnl": -0.5},
            "TRENDING_UP": {"count": 12, "win_rate": 75.0, "wins": 9, "losses": 3, "avg_pnl": 1.5},
        }
        recs = generate_pair_recommendations(
            "ETHUSDT", snap, quality, regime_stats, {}, {},
        )
        regime_recs = [r for r in recs if r.category == "REGIME"]
        assert len(regime_recs) >= 1
        assert "RANGING" in regime_recs[0].description

    def test_session_recommendation(self) -> None:
        snap = PairSnapshot(symbol="BTCUSDT")
        quality = PairSignalQuality(symbol="BTCUSDT", total_signals=20, hit_rate=55.0)
        session_stats = {
            "ASIAN_SESSION": {"count": 8, "win_rate": 20.0, "wins": 2, "losses": 8, "avg_pnl": -1.0},
            "NY_LONDON_OVERLAP": {"count": 12, "win_rate": 80.0, "wins": 10, "losses": 2, "avg_pnl": 1.5},
        }
        recs = generate_pair_recommendations(
            "BTCUSDT", snap, quality, {}, session_stats, {},
        )
        timing_recs = [r for r in recs if r.category == "TIMING"]
        assert len(timing_recs) >= 1

    def test_btc_correlation_recommendation(self) -> None:
        snap = PairSnapshot(symbol="SOLUSDT", btc_corr_short=0.85, btc_role="LAGGER")
        quality = PairSignalQuality(symbol="SOLUSDT", total_signals=20, hit_rate=55.0)
        recs = generate_pair_recommendations(
            "SOLUSDT", snap, quality, {}, {}, {},
        )
        corr_recs = [r for r in recs if r.category == "CORRELATION"]
        assert len(corr_recs) >= 1

    def test_critical_quality_recommendation(self) -> None:
        snap = PairSnapshot(symbol="DOGEUSDT")
        quality = PairSignalQuality(
            symbol="DOGEUSDT", total_signals=10, hit_rate=20.0,
            max_drawdown=18.0, quality_label="CRITICAL",
            weak_areas=["low_hit_rate", "high_drawdown"],
        )
        recs = generate_pair_recommendations(
            "DOGEUSDT", snap, quality, {}, {}, {},
        )
        general_recs = [r for r in recs if r.category == "GENERAL"]
        assert len(general_recs) >= 1
        assert general_recs[0].priority == "HIGH"

    def test_empty_data_no_crash(self) -> None:
        snap = PairSnapshot(symbol="NOPAIR")
        quality = PairSignalQuality(symbol="NOPAIR")
        recs = generate_pair_recommendations("NOPAIR", snap, quality, {}, {}, {})
        assert isinstance(recs, list)

    def test_recommendations_sorted_by_priority(self) -> None:
        snap = PairSnapshot(symbol="TEST", btc_corr_short=0.9, btc_role="LAGGER")
        quality = PairSignalQuality(
            symbol="TEST", total_signals=20, hit_rate=20.0,
            quality_label="CRITICAL", weak_areas=["low_hit_rate"],
        )
        recs = generate_pair_recommendations(
            "TEST", snap, quality,
            {"RANGING": {"count": 10, "win_rate": 15.0, "wins": 1, "losses": 9, "avg_pnl": -2.0}},
            {}, {},
        )
        assert len(recs) > 0
        # HIGH priority should come first
        priorities = [r.priority for r in recs]
        assert priorities[0] == "HIGH"


# ===========================================================================
# Anomaly detection
# ===========================================================================


class TestAnomalyDetection:
    """Tests for detect_pair_anomalies."""

    def test_insufficient_data_no_anomalies(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _record(tracker, symbol="BTCUSDT", pnl_pct=1.0)
        snap = PairSnapshot(symbol="BTCUSDT")
        quality = PairSignalQuality(symbol="BTCUSDT", total_signals=1)

        anomalies = detect_pair_anomalies("BTCUSDT", tracker, quality, snap)
        assert anomalies == []

    def test_consecutive_failures_detected(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        for i in range(6):
            _record(
                tracker, symbol="BTCUSDT", pnl_pct=-1.0,
                hit_sl=True, hit_tp=0, timestamp=now - (6 - i) * 86400,
            )
        snap = PairSnapshot(symbol="BTCUSDT")
        quality = PairSignalQuality(symbol="BTCUSDT", total_signals=6, hit_rate=0.0)
        anomalies = detect_pair_anomalies("BTCUSDT", tracker, quality, snap)
        types = [a.anomaly_type for a in anomalies]
        assert "CONSECUTIVE_FAILURES" in types

    def test_declining_performance_detected(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        snap = PairSnapshot(symbol="BTCUSDT")
        quality = PairSignalQuality(
            symbol="BTCUSDT", total_signals=10,
            consistency_trend="DEGRADING", consistency_score=40.0,
        )
        anomalies = detect_pair_anomalies("BTCUSDT", tracker, quality, snap)
        types = [a.anomaly_type for a in anomalies]
        assert "DECLINING_PERFORMANCE" in types

    def test_excessive_drawdown_critical(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        snap = PairSnapshot(symbol="BTCUSDT")
        quality = PairSignalQuality(
            symbol="BTCUSDT", total_signals=10,
            current_drawdown=12.0, max_drawdown=18.0,
        )
        anomalies = detect_pair_anomalies("BTCUSDT", tracker, quality, snap)
        dd_anomalies = [a for a in anomalies if a.anomaly_type == "EXCESSIVE_DRAWDOWN"]
        assert len(dd_anomalies) >= 1
        assert dd_anomalies[0].severity == "CRITICAL"

    def test_btc_correlation_ignored(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        snap = PairSnapshot(symbol="SOLUSDT", btc_corr_short=0.85, btc_role="LAGGER")
        quality = PairSignalQuality(
            symbol="SOLUSDT", total_signals=10,
            quality_label="WEAK",
        )
        anomalies = detect_pair_anomalies("SOLUSDT", tracker, quality, snap)
        types = [a.anomaly_type for a in anomalies]
        assert "BTC_CORRELATION_IGNORED" in types

    def test_low_hit_rate_regime(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        # 5 losses in VOLATILE regime
        for i in range(5):
            _record(
                tracker, symbol="XRPUSDT", pnl_pct=-1.0,
                hit_sl=True, hit_tp=0,
                market_phase="VOLATILE",
                timestamp=now - (5 - i) * 86400,
            )
        # 5 wins in TRENDING_UP
        for i in range(5):
            _record(
                tracker, symbol="XRPUSDT", pnl_pct=1.0,
                hit_tp=1,
                market_phase="TRENDING_UP",
                timestamp=now - (5 - i) * 86400,
            )
        snap = PairSnapshot(symbol="XRPUSDT")
        quality = PairSignalQuality(symbol="XRPUSDT", total_signals=10, hit_rate=50.0)
        anomalies = detect_pair_anomalies("XRPUSDT", tracker, quality, snap)
        types = [a.anomaly_type for a in anomalies]
        assert "LOW_HIT_RATE_REGIME" in types

    def test_anomalies_sorted_by_severity(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        snap = PairSnapshot(symbol="BTCUSDT", btc_corr_short=0.9)
        quality = PairSignalQuality(
            symbol="BTCUSDT", total_signals=10,
            consistency_trend="DEGRADING", consistency_score=30.0,
            current_drawdown=15.0, max_drawdown=20.0,
            quality_label="CRITICAL",
        )
        anomalies = detect_pair_anomalies("BTCUSDT", tracker, quality, snap)
        if len(anomalies) >= 2:
            severities = [a.severity for a in anomalies]
            order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            for i in range(len(severities) - 1):
                assert order.get(severities[i], 4) <= order.get(severities[i + 1], 4)


# ===========================================================================
# Report generation
# ===========================================================================


class TestReportGeneration:
    """Tests for run_pair_analysis and report formatters."""

    def test_run_pair_analysis_basic(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)
        symbols = tracker.get_all_traded_symbols()

        report = run_pair_analysis(tracker, symbols, window_days=30)
        assert report.total_pairs_analyzed == len(symbols)
        assert len(report.pair_results) == len(symbols)
        assert isinstance(report.quality_distribution, dict)

    def test_report_identifies_critical_pair(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)
        symbols = tracker.get_all_traded_symbols()

        report = run_pair_analysis(tracker, symbols, window_days=30)
        # DOGEUSDT should be flagged as CRITICAL
        assert "DOGEUSDT" in report.pair_results
        assert report.pair_results["DOGEUSDT"].quality.quality_label == "CRITICAL"
        assert "DOGEUSDT" in report.pairs_to_suppress

    def test_report_estimates_bad_signal_reduction(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)
        symbols = tracker.get_all_traded_symbols()

        report = run_pair_analysis(tracker, symbols, window_days=30)
        assert report.estimated_bad_signal_reduction_pct >= 0

    def test_telegram_summary_format(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)
        symbols = tracker.get_all_traded_symbols()

        report = run_pair_analysis(tracker, symbols)
        telegram = format_telegram_summary(report)
        assert "Per-Pair Analysis Report" in telegram
        assert "Signal Quality Distribution" in telegram
        assert "Est. bad signal reduction" in telegram

    def test_detailed_report_format(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)
        symbols = tracker.get_all_traded_symbols()

        report = run_pair_analysis(tracker, symbols)
        detailed = format_detailed_report(report)
        assert "PER-PAIR ANALYSIS REPORT" in detailed
        assert "BTCUSDT" in detailed
        assert "DOGEUSDT" in detailed
        assert "IMPACT ASSESSMENT" in detailed

    def test_json_export(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)
        symbols = tracker.get_all_traded_symbols()

        report = run_pair_analysis(tracker, symbols)
        json_str = export_json(report)
        data = json.loads(json_str)
        assert "total_pairs_analyzed" in data
        assert "pair_results" in data
        assert "quality_distribution" in data
        assert "pairs_to_suppress" in data

    def test_empty_tracker_no_crash(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        report = run_pair_analysis(tracker, [])
        assert report.total_pairs_analyzed == 0
        assert report.pair_results == {}

        telegram = format_telegram_summary(report)
        assert "Per-Pair Analysis Report" in telegram

    def test_single_pair_analysis(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        now = time.time()
        for i in range(8):
            _record(
                tracker, symbol="BTCUSDT",
                pnl_pct=1.5 if i < 6 else -0.8,
                hit_tp=2 if i < 6 else 0,
                hit_sl=i >= 6,
                timestamp=now - (8 - i) * 86400,
            )

        report = run_pair_analysis(tracker, ["BTCUSDT"])
        assert report.total_pairs_analyzed == 1
        result = report.pair_results["BTCUSDT"]
        assert result.quality.total_signals == 8


# ===========================================================================
# Integration: full pipeline
# ===========================================================================


class TestIntegration:
    """End-to-end integration tests for the analysis pipeline."""

    def test_full_pipeline(self, tmp_path: Any) -> None:
        """Run the complete pipeline: tracker → analysis → report → JSON."""
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)
        symbols = tracker.get_all_traded_symbols()

        # Run analysis
        report = run_pair_analysis(tracker, symbols, window_days=30)

        # Verify structure
        assert report.total_pairs_analyzed >= 4
        assert len(report.quality_distribution) > 0

        # Verify anomalies are detected
        assert len(report.all_anomalies) > 0

        # Verify recommendations are generated
        assert len(report.top_recommendations) > 0

        # Verify impact estimation
        assert report.estimated_bad_signal_reduction_pct > 0

        # Verify all formatters work
        telegram = format_telegram_summary(report)
        assert len(telegram) > 100

        detailed = format_detailed_report(report)
        assert len(detailed) > 500

        json_str = export_json(report)
        data = json.loads(json_str)
        assert data["total_pairs_analyzed"] >= 4

    def test_pair_analysis_result_has_all_fields(self, tmp_path: Any) -> None:
        tracker = _make_tracker(tmp_path)
        _fill_tracker_with_data(tracker)

        report = run_pair_analysis(tracker, ["BTCUSDT"])
        result = report.pair_results["BTCUSDT"]

        assert hasattr(result, "snapshot")
        assert hasattr(result, "quality")
        assert hasattr(result, "regime_stats")
        assert hasattr(result, "session_stats")
        assert hasattr(result, "weekday_stats")
        assert hasattr(result, "anomalies")
        assert hasattr(result, "recommendations")
