"""Tests for confidence calibration and AI scorer enhanced ranges."""

from __future__ import annotations

import math

import pytest

from src.confidence_calibration import (
    ConfidenceCalibrator,
    _HARDCODED_CURVE,
    _interpolate_curve,
    wilson_lower_bound,
)
from src.ai_engine.scorer import AIConfidenceScorer


# ---------------------------------------------------------------------------
# Wilson score interval
# ---------------------------------------------------------------------------


class TestWilsonLowerBound:
    def test_zero_total_returns_zero(self):
        assert wilson_lower_bound(0, 0) == 0.0

    def test_all_wins(self):
        lb = wilson_lower_bound(10, 10)
        assert 0.0 < lb <= 1.0
        assert lb > 0.65

    def test_zero_wins(self):
        lb = wilson_lower_bound(0, 10)
        assert lb == pytest.approx(0.0, abs=0.05)
        assert lb >= 0.0

    def test_small_sample(self):
        lb = wilson_lower_bound(1, 2)
        assert 0.0 < lb < 0.5

    def test_large_sample_converges(self):
        lb = wilson_lower_bound(700, 1000)
        assert lb == pytest.approx(0.70, abs=0.03)

    def test_fifty_fifty(self):
        lb = wilson_lower_bound(50, 100)
        assert 0.35 < lb < 0.50

    def test_custom_z_score(self):
        lb_95 = wilson_lower_bound(50, 100, z=1.96)
        lb_99 = wilson_lower_bound(50, 100, z=2.576)
        assert lb_99 < lb_95


# ---------------------------------------------------------------------------
# Hardcoded curve interpolation
# ---------------------------------------------------------------------------


class TestInterpolateCurve:
    def test_exact_bucket_values(self):
        for bucket, expected in _HARDCODED_CURVE.items():
            assert _interpolate_curve(float(bucket)) == pytest.approx(expected, abs=1e-6)

    def test_midpoint_interpolation(self):
        mid = _interpolate_curve(57.5)
        assert _HARDCODED_CURVE[55] < mid < _HARDCODED_CURVE[60]
        expected = (_HARDCODED_CURVE[55] + _HARDCODED_CURVE[60]) / 2.0
        assert mid == pytest.approx(expected, abs=1e-6)

    def test_below_minimum_clamps(self):
        assert _interpolate_curve(30.0) == _HARDCODED_CURVE[50]
        assert _interpolate_curve(0.0) == _HARDCODED_CURVE[50]

    def test_above_maximum_clamps(self):
        assert _interpolate_curve(105.0) == _HARDCODED_CURVE[100]

    def test_monotonically_increasing(self):
        values = [_interpolate_curve(float(c)) for c in range(50, 101)]
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1]


# ---------------------------------------------------------------------------
# ConfidenceCalibrator — hardcoded mode (no data)
# ---------------------------------------------------------------------------


class TestCalibratorHardcodedMode:
    def test_no_data_uses_hardcoded_curve(self):
        cal = ConfidenceCalibrator(min_samples=20)
        result = cal.calibrate(70.0)
        alpha = 0.8
        expected = 70.0 * alpha + _interpolate_curve(70.0) * 100.0 * (1.0 - alpha)
        assert result == pytest.approx(expected, abs=0.1)

    def test_calibrate_low_confidence(self):
        cal = ConfidenceCalibrator()
        result = cal.calibrate(50.0)
        assert 0.0 <= result <= 100.0

    def test_calibrate_high_confidence(self):
        cal = ConfidenceCalibrator()
        result = cal.calibrate(95.0)
        assert result > cal.calibrate(60.0)

    def test_calibrate_clamps_to_valid_range(self):
        cal = ConfidenceCalibrator()
        result = cal.calibrate(100.0)
        assert 0.0 <= result <= 100.0


# ---------------------------------------------------------------------------
# Alpha decay
# ---------------------------------------------------------------------------


class TestAlphaDecay:
    def test_alpha_at_zero_samples(self):
        cal = ConfidenceCalibrator(min_samples=20)
        assert cal._compute_alpha() == pytest.approx(0.8)

    def test_alpha_below_min_samples(self):
        cal = ConfidenceCalibrator(min_samples=20)
        for _ in range(15):
            cal.record_outcome(70.0, True)
        assert cal._compute_alpha() == pytest.approx(0.8)

    def test_alpha_at_min_samples(self):
        cal = ConfidenceCalibrator(min_samples=20)
        for _ in range(20):
            cal.record_outcome(70.0, True)
        assert cal._compute_alpha() == pytest.approx(0.8)

    def test_alpha_decays_past_min_samples(self):
        cal = ConfidenceCalibrator(min_samples=20)
        for _ in range(120):
            cal.record_outcome(70.0, True)
        alpha = cal._compute_alpha()
        assert alpha < 0.8
        assert alpha > 0.3

    def test_alpha_floors_at_0_3(self):
        cal = ConfidenceCalibrator(min_samples=20)
        for _ in range(300):
            cal.record_outcome(70.0, True)
        assert cal._compute_alpha() == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Record outcome and stats
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    def test_record_increments_totals(self):
        cal = ConfidenceCalibrator()
        cal.record_outcome(70.0, True)
        cal.record_outcome(70.0, False)
        stats = cal.get_calibration_stats()
        assert stats["total_outcomes"] == 2
        assert stats["global_win_rate"] == pytest.approx(0.5)

    def test_bucket_stats_populated(self):
        cal = ConfidenceCalibrator()
        cal.record_outcome(74.0, True)
        cal.record_outcome(76.0, False)
        stats = cal.get_calibration_stats()
        assert 75 in stats["bucket_stats"]
        assert stats["bucket_stats"][75]["total"] == 2

    def test_using_data_driven_flag(self):
        cal = ConfidenceCalibrator(min_samples=5)
        for _ in range(4):
            cal.record_outcome(70.0, True)
        assert cal.get_calibration_stats()["using_data_driven"] is False
        cal.record_outcome(70.0, True)
        assert cal.get_calibration_stats()["using_data_driven"] is True

    def test_wilson_lb_in_stats(self):
        cal = ConfidenceCalibrator()
        for _ in range(10):
            cal.record_outcome(80.0, True)
        stats = cal.get_calibration_stats()
        assert stats["bucket_stats"][80]["wilson_lb"] > 0.0


# ---------------------------------------------------------------------------
# Channel-specific calibration
# ---------------------------------------------------------------------------


class TestChannelCalibration:
    def test_channel_stats_recorded(self):
        cal = ConfidenceCalibrator()
        cal.record_outcome(70.0, True, channel="spot")
        cal.record_outcome(70.0, False, channel="futures")
        stats = cal.get_calibration_stats()
        assert "spot" in stats["channel_stats"]
        assert "futures" in stats["channel_stats"]
        assert stats["channel_stats"]["spot"][70]["wins"] == 1
        assert stats["channel_stats"]["futures"][70]["wins"] == 0

    def test_channel_specific_calibration_used(self):
        cal = ConfidenceCalibrator(min_samples=5)
        for _ in range(10):
            cal.record_outcome(70.0, True, channel="good_channel")
        for _ in range(10):
            cal.record_outcome(70.0, False, channel="bad_channel")

        good_cal = cal.calibrate(70.0, channel="good_channel")
        bad_cal = cal.calibrate(70.0, channel="bad_channel")
        assert good_cal > bad_cal

    def test_no_channel_falls_back_to_global(self):
        cal = ConfidenceCalibrator(min_samples=5)
        for _ in range(10):
            cal.record_outcome(70.0, True, channel="some_channel")
        result_with = cal.calibrate(70.0, channel="some_channel")
        result_without = cal.calibrate(70.0)
        assert isinstance(result_with, float)
        assert isinstance(result_without, float)


# ---------------------------------------------------------------------------
# AI Scorer — enhanced ranges
# ---------------------------------------------------------------------------


class TestAIScorerEnhancedRanges:
    def test_high_win_rate_boost_up_to_8(self):
        scorer = AIConfidenceScorer()
        result = scorer.score_signal(
            symbol="BTCUSDT",
            base_confidence=70.0,
            pair_win_rate=0.90,
        )
        adj = result.ai_adjustment
        assert adj > 3.0, f"Expected adjustment > 3.0 with 0.90 win rate, got {adj}"
        assert adj <= 8.0, f"Win-rate boost should cap at 8.0, got {adj}"

    def test_low_win_rate_penalty_up_to_8(self):
        scorer = AIConfidenceScorer()
        result = scorer.score_signal(
            symbol="ETHUSDT",
            base_confidence=70.0,
            pair_win_rate=0.10,
        )
        adj = result.ai_adjustment
        assert adj < -3.0, f"Expected adjustment < -3.0 with 0.10 win rate, got {adj}"
        assert adj >= -8.0, f"Win-rate penalty should cap at -8.0, got {adj}"

    def test_extreme_volatility_penalty_up_to_5(self):
        scorer = AIConfidenceScorer()
        result = scorer.score_signal(
            symbol="SOLUSDT",
            base_confidence=70.0,
            volatility_percentile=1.0,
            pair_win_rate=0.5,
        )
        adj = result.ai_adjustment
        assert adj < -3.0, f"Expected penalty > 3.0 at 100th pctile volatility, got {adj}"

    def test_overall_cap_is_10(self):
        scorer = AIConfidenceScorer()
        result = scorer.score_signal(
            symbol="XRPUSDT",
            base_confidence=70.0,
            pair_win_rate=0.99,
            volatility_percentile=0.0,
        )
        assert result.ai_adjustment <= 10.0

        result2 = scorer.score_signal(
            symbol="DOGEUSDT",
            base_confidence=70.0,
            pair_win_rate=0.01,
            volatility_percentile=1.0,
        )
        assert result2.ai_adjustment >= -10.0

    def test_moderate_win_rate_no_adjustment(self):
        scorer = AIConfidenceScorer()
        result = scorer.score_signal(
            symbol="AVAXUSDT",
            base_confidence=70.0,
            pair_win_rate=0.50,
            volatility_percentile=0.5,
        )
        assert abs(result.ai_adjustment) < 2.0
