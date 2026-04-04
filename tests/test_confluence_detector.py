"""Tests for the cross-strategy confluence detector."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from unittest.mock import patch

import pytest

from src.confluence_detector import ConfluenceDetector, ConfluenceResult


# ---------------------------------------------------------------------------
# Minimal signal stub
# ---------------------------------------------------------------------------

class _Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class _FakeSignal:
    symbol: str
    direction: _Direction
    channel: str
    confidence: float
    setup_class: str = ""
    analyst_reason: str = ""
    quality_tier: str = "B"


def _sig(
    symbol: str = "BTCUSDT",
    direction: _Direction = _Direction.LONG,
    channel: str = "360_SCALP",
    confidence: float = 70.0,
) -> _FakeSignal:
    return _FakeSignal(
        symbol=symbol, direction=direction, channel=channel, confidence=confidence
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConfluenceDetectorBasics:
    def test_single_signal_no_confluence(self):
        """One signal is below min_strategies=2 → no confluence."""
        cd = ConfluenceDetector()
        cd.record_signal(_sig(channel="360_SCALP"))
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is None

    def test_two_signals_same_direction_confluence(self):
        """Two signals same (symbol, direction) → confluence detected with +5 boost."""
        cd = ConfluenceDetector()
        cd.record_signal(_sig(channel="360_SCALP", confidence=70))
        cd.record_signal(_sig(channel="360_SCALP_FVG", confidence=75))
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is not None
        assert result.confluence_boost == 5.0
        assert result.strategy_count == 2
        assert set(result.contributing_channels) == {"360_SCALP", "360_SCALP_FVG"}
        assert result.label == "Multi-Strategy Confluence"

    def test_three_signals_boost_8(self):
        """Three strategies → +8 boost."""
        cd = ConfluenceDetector()
        for ch in ("360_SCALP", "360_SCALP_FVG", "360_SCALP_CVD"):
            cd.record_signal(_sig(channel=ch))
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is not None
        assert result.confluence_boost == 8.0
        assert result.strategy_count == 3

    def test_four_plus_signals_boost_12(self):
        """Four+ strategies → +12 boost."""
        cd = ConfluenceDetector()
        for ch in ("360_SCALP", "360_SCALP_FVG", "360_SCALP_CVD", "360_SCALP_VWAP"):
            cd.record_signal(_sig(channel=ch))
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is not None
        assert result.confluence_boost == 12.0
        assert result.strategy_count == 4

    def test_five_signals_still_boost_12(self):
        """Five strategies → still +12 boost (max)."""
        cd = ConfluenceDetector()
        for ch in ("A", "B", "C", "D", "E"):
            cd.record_signal(_sig(channel=ch))
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is not None
        assert result.confluence_boost == 12.0
        assert result.strategy_count == 5


class TestConfluenceDetectorDirections:
    def test_different_directions_no_confluence(self):
        """Signals with different directions → no confluence for either."""
        cd = ConfluenceDetector()
        cd.record_signal(_sig(channel="360_SCALP", direction=_Direction.LONG))
        cd.record_signal(_sig(channel="360_SCALP_FVG", direction=_Direction.SHORT))
        assert cd.check_confluence("BTCUSDT", "LONG") is None
        assert cd.check_confluence("BTCUSDT", "SHORT") is None

    def test_mixed_directions_partial_confluence(self):
        """Two LONG + one SHORT → confluence only for LONG."""
        cd = ConfluenceDetector()
        cd.record_signal(_sig(channel="360_SCALP", direction=_Direction.LONG))
        cd.record_signal(_sig(channel="360_SCALP_FVG", direction=_Direction.LONG))
        cd.record_signal(_sig(channel="360_SCALP_CVD", direction=_Direction.SHORT))
        long_result = cd.check_confluence("BTCUSDT", "LONG")
        short_result = cd.check_confluence("BTCUSDT", "SHORT")
        assert long_result is not None
        assert long_result.strategy_count == 2
        assert short_result is None


class TestConfluenceDetectorWindowExpiry:
    def test_expired_signals_pruned(self):
        """Signals older than window_seconds are pruned."""
        cd = ConfluenceDetector(window_seconds=1.0)
        cd.record_signal(_sig(channel="360_SCALP"))
        # Backdate the timestamp
        key = ("BTCUSDT", "LONG")
        cd._recent_signals[key][0].timestamp = time.monotonic() - 2.0
        cd.record_signal(_sig(channel="360_SCALP_FVG"))
        result = cd.check_confluence("BTCUSDT", "LONG")
        # Only 1 non-expired signal → no confluence
        assert result is None

    def test_all_expired_returns_none(self):
        """All signals expired → None and key is cleaned up."""
        cd = ConfluenceDetector(window_seconds=0.1)
        cd.record_signal(_sig(channel="360_SCALP"))
        cd.record_signal(_sig(channel="360_SCALP_FVG"))
        key = ("BTCUSDT", "LONG")
        for entry in cd._recent_signals[key]:
            entry.timestamp = time.monotonic() - 1.0
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is None
        assert key not in cd._recent_signals


class TestConfluenceDetectorFlush:
    def test_flush_clears_entries(self):
        """flush_symbol removes entries for that (symbol, direction)."""
        cd = ConfluenceDetector()
        cd.record_signal(_sig(channel="360_SCALP"))
        cd.record_signal(_sig(channel="360_SCALP_FVG"))
        cd.flush_symbol("BTCUSDT", "LONG")
        assert cd.check_confluence("BTCUSDT", "LONG") is None

    def test_flush_only_affects_target(self):
        """flush_symbol doesn't affect other (symbol, direction) pairs."""
        cd = ConfluenceDetector()
        cd.record_signal(_sig(channel="A", symbol="BTCUSDT"))
        cd.record_signal(_sig(channel="B", symbol="BTCUSDT"))
        cd.record_signal(_sig(channel="C", symbol="ETHUSDT"))
        cd.record_signal(_sig(channel="D", symbol="ETHUSDT"))
        cd.flush_symbol("BTCUSDT", "LONG")
        assert cd.check_confluence("BTCUSDT", "LONG") is None
        assert cd.check_confluence("ETHUSDT", "LONG") is not None


class TestConfluenceDetectorBestSignal:
    def test_best_signal_selected_by_highest_confidence(self):
        """The signal with the highest confidence is selected as best."""
        cd = ConfluenceDetector()
        cd.record_signal(_sig(channel="360_SCALP", confidence=60))
        cd.record_signal(_sig(channel="360_SCALP_FVG", confidence=80))
        cd.record_signal(_sig(channel="360_SCALP_CVD", confidence=70))
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is not None
        assert result.best_signal.channel == "360_SCALP_FVG"
        assert result.best_signal.confidence == 80

    def test_best_signal_preserves_original_object(self):
        """The best_signal in the result is the actual signal object."""
        sig1 = _sig(channel="A", confidence=50)
        sig2 = _sig(channel="B", confidence=90)
        cd = ConfluenceDetector()
        cd.record_signal(sig1)
        cd.record_signal(sig2)
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result.best_signal is sig2


class TestConfluenceResultDataclass:
    def test_default_label(self):
        result = ConfluenceResult(
            best_signal=None,
            contributing_channels=["A", "B"],
            confluence_boost=5.0,
            strategy_count=2,
        )
        assert result.label == "Multi-Strategy Confluence"

    def test_custom_label(self):
        result = ConfluenceResult(
            best_signal=None,
            contributing_channels=[],
            confluence_boost=0.0,
            label="Custom",
            strategy_count=0,
        )
        assert result.label == "Custom"

    def test_all_fields_accessible(self):
        sig = _sig()
        result = ConfluenceResult(
            best_signal=sig,
            contributing_channels=["X", "Y"],
            confluence_boost=5.0,
            strategy_count=2,
        )
        assert result.best_signal is sig
        assert result.contributing_channels == ["X", "Y"]
        assert result.confluence_boost == 5.0
        assert result.strategy_count == 2


class TestSetupClassEnum:
    def test_multi_strategy_confluence_exists(self):
        from src.signal_quality import SetupClass

        assert hasattr(SetupClass, "MULTI_STRATEGY_CONFLUENCE")
        assert SetupClass.MULTI_STRATEGY_CONFLUENCE.value == "MULTI_STRATEGY_CONFLUENCE"

    def test_multi_strategy_confluence_in_channel_compat(self):
        from src.signal_quality import CHANNEL_SETUP_COMPATIBILITY, SetupClass

        for channel, setup_classes in CHANNEL_SETUP_COMPATIBILITY.items():
            assert SetupClass.MULTI_STRATEGY_CONFLUENCE in setup_classes, (
                f"MULTI_STRATEGY_CONFLUENCE missing from {channel}"
            )

    def test_multi_strategy_confluence_in_regime_compat(self):
        from src.signal_quality import REGIME_SETUP_COMPATIBILITY, SetupClass, MarketState

        for state, setup_classes in REGIME_SETUP_COMPATIBILITY.items():
            if state == MarketState.VOLATILE_UNSUITABLE:
                assert SetupClass.MULTI_STRATEGY_CONFLUENCE not in setup_classes
            else:
                assert SetupClass.MULTI_STRATEGY_CONFLUENCE in setup_classes, (
                    f"MULTI_STRATEGY_CONFLUENCE missing from {state.name}"
                )


class TestConfluenceDetectorMinStrategies:
    def test_custom_min_strategies(self):
        """Confluence with min_strategies=3 requires at least 3."""
        cd = ConfluenceDetector(min_strategies=3)
        cd.record_signal(_sig(channel="A"))
        cd.record_signal(_sig(channel="B"))
        assert cd.check_confluence("BTCUSDT", "LONG") is None
        cd.record_signal(_sig(channel="C"))
        result = cd.check_confluence("BTCUSDT", "LONG")
        assert result is not None
        assert result.strategy_count == 3


class TestConfluenceDetectorEmptyLookup:
    def test_no_signals_returns_none(self):
        cd = ConfluenceDetector()
        assert cd.check_confluence("BTCUSDT", "LONG") is None

    def test_wrong_symbol_returns_none(self):
        cd = ConfluenceDetector()
        cd.record_signal(_sig(symbol="BTCUSDT"))
        cd.record_signal(_sig(symbol="BTCUSDT", channel="B"))
        assert cd.check_confluence("ETHUSDT", "LONG") is None
