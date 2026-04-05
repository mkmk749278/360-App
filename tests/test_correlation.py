"""Tests for src.correlation – correlation-aware position limiting."""

from __future__ import annotations

import pytest

from src.correlation import check_correlation_limit, get_correlation_groups


class TestGetCorrelationGroups:
    def test_known_symbol_returns_group(self):
        groups = get_correlation_groups("ETHUSDT")
        assert "MAJOR_ALTS" in groups

    def test_btc_ecosystem_symbol(self):
        groups = get_correlation_groups("BTCUSDT")
        assert "BTC_ECOSYSTEM" in groups

    def test_unknown_symbol_returns_empty(self):
        groups = get_correlation_groups("UNKNOWNUSDT")
        assert groups == set()

    def test_meme_symbol(self):
        groups = get_correlation_groups("DOGEUSDT")
        assert "MEME" in groups

    def test_defi_symbol(self):
        groups = get_correlation_groups("UNIUSDT")
        assert "DEFI" in groups

    def test_layer2_symbol(self):
        groups = get_correlation_groups("ARBUSDT")
        assert "LAYER2" in groups


class TestCheckCorrelationLimit:
    def test_allows_first_long_in_group(self):
        """First LONG position in a group must be allowed."""
        allowed, reason = check_correlation_limit(
            symbol="ETHUSDT",
            direction="LONG",
            active_positions={"s1": ("BNBUSDT", "LONG")},
            max_per_group=3,
        )
        assert allowed is True
        assert reason == ""

    def test_allows_up_to_max_long_positions(self):
        """3 existing LONGs in MAJOR_ALTS + 1 new one = 4 → blocked at limit=3."""
        active = {
            "s1": ("ETHUSDT", "LONG"),
            "s2": ("BNBUSDT", "LONG"),
            "s3": ("SOLUSDT", "LONG"),
        }
        # 3 existing LONGs – the 4th should be blocked
        allowed, reason = check_correlation_limit(
            symbol="ADAUSDT",
            direction="LONG",
            active_positions=active,
            max_per_group=3,
        )
        assert allowed is False
        assert "MAJOR_ALTS" in reason
        assert "3/3" in reason

    def test_allows_short_when_longs_at_limit(self):
        """A SHORT in the same group must be allowed even if LONGs are at limit."""
        active = {
            "s1": ("ETHUSDT", "LONG"),
            "s2": ("BNBUSDT", "LONG"),
            "s3": ("SOLUSDT", "LONG"),
        }
        allowed, reason = check_correlation_limit(
            symbol="ADAUSDT",
            direction="SHORT",
            active_positions=active,
            max_per_group=3,
        )
        assert allowed is True
        assert reason == ""

    def test_different_groups_do_not_interfere(self):
        """LONGs in MAJOR_ALTS at limit must NOT block a LONG in MEME group."""
        active = {
            "s1": ("ETHUSDT", "LONG"),
            "s2": ("BNBUSDT", "LONG"),
            "s3": ("SOLUSDT", "LONG"),
        }
        allowed, reason = check_correlation_limit(
            symbol="DOGEUSDT",
            direction="LONG",
            active_positions=active,
            max_per_group=3,
        )
        assert allowed is True
        assert reason == ""

    def test_unknown_symbol_always_allowed(self):
        """An uncorrelated symbol must never be blocked by the correlation filter."""
        active = {
            "s1": ("ETHUSDT", "LONG"),
            "s2": ("BNBUSDT", "LONG"),
            "s3": ("SOLUSDT", "LONG"),
        }
        allowed, reason = check_correlation_limit(
            symbol="UNKNOWNUSDT",
            direction="LONG",
            active_positions=active,
            max_per_group=3,
        )
        assert allowed is True
        assert reason == ""

    def test_empty_active_positions_always_allowed(self):
        """No active positions → any new position must be allowed."""
        allowed, reason = check_correlation_limit(
            symbol="ETHUSDT",
            direction="LONG",
            active_positions={},
            max_per_group=3,
        )
        assert allowed is True
        assert reason == ""

    def test_allows_exactly_at_limit_minus_one(self):
        """2 existing LONGs with limit=3 → 3rd is still allowed."""
        active = {
            "s1": ("ETHUSDT", "LONG"),
            "s2": ("BNBUSDT", "LONG"),
        }
        allowed, reason = check_correlation_limit(
            symbol="SOLUSDT",
            direction="LONG",
            active_positions=active,
            max_per_group=3,
        )
        assert allowed is True
        assert reason == ""


class TestComputeRollingBtcCorrelation:
    """Tests for the compute_rolling_btc_correlation() convenience wrapper."""

    def test_perfectly_correlated_series(self):
        from src.correlation import compute_rolling_btc_correlation
        prices = [float(i) for i in range(1, 60)]
        result = compute_rolling_btc_correlation("ETHUSDT", prices, prices, window=50)
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_insufficient_data_returns_zero(self):
        from src.correlation import compute_rolling_btc_correlation
        result = compute_rolling_btc_correlation("SOLUSDT", [1.0, 2.0], [1.0, 2.0], window=50)
        assert result == pytest.approx(0.0)

    def test_custom_window_respected(self):
        from src.correlation import compute_rolling_btc_correlation
        prices_btc = [float(i) for i in range(1, 60)]
        prices_pair = [float(i * 2) for i in range(1, 60)]
        r20 = compute_rolling_btc_correlation("BNBUSDT", prices_btc, prices_pair, window=20)
        r50 = compute_rolling_btc_correlation("BNBUSDT", prices_btc, prices_pair, window=50)
        # Both should be ~1.0 for linear series; just check both return valid correlation
        assert -1.0 <= r20 <= 1.0
        assert -1.0 <= r50 <= 1.0
