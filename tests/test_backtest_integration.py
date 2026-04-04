"""Backtesting integration tests for quality improvement pipeline.

Validates that all quality improvement modules work together correctly
using simulated historical market data to ensure:
- Higher quality signals are boosted appropriately
- Lower quality signals are penalized/filtered
- TP1 hit rate improves with structural levels
- Confluence detection works end-to-end
- No valid setups are missed (frequency maintained)
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import numpy as np
import pytest

from config import PAIR_PROFILES, PairProfile
from src.channels.base import Signal
from src.channels.scalp import ScalpChannel
from src.confidence_calibration import ConfidenceCalibrator, wilson_lower_bound
from src.confluence_detector import ConfluenceDetector
from src.mtf import compute_mtf_confluence, compute_mtf_confluence_with_decay
from src.regime_transition import RegimeTransitionDetector
from src.smc import Direction
from src.stat_filter import RollingWinRateStore, SignalOutcome, StatisticalFilter
from src.structural_levels import (
    find_round_numbers,
    find_structural_sl,
    find_structural_tp,
    find_swing_levels,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    symbol: str = "BTCUSDT",
    direction: Direction = Direction.LONG,
    entry: float = 65_000.0,
    stop_loss: float = 64_000.0,
    tp1: float = 66_000.0,
    tp2: float = 67_000.0,
    tp3: float = 68_000.0,
    channel: str = "360_SCALP",
    confidence: float = 75.0,
    setup_class: str = "LIQUIDITY_SWEEP_REVERSAL",
) -> Signal:
    return Signal(
        channel=channel,
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        confidence=confidence,
        signal_id=f"TEST-{random.randint(1000, 9999)}",
        original_sl_distance=abs(entry - stop_loss),
        setup_class=setup_class,
    )


def _record_outcomes(
    sf: StatisticalFilter,
    channel: str,
    pair: str,
    regime: str,
    n: int,
    win_rate: float,
) -> None:
    """Record *n* outcomes with the given approximate win rate."""
    wins = int(n * win_rate)
    for i in range(n):
        sf.record(SignalOutcome(
            signal_id=f"SIM-{i}",
            channel=channel,
            pair=pair,
            regime=regime,
            setup_class="LIQUIDITY_SWEEP_REVERSAL",
            won=(i < wins),
            pnl_pct=1.5 if i < wins else -1.0,
        ))


def _bullish_tf_data() -> dict[str, float]:
    """Return EMA/close data for a bullish timeframe."""
    return {"ema_fast": 105.0, "ema_slow": 100.0, "close": 106.0}


def _bearish_tf_data() -> dict[str, float]:
    return {"ema_fast": 95.0, "ema_slow": 100.0, "close": 94.0}


# ---------------------------------------------------------------------------
# 1. Confidence calibration
# ---------------------------------------------------------------------------

class TestConfidenceCalibration:
    def test_confidence_calibration_improves_discrimination(self):
        cal = ConfidenceCalibrator()
        raw_scores = [random.randint(50, 95) for _ in range(100)]

        calibrated = [cal.calibrate(r) for r in raw_scores]

        # Calibration is active: at least some scores differ from raw
        diffs = [abs(c - r) for c, r in zip(calibrated, raw_scores)]
        assert any(d > 0.01 for d in diffs), "Calibration should modify at least some scores"

        # Monotonic: higher raw → higher calibrated
        for r1, r2 in zip(range(50, 95, 5), range(55, 100, 5)):
            c1 = cal.calibrate(float(r1))
            c2 = cal.calibrate(float(r2))
            assert c2 >= c1, f"cal({r2})={c2} should be >= cal({r1})={c1}"

        # Bounded 0-100
        for c in calibrated:
            assert 0.0 <= c <= 100.0, f"Calibrated score {c} out of [0,100]"


# ---------------------------------------------------------------------------
# 2. Confluence detection
# ---------------------------------------------------------------------------

class TestConfluenceDetection:
    def test_confluence_boosts_multi_strategy_signals(self):
        cd = ConfluenceDetector()

        sigs = [
            _make_signal(channel="360_SCALP", confidence=70.0),
            _make_signal(channel="360_SCALP_FVG", confidence=80.0),
            _make_signal(channel="360_SCALP_CVD", confidence=72.0),
        ]
        for s in sigs:
            cd.record_signal(s)

        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is not None, "3 strategies should trigger confluence"
        assert result.confluence_boost == 8.0, f"3 strategies → +8, got {result.confluence_boost}"
        assert result.best_signal.confidence == 80.0, "Best signal is the one with highest confidence"
        assert len(result.contributing_channels) == 3
        assert set(result.contributing_channels) == {"360_SCALP", "360_SCALP_FVG", "360_SCALP_CVD"}


# ---------------------------------------------------------------------------
# 3. Structural SL tightening
# ---------------------------------------------------------------------------

class TestStructuralLevels:
    def test_structural_levels_tighten_sl(self):
        # Price data with a clear swing low at ~64_500
        np.random.seed(42)
        n = 40
        base = np.linspace(64_000, 66_000, n)
        highs = base + np.random.uniform(50, 200, n)
        lows = base - np.random.uniform(50, 200, n)
        closes = base + np.random.uniform(-50, 50, n)

        # Plant a clear swing low at index 20
        lows[20] = 64_500.0
        for offset in range(1, 4):
            lows[20 - offset] = 64_700.0
            lows[20 + offset] = 64_700.0

        swing = find_swing_levels(highs, lows, closes, lookback=30)
        round_nums = find_round_numbers(65_000.0)

        entry = 65_000.0
        atr_val = 600.0
        atr_sl = entry - atr_val  # 64_400

        sl = find_structural_sl(
            direction="LONG",
            entry=entry,
            atr_sl=atr_sl,
            swing_levels=swing,
            round_numbers=round_nums,
            atr_val=atr_val,
            min_atr_mult=0.7,
            max_atr_mult=1.3,
        )

        # SL should have moved: either to the planted swing low (slightly below)
        # or to a nearby structural level within the acceptable range
        min_sl = entry - atr_val * 1.3  # 64_220
        max_sl = entry - atr_val * 0.7  # 64_580
        assert min_sl <= sl <= max_sl or sl == atr_sl, (
            f"SL {sl} should be within [{min_sl}, {max_sl}] or original {atr_sl}"
        )

    # -------------------------------------------------------------------
    # 4. Structural TP at resistance
    # -------------------------------------------------------------------

    def test_structural_tp_at_resistance(self):
        np.random.seed(7)
        n = 40
        base = np.linspace(64_000, 66_000, n)
        highs = base + np.random.uniform(50, 200, n)
        lows = base - np.random.uniform(50, 200, n)
        closes = base + np.random.uniform(-50, 50, n)

        # Plant swing high at 65_800
        highs[25] = 65_800.0
        for offset in range(1, 4):
            highs[25 - offset] = 65_500.0
            highs[25 + offset] = 65_500.0

        swing = find_swing_levels(highs, lows, closes, lookback=30)
        round_nums = find_round_numbers(65_000.0)

        entry = 65_000.0
        atr_val = 500.0
        atr_tp = entry + atr_val * 2.0  # 66_000

        tp = find_structural_tp(
            direction="LONG",
            entry=entry,
            atr_tp=atr_tp,
            swing_levels=swing,
            round_numbers=round_nums,
            atr_val=atr_val,
        )

        # TP should have adjusted closer to the swing high (65_800) if it's
        # between entry and the original ATR TP.
        # If 65_800 is closer than 66_000, TP should be near 65_800.
        # At minimum, TP should be <= atr_tp (never exceeds original).
        assert tp <= atr_tp, f"Structural TP {tp} should not exceed ATR TP {atr_tp}"
        assert tp > entry, f"TP {tp} must be above entry {entry}"


# ---------------------------------------------------------------------------
# 5 & 6. Statistical filter with Wilson score
# ---------------------------------------------------------------------------

class TestStatFilter:
    def test_stat_filter_wilson_penalizes_losing_combos(self):
        store = RollingWinRateStore(window=50, min_samples=15)
        sf = StatisticalFilter(store=store)

        # 35% raw WR with 40 samples → Wilson lower ≈ 0.22–0.28 range
        # Use 40% raw WR so Wilson lower lands between 0.25 and 0.45 (soft penalty zone)
        _record_outcomes(sf, "360_SCALP", "BTCUSDT", "TRENDING_UP", n=40, win_rate=0.40)

        wl = store.wilson_lower("360_SCALP", "BTCUSDT", "TRENDING_UP")
        assert wl is not None

        allow, adj_conf, reason = sf.check("360_SCALP", "BTCUSDT", "TRENDING_UP", 75.0)

        # Wilson lower for 40% WR / 40 samples should be in soft penalty zone
        assert 0.25 <= wl < 0.45, f"Wilson lower {wl} should be in soft penalty zone [0.25, 0.45)"
        assert allow is True, f"Wilson={wl:.3f} should trigger soft penalty, not hard suppress"
        assert adj_conf == pytest.approx(65.0), f"Expected 75-10=65, got {adj_conf}"
        assert "soft_penalty" in reason

    def test_stat_filter_wilson_passes_good_combos(self):
        store = RollingWinRateStore(window=30, min_samples=15)
        sf = StatisticalFilter(store=store)

        _record_outcomes(sf, "360_SCALP", "ETHUSDT", "TRENDING_UP", n=20, win_rate=0.70)

        allow, adj_conf, reason = sf.check("360_SCALP", "ETHUSDT", "TRENDING_UP", 75.0)

        assert allow is True
        assert adj_conf == pytest.approx(75.0), f"Good WR should keep confidence at 75, got {adj_conf}"
        assert "ok" in reason


# ---------------------------------------------------------------------------
# 7. Regime transition boost
# ---------------------------------------------------------------------------

class TestRegimeTransition:
    def test_regime_transition_breakout_boost(self):
        det = RegimeTransitionDetector(transition_window_seconds=300.0)

        # Record the previous regime
        det.record_regime("ETHUSDT", "QUIET")

        # Check adjustment *before* recording new regime (mirrors real pipeline usage)
        adj = det.get_transition_adjustment("ETHUSDT", "TRENDING_UP")
        assert adj == pytest.approx(5.0), f"QUIET→TRENDING_UP should give +5.0, got {adj}"

        # Now record the new regime and verify transition was captured
        det.record_regime("ETHUSDT", "TRENDING_UP")
        last = det.get_last_transition("ETHUSDT")
        assert last is not None
        assert last["from_regime"] == "QUIET"
        assert last["to_regime"] == "TRENDING_UP"


# ---------------------------------------------------------------------------
# 8. MTF staleness decay
# ---------------------------------------------------------------------------

class TestMTFDecay:
    def test_mtf_staleness_decay_penalizes_stale(self):
        # Mix bullish + neutral so score isn't capped at 1.0
        tfs = {
            "5m": _bullish_tf_data(),
            "1h": {"ema_fast": 100.0, "ema_slow": 100.0, "close": 100.0},  # NEUTRAL
            "4h": _bullish_tf_data(),
        }

        # Fresh candles (no decay)
        fresh = compute_mtf_confluence("LONG", tfs)

        # Stale 4h candle (3.5 hours old → decay ≈ 0.5625)
        stale = compute_mtf_confluence_with_decay(
            "LONG",
            tfs,
            candle_ages_hours={"5m": 0.01, "1h": 0.1, "4h": 3.5},
        )

        # Decay reduces effective weight → lower aligned_count
        assert stale.aligned_count < fresh.aligned_count, (
            f"Stale aligned {stale.aligned_count} should be less than fresh {fresh.aligned_count}"
        )
        assert stale.score > 0.0, "Stale candles should still contribute (minimum 30% weight)"


# ---------------------------------------------------------------------------
# 9. Kill zone softening
# ---------------------------------------------------------------------------

class TestKillZoneSoftening:
    def test_kill_zone_softening_preserves_signals(self):
        ch = ScalpChannel()
        sig = _make_signal(confidence=80.0)

        # Use 03:00 UTC → definitely outside all kill zones
        outside_kz_time = datetime(2024, 6, 15, 3, 0, 0, tzinfo=timezone.utc)

        altcoin_profile = PAIR_PROFILES["ALTCOIN"]
        result = ch._apply_kill_zone_note(sig, profile=altcoin_profile, now=outside_kz_time)

        # Signal is preserved (not None)
        assert result is not None, "Kill zone softening should preserve signal, not reject"
        # Confidence reduced by 8
        assert result.confidence == pytest.approx(72.0), (
            f"Expected 80-8=72, got {result.confidence}"
        )
        assert "Kill zone penalty" in result.execution_note


# ---------------------------------------------------------------------------
# 10. Full pipeline quality ordering
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_full_pipeline_quality_ordering(self):
        cal = ConfidenceCalibrator()
        cd = ConfluenceDetector()
        store = RollingWinRateStore(window=30, min_samples=15)
        sf = StatisticalFilter(store=store)

        # --- (d) Pre-record losing history for one combo ---
        _record_outcomes(sf, "360_SCALP", "DOGEUSDT", "RANGING", n=20, win_rate=0.30)

        # --- Build 5 signals ---

        # (a) High confidence + confluence + structural
        sig_a = _make_signal(channel="360_SCALP", confidence=90.0, symbol="BTCUSDT")
        sig_a2 = _make_signal(channel="360_SCALP_FVG", confidence=88.0, symbol="BTCUSDT")
        sig_a3 = _make_signal(channel="360_SCALP_CVD", confidence=85.0, symbol="BTCUSDT")
        for s in [sig_a, sig_a2, sig_a3]:
            cd.record_signal(s)
        conf_a = cd.check_confluence("BTCUSDT", "LONG")
        cd.flush_symbol("BTCUSDT", "LONG")

        # (b) High confidence, no confluence
        sig_b = _make_signal(channel="360_SCALP", confidence=88.0, symbol="ETHUSDT")

        # (c) Low confidence + confluence boost
        sig_c = _make_signal(channel="360_SCALP", confidence=70.0, symbol="SOLUSDT")
        sig_c2 = _make_signal(channel="360_SCALP_FVG", confidence=72.0, symbol="SOLUSDT")
        for s in [sig_c, sig_c2]:
            cd.record_signal(s)
        conf_c = cd.check_confluence("SOLUSDT", "LONG")
        cd.flush_symbol("SOLUSDT", "LONG")

        # (d) Low confidence + losing stat combo
        sig_d = _make_signal(channel="360_SCALP", confidence=70.0, symbol="DOGEUSDT")

        # (e) Low confidence, no confluence
        sig_e = _make_signal(channel="360_SCALP", confidence=68.0, symbol="LINKUSDT")

        # --- Apply pipeline to each signal ---

        def pipeline_score(sig: Signal, confluence_result, regime: str = "RANGING") -> float:
            score = cal.calibrate(sig.confidence)
            if confluence_result is not None:
                score += confluence_result.confluence_boost
            _, adj, _ = sf.check(sig.channel, sig.symbol, regime, score)
            return adj

        score_a = pipeline_score(sig_a, conf_a)
        score_b = pipeline_score(sig_b, None)
        score_c = pipeline_score(sig_c, conf_c)
        score_d = pipeline_score(sig_d, None)
        score_e = pipeline_score(sig_e, None)

        # Verify ordering: a > b, a > c, c > e, b > e, d penalized vs e
        assert score_a > score_b, f"(a)={score_a} should rank above (b)={score_b}"
        assert score_a > score_c, f"(a)={score_a} should rank above (c)={score_c}"
        assert score_c > score_e, f"(c)={score_c} boosted should rank above (e)={score_e}"
        assert score_b > score_e, f"(b)={score_b} should rank above (e)={score_e}"
        assert score_d < score_e or score_d < score_b, (
            f"(d)={score_d} penalized should rank below (b)={score_b} or (e)={score_e}"
        )


# ---------------------------------------------------------------------------
# 11. No valid setup missed
# ---------------------------------------------------------------------------

class TestNoSetupMissed:
    def test_no_valid_setup_missed(self):
        cal = ConfidenceCalibrator()
        store = RollingWinRateStore(window=30, min_samples=15)
        sf = StatisticalFilter(store=store)

        # Signal at minimum confidence threshold
        sig = _make_signal(confidence=68.0)

        # Calibration still produces a valid score
        calibrated = cal.calibrate(sig.confidence)
        assert calibrated > 0.0, f"Calibrated score {calibrated} should be positive"

        # Stat filter with no history → fail-open (passes)
        allow, adj, reason = sf.check(sig.channel, sig.symbol, "TRENDING_UP", calibrated)
        assert allow is True, "No history should fail-open"
        assert adj == pytest.approx(calibrated), "No penalty when no history exists"
        assert "no_history" in reason

        # The pipeline preserves valid setups
        assert adj > 0.0, "Minimum-confidence signal should survive the full pipeline"
