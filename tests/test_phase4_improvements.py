"""Tests for Phase 4: Adaptive Quality Intelligence.

Covers:
1. Stat filter Wilson score + -10 pts soft penalty
2. Regime transition detector
3. MTF staleness decay
4. Kill zone soft penalty (was hard reject)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.stat_filter import (
    RollingWinRateStore,
    SignalOutcome,
    StatisticalFilter,
)
from src.regime_transition import RegimeTransitionDetector
from src.mtf import compute_mtf_confluence, compute_mtf_confluence_with_decay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fill_store(
    store: RollingWinRateStore,
    channel: str,
    pair: str,
    regime: str,
    wins: int,
    losses: int,
) -> None:
    for i in range(wins):
        store.record(SignalOutcome(
            signal_id=f"w{i}", channel=channel, pair=pair,
            regime=regime, setup_class="", won=True, pnl_pct=1.5,
        ))
    for i in range(losses):
        store.record(SignalOutcome(
            signal_id=f"l{i}", channel=channel, pair=pair,
            regime=regime, setup_class="", won=False, pnl_pct=-1.0,
        ))


# ===========================================================================
# 1. Stat filter — Wilson score + 10 pts soft penalty
# ===========================================================================


class TestStatFilterWilson:
    def test_wilson_lower_returns_conservative_bound(self):
        """Wilson lower bound must be strictly below raw win rate."""
        store = RollingWinRateStore(window=30, min_samples=15)
        _fill_store(store, "SC", "BTC", "TR", wins=12, losses=8)  # 60% raw
        raw_wr = store.win_rate("SC", "BTC", "TR")
        wilson = store.wilson_lower("SC", "BTC", "TR")
        assert raw_wr is not None
        assert wilson is not None
        assert wilson < raw_wr  # more conservative
        assert wilson > 0.0

    def test_wilson_lower_none_below_min_samples(self):
        store = RollingWinRateStore(window=30, min_samples=15)
        _fill_store(store, "SC", "BTC", "TR", wins=5, losses=5)
        assert store.wilson_lower("SC", "BTC", "TR") is None

    def test_soft_penalty_is_10_pts(self):
        """Default soft penalty must be 10 points (not the old 5)."""
        store = RollingWinRateStore(window=30, min_samples=15)
        # 43% raw WR → Wilson lower bound ~0.27 → soft penalty zone (0.25–0.45)
        _fill_store(store, "SW", "ETH", "VOL", wins=13, losses=17)
        sf = StatisticalFilter(store)
        allow, conf, reason = sf.check("SW", "ETH", "VOL", 70.0)
        assert allow is True
        assert conf == pytest.approx(60.0)  # 70 - 10
        assert "soft_penalty" in reason

    def test_wilson_used_for_threshold_comparison(self):
        """check() reason must mention 'wilson' not raw 'wr'."""
        store = RollingWinRateStore(window=30, min_samples=15)
        _fill_store(store, "SC", "BTC", "TR", wins=15, losses=5)
        sf = StatisticalFilter(store)
        _allow, _conf, reason = sf.check("SC", "BTC", "TR", 80.0)
        assert "wilson=" in reason


# ===========================================================================
# 2. Regime transition detector
# ===========================================================================


class TestRegimeTransition:
    def test_quiet_to_trending_up_boost(self):
        det = RegimeTransitionDetector(transition_window_seconds=300.0)
        det.record_regime("BTCUSDT", "QUIET")
        adj = det.get_transition_adjustment("BTCUSDT", "TRENDING_UP")
        assert adj == pytest.approx(5.0)

    def test_trending_up_to_ranging_penalty(self):
        det = RegimeTransitionDetector()
        det.record_regime("ETHUSDT", "TRENDING_UP")
        adj = det.get_transition_adjustment("ETHUSDT", "RANGING")
        assert adj == pytest.approx(-5.0)

    def test_volatile_to_quiet_penalty(self):
        det = RegimeTransitionDetector()
        det.record_regime("SOLUSDT", "VOLATILE")
        adj = det.get_transition_adjustment("SOLUSDT", "QUIET")
        assert adj == pytest.approx(-3.0)

    def test_same_regime_returns_zero(self):
        det = RegimeTransitionDetector()
        det.record_regime("BTCUSDT", "TRENDING_UP")
        adj = det.get_transition_adjustment("BTCUSDT", "TRENDING_UP")
        assert adj == 0.0

    def test_outside_window_returns_zero(self):
        det = RegimeTransitionDetector(transition_window_seconds=0.01)
        det.record_regime("BTCUSDT", "QUIET")
        time.sleep(0.02)  # exceed the tiny window
        adj = det.get_transition_adjustment("BTCUSDT", "TRENDING_UP")
        assert adj == 0.0

    def test_get_last_transition_returns_dict(self):
        det = RegimeTransitionDetector()
        det.record_regime("BTCUSDT", "QUIET")
        det.record_regime("BTCUSDT", "TRENDING_UP")
        info = det.get_last_transition("BTCUSDT")
        assert info is not None
        assert info["from_regime"] == "QUIET"
        assert info["to_regime"] == "TRENDING_UP"
        assert "seconds_ago" in info

    def test_get_last_transition_none_unknown_symbol(self):
        det = RegimeTransitionDetector()
        assert det.get_last_transition("UNKNOWN") is None

    def test_get_last_transition_none_no_transition(self):
        """Only one regime recorded — no transition yet."""
        det = RegimeTransitionDetector()
        det.record_regime("BTCUSDT", "QUIET")
        assert det.get_last_transition("BTCUSDT") is None

    def test_ranging_to_trending_down_boost(self):
        det = RegimeTransitionDetector()
        det.record_regime("XRPUSDT", "RANGING")
        adj = det.get_transition_adjustment("XRPUSDT", "TRENDING_DOWN")
        assert adj == pytest.approx(3.0)

    def test_trending_down_to_volatile(self):
        det = RegimeTransitionDetector()
        det.record_regime("ADAUSDT", "TRENDING_DOWN")
        adj = det.get_transition_adjustment("ADAUSDT", "VOLATILE")
        assert adj == pytest.approx(-3.0)


# ===========================================================================
# 3. MTF staleness decay
# ===========================================================================


class TestMTFStalenessDecay:
    _TFS_BULLISH = {
        "1m":  {"ema_fast": 101.0, "ema_slow": 100.0, "close": 101.5},
        "5m":  {"ema_fast": 102.0, "ema_slow": 101.0, "close": 102.5},
        "15m": {"ema_fast": 103.0, "ema_slow": 101.5, "close": 103.5},
        "4h":  {"ema_fast": 105.0, "ema_slow": 103.0, "close": 106.0},
    }

    def test_fresh_candles_full_weight(self):
        """Age 0 → decay=1.0 → identical to no-decay."""
        ages = {"1m": 0.0, "5m": 0.0, "15m": 0.0, "4h": 0.0}
        result_decay = compute_mtf_confluence_with_decay("LONG", self._TFS_BULLISH, candle_ages_hours=ages)
        result_orig = compute_mtf_confluence("LONG", self._TFS_BULLISH)
        assert result_decay.score == pytest.approx(result_orig.score)

    def test_4h_candle_3h_old_decay(self):
        """4h candle 3h old: decay = max(0.3, 1 - 3/8) = 0.625."""
        ages = {"1m": 0.0, "5m": 0.0, "15m": 0.0, "4h": 3.0}
        result = compute_mtf_confluence_with_decay("LONG", self._TFS_BULLISH, candle_ages_hours=ages)
        # 4h weight = 3.0 * 0.625 = 1.875 instead of 3.0
        # Score still 1.0 because all bullish, but total weight is lower
        assert result.score == pytest.approx(1.0)
        assert result.is_aligned is True

    def test_very_old_candle_clamped_at_30pct(self):
        """A very stale candle should be clamped at 30% weight minimum."""
        ages = {"1m": 0.0, "5m": 0.0, "15m": 0.0, "4h": 100.0}
        result = compute_mtf_confluence_with_decay("LONG", self._TFS_BULLISH, candle_ages_hours=ages)
        # 4h weight = 3.0 * 0.3 = 0.9 (clamped)
        assert result.score == pytest.approx(1.0)  # still all bullish
        assert result.is_aligned is True

    def test_without_candle_ages_identical_to_original(self):
        """When candle_ages_hours is None, result must be identical."""
        result_decay = compute_mtf_confluence_with_decay("LONG", self._TFS_BULLISH)
        result_orig = compute_mtf_confluence("LONG", self._TFS_BULLISH)
        assert result_decay.score == pytest.approx(result_orig.score)
        assert result_decay.aligned_count == pytest.approx(result_orig.aligned_count)
        assert result_decay.total_count == result_orig.total_count

    def test_decay_improves_score_discrimination(self):
        """Stale candles should reduce total weight, changing alignment math for mixed signals."""
        mixed_tfs = {
            "5m":  {"ema_fast": 101.0, "ema_slow": 100.0, "close": 101.5},  # BULLISH
            "4h":  {"ema_fast": 99.0, "ema_slow": 101.0, "close": 98.0},    # BEARISH
        }
        # With fresh candles: BEARISH 4h has weight 3.0
        result_fresh = compute_mtf_confluence_with_decay(
            "LONG", mixed_tfs, candle_ages_hours={"5m": 0.0, "4h": 0.0},
        )
        # With stale 4h: BEARISH 4h has reduced weight (3.0 * 0.3 = 0.9)
        result_stale = compute_mtf_confluence_with_decay(
            "LONG", mixed_tfs, candle_ages_hours={"5m": 0.0, "4h": 100.0},
        )
        # Stale bearish 4h should give higher score than fresh bearish 4h
        assert result_stale.score > result_fresh.score


# ===========================================================================
# 4. Kill zone softening
# ===========================================================================


class TestKillZoneSoftening:
    """Test that ALTCOIN tier outside kill zone gets a soft penalty, not hard reject."""

    def _make_signal(self, confidence: float = 75.0, note: str = "") -> SimpleNamespace:
        return SimpleNamespace(confidence=confidence, execution_note=note)

    def _make_channel(self):
        """Return a minimal ScalpChannel-like object with kill zone methods."""
        from src.channels.scalp import ScalpChannel
        return ScalpChannel()

    def test_altcoin_outside_kill_zone_not_rejected(self):
        """Signal must NOT be None (was hard-rejected before)."""
        ch = self._make_channel()
        sig = self._make_signal(confidence=75.0)
        profile = SimpleNamespace(kill_zone_hard_gate=True)
        # 3 AM UTC — outside all kill zones
        now = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
        result = ch._apply_kill_zone_note(sig, profile=profile, now=now)
        assert result is not None

    def test_altcoin_outside_kill_zone_confidence_reduced(self):
        """Confidence must be reduced by 8 pts."""
        ch = self._make_channel()
        sig = self._make_signal(confidence=75.0)
        profile = SimpleNamespace(kill_zone_hard_gate=True)
        now = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
        result = ch._apply_kill_zone_note(sig, profile=profile, now=now)
        assert result.confidence == pytest.approx(67.0)
        assert "Kill zone penalty" in result.execution_note
        assert "-8 pts" in result.execution_note

    def test_inside_kill_zone_no_penalty(self):
        """During London session — no penalty applied."""
        ch = self._make_channel()
        sig = self._make_signal(confidence=75.0)
        profile = SimpleNamespace(kill_zone_hard_gate=True)
        now = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)  # London session
        result = ch._apply_kill_zone_note(sig, profile=profile, now=now)
        assert result is not None
        assert result.confidence == pytest.approx(75.0)

    def test_non_altcoin_outside_kill_zone_note_added(self):
        """Non-ALTCOIN tier outside kill zone: note added, no confidence reduction."""
        ch = self._make_channel()
        sig = self._make_signal(confidence=75.0)
        now = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
        result = ch._apply_kill_zone_note(sig, profile=None, now=now)
        assert result is not None
        assert result.confidence == pytest.approx(75.0)
        assert "Outside kill zone" in result.execution_note
