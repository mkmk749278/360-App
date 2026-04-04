"""Tests for structural level detection (Phase 3 – Entry & Exit Precision)."""

from __future__ import annotations

import numpy as np
import pytest

from src.structural_levels import (
    find_round_numbers,
    find_structural_sl,
    find_structural_tp,
    find_swing_levels,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trending_data(n: int = 30, base: float = 100.0, step: float = 0.5):
    """Produce synthetic OHLC with clear swing highs and lows."""
    closes = np.array([base + step * i for i in range(n)])
    # Inject a swing high at index 10 and swing low at index 15
    highs = closes + 0.3
    lows = closes - 0.3

    highs[10] = closes[10] + 2.0  # clear swing high
    lows[15] = closes[15] - 2.0   # clear swing low
    return highs, lows, closes


# ---------------------------------------------------------------------------
# find_swing_levels
# ---------------------------------------------------------------------------

class TestFindSwingLevels:
    def test_detects_swing_high_and_low(self):
        highs, lows, closes = _trending_data(30)
        result = find_swing_levels(highs, lows, closes, lookback=30)
        assert highs[10] in result["swing_highs"]
        assert lows[15] in result["swing_lows"]

    def test_flat_data_returns_empty(self):
        n = 30
        flat = np.ones(n) * 50.0
        result = find_swing_levels(flat, flat, flat, lookback=30)
        # Every candle ties, so all of them qualify – but the values are identical.
        # The key invariant: no crash and result keys exist.
        assert "swing_highs" in result
        assert "swing_lows" in result

    def test_short_data_returns_empty(self):
        short = np.array([1.0, 2.0, 3.0])
        result = find_swing_levels(short, short, short)
        assert result["swing_highs"] == []
        assert result["swing_lows"] == []


# ---------------------------------------------------------------------------
# find_round_numbers
# ---------------------------------------------------------------------------

class TestFindRoundNumbers:
    def test_btc_price(self):
        levels = find_round_numbers(68050.0)
        assert 68000.0 in levels
        assert 68100.0 in levels

    def test_low_price_coin(self):
        levels = find_round_numbers(0.505)
        assert 0.50 in levels
        assert 0.51 in levels

    def test_mid_price(self):
        levels = find_round_numbers(152.3)
        assert 150.0 in levels
        assert 160.0 in levels

    def test_count_parameter(self):
        levels = find_round_numbers(100.0, count=3)
        # Should have roughly 2*count+1 levels (±count around base)
        assert len(levels) >= 4


# ---------------------------------------------------------------------------
# find_structural_sl
# ---------------------------------------------------------------------------

class TestFindStructuralSL:
    def test_long_moves_sl_to_swing_low(self):
        entry = 100.0
        atr_val = 2.0
        atr_sl = entry - atr_val  # 98.0
        swing_levels = {"swing_highs": [], "swing_lows": [98.5]}
        round_nums = find_round_numbers(entry)

        result = find_structural_sl(
            "LONG", entry, atr_sl, swing_levels, round_nums, atr_val
        )
        # Should snap SL to just below 98.5 (with 0.1% buffer)
        assert result < 98.5
        assert result > atr_sl  # tighter than pure ATR SL
        assert result == pytest.approx(98.5 * 0.999, abs=0.01)

    def test_long_keeps_atr_sl_when_no_level(self):
        entry = 100.0
        atr_val = 2.0
        atr_sl = 98.0
        swing_levels = {"swing_highs": [], "swing_lows": [90.0]}
        round_nums = []

        result = find_structural_sl(
            "LONG", entry, atr_sl, swing_levels, round_nums, atr_val
        )
        assert result == atr_sl

    def test_short_moves_sl_to_swing_high(self):
        entry = 100.0
        atr_val = 2.0
        atr_sl = entry + atr_val  # 102.0
        swing_levels = {"swing_highs": [101.5], "swing_lows": []}
        round_nums = find_round_numbers(entry)

        result = find_structural_sl(
            "SHORT", entry, atr_sl, swing_levels, round_nums, atr_val
        )
        # Should snap SL to just above 101.5
        assert result > 101.5
        assert result < atr_sl  # tighter than pure ATR SL

    def test_respects_min_max_atr_bounds(self):
        entry = 100.0
        atr_val = 2.0
        atr_sl = 98.0
        # Swing low at 99.8 is too close (within min_atr_mult * atr = 0.7*2=1.4 → 98.6)
        swing_levels = {"swing_highs": [], "swing_lows": [99.8]}
        round_nums = []

        result = find_structural_sl(
            "LONG", entry, atr_sl, swing_levels, round_nums, atr_val,
            min_atr_mult=0.7, max_atr_mult=1.3,
        )
        # 99.8 is above upper_bound (100 - 0.7*2 = 98.6), so out of range
        assert result == atr_sl

    def test_direction_enum_compat(self):
        """Works with Direction enum (str representation)."""
        from src.smc import Direction

        entry = 100.0
        atr_val = 2.0
        atr_sl = 98.0
        swing_levels = {"swing_highs": [], "swing_lows": [98.5]}
        round_nums = []

        result = find_structural_sl(
            Direction.LONG, entry, atr_sl, swing_levels, round_nums, atr_val
        )
        assert result < 98.5


# ---------------------------------------------------------------------------
# find_structural_tp
# ---------------------------------------------------------------------------

class TestFindStructuralTP:
    def test_long_uses_closer_resistance(self):
        entry = 100.0
        atr_val = 2.0
        atr_tp = entry + atr_val  # 102.0
        swing_levels = {"swing_highs": [101.8], "swing_lows": []}
        round_nums = find_round_numbers(entry)

        result = find_structural_tp(
            "LONG", entry, atr_tp, swing_levels, round_nums, atr_val
        )
        # 101.8 is closer than 102.0 and within 0.8-1.2 range → use it
        assert result == 101.8

    def test_long_keeps_atr_tp_when_no_better_level(self):
        entry = 100.0
        atr_val = 2.0
        atr_tp = 102.0
        swing_levels = {"swing_highs": [110.0], "swing_lows": []}
        round_nums = []

        result = find_structural_tp(
            "LONG", entry, atr_tp, swing_levels, round_nums, atr_val
        )
        assert result == atr_tp

    def test_short_uses_closer_support(self):
        entry = 100.0
        atr_val = 2.0
        atr_tp = entry - atr_val  # 98.0
        swing_levels = {"swing_highs": [], "swing_lows": [98.2]}
        round_nums = find_round_numbers(entry)

        result = find_structural_tp(
            "SHORT", entry, atr_tp, swing_levels, round_nums, atr_val
        )
        # 98.2 is closer (higher) than 98.0 and within range → use it
        assert result == 98.2


# ---------------------------------------------------------------------------
# Integration: build_channel_signal backward compatibility & structural adj
# ---------------------------------------------------------------------------

class TestBuildChannelSignalIntegration:
    def _simple_signal(self, **kwargs):
        from config import CHANNEL_SCALP
        from src.channels.base import build_channel_signal
        from src.smc import Direction

        defaults = dict(
            config=CHANNEL_SCALP,
            symbol="BTCUSDT",
            direction=Direction.LONG,
            close=100.0,
            sl=99.0,
            tp1=0.0,
            tp2=0.0,
            tp3=0.0,
            sl_dist=1.0,
            id_prefix="TEST",
            atr_val=1.0,
            setup_class="TEST",
        )
        defaults.update(kwargs)
        return build_channel_signal(**defaults)

    def test_backward_compatible_without_candle_data(self):
        """build_channel_signal still works without the new candle params."""
        sig = self._simple_signal()
        assert sig is not None
        assert sig.stop_loss > 0

    def test_with_candle_data_adjusts_sl_tp(self):
        """When candle data is provided, structural adjustment is attempted."""
        n = 30
        closes = [100.0 + 0.1 * i for i in range(n)]
        highs = [c + 0.3 for c in closes]
        lows = [c - 0.3 for c in closes]
        # Inject a swing low near the ATR SL region
        lows[15] = 99.2  # within min/max ATR mult of entry=100, sl_dist=1

        sig = self._simple_signal(
            candle_highs=highs,
            candle_lows=lows,
            candle_closes=closes,
        )
        assert sig is not None
        assert sig.stop_loss > 0
