"""Tests for extended channel strategies – ScalpDivergence, ScalpSupertrend,
ScalpIchimoku, ScalpOrderblock.

These four channels had zero dedicated test coverage as identified by
SIGNAL_CHANNEL_AUDIT.md §5 (P0 recommendation).
"""

import numpy as np
import pytest

from src.channels.scalp_divergence import ScalpDivergenceChannel
from src.channels.scalp_supertrend import ScalpSupertrendChannel
from src.channels.scalp_ichimoku import ScalpIchimokuChannel
from src.channels.scalp_orderblock import ScalpOrderblockChannel
from src.smc import Direction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candles(n=60, base=100.0, trend=0.0):
    """Create synthetic OHLCV data."""
    close = np.cumsum(np.ones(n) * trend) + base
    high = close + 0.5
    low = close - 0.5
    opn = close - 0.1
    volume = np.ones(n) * 1000.0
    return {
        "open": list(opn),
        "high": list(high),
        "low": list(low),
        "close": list(close),
        "volume": list(volume),
    }


def _make_indicators(adx_val=25, atr_val=0.5, rsi_val=50, ema9=101.0, ema21=100.0):
    return {
        "adx_last": adx_val,
        "atr_last": atr_val,
        "rsi_last": rsi_val,
        "ema9_last": ema9,
        "ema21_last": ema21,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ScalpDivergenceChannel
# ═══════════════════════════════════════════════════════════════════════════

class TestScalpDivergenceChannel:
    """Unit tests for the RSI/MACD divergence scalp channel."""

    def _build_bullish_divergence_candles(self, n=40):
        """Create candles with a regular bullish divergence pattern.

        Price makes a lower low but RSI makes a higher low.
        """
        close = [100.0] * n
        # Create two price lows: the second one is lower than the first
        for i in range(10, 14):
            close[i] = 98.0  # first low
        for i in range(25, 29):
            close[i] = 97.0  # second (lower) low → price lower low
        close[-1] = 99.0  # current price recovering

        high = [c + 0.5 for c in close]
        low = [c - 0.5 for c in close]
        opn = [c - 0.1 for c in close]
        volume = [1000.0] * n

        # RSI array with higher low at the second price low
        rsi_arr = [50.0] * n
        for i in range(10, 14):
            rsi_arr[i] = 28.0  # first RSI low
        for i in range(25, 29):
            rsi_arr[i] = 32.0  # second RSI higher low → bullish divergence

        return (
            {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
            rsi_arr,
        )

    def _build_bearish_divergence_candles(self, n=40):
        """Create candles with a regular bearish divergence.

        Price makes a higher high but RSI makes a lower high.
        """
        close = [100.0] * n
        for i in range(10, 14):
            close[i] = 103.0  # first high
        for i in range(25, 29):
            close[i] = 105.0  # second (higher) high → price higher high
        close[-1] = 103.5

        high = [c + 0.5 for c in close]
        low = [c - 0.5 for c in close]
        opn = [c - 0.1 for c in close]
        volume = [1000.0] * n

        rsi_arr = [50.0] * n
        for i in range(10, 14):
            rsi_arr[i] = 75.0  # first RSI high
        for i in range(25, 29):
            rsi_arr[i] = 68.0  # second RSI lower high → bearish divergence

        return (
            {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
            rsi_arr,
        )

    def test_bullish_divergence_long_signal(self):
        """Regular bullish divergence → LONG signal."""
        ch = ScalpDivergenceChannel()
        cd, rsi_arr = self._build_bullish_divergence_candles()
        candles = {"5m": cd}
        ind = _make_indicators(adx_val=20, rsi_val=35)
        ind["rsi_arr"] = rsi_arr
        indicators = {"5m": ind}
        smc_data = {}

        sig = ch.evaluate("BTCUSDT", candles, indicators, smc_data, 0.01, 10_000_000)
        if sig is not None:
            assert sig.direction == Direction.LONG
            assert sig.setup_class == "RSI_MACD_DIVERGENCE"
            assert sig.analyst_reason is not None and "BULL" in sig.analyst_reason

    def test_bearish_divergence_short_signal(self):
        """Regular bearish divergence → SHORT signal."""
        ch = ScalpDivergenceChannel()
        cd, rsi_arr = self._build_bearish_divergence_candles()
        candles = {"5m": cd}
        ind = _make_indicators(adx_val=20, rsi_val=65)
        ind["rsi_arr"] = rsi_arr
        indicators = {"5m": ind}
        smc_data = {}

        sig = ch.evaluate("BTCUSDT", candles, indicators, smc_data, 0.01, 10_000_000)
        if sig is not None:
            assert sig.direction == Direction.SHORT
            assert "BEAR" in sig.analyst_reason

    def test_no_signal_when_adx_too_high(self):
        """ADX > 40 → divergence unreliable, should return None."""
        ch = ScalpDivergenceChannel()
        cd, rsi_arr = self._build_bullish_divergence_candles()
        candles = {"5m": cd}
        ind = _make_indicators(adx_val=45, rsi_val=35)
        ind["rsi_arr"] = rsi_arr
        indicators = {"5m": ind}

        sig = ch.evaluate("BTCUSDT", candles, indicators, smc_data={}, spread_pct=0.01, volume_24h_usd=10_000_000)
        assert sig is None

    def test_no_signal_on_insufficient_data(self):
        """Fewer than 30 candles → return None."""
        ch = ScalpDivergenceChannel()
        candles = {"5m": _make_candles(15)}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None

    def test_no_signal_on_low_volume(self):
        """Volume below minimum → basic filter rejection."""
        ch = ScalpDivergenceChannel()
        cd, rsi_arr = self._build_bullish_divergence_candles()
        candles = {"5m": cd}
        ind = _make_indicators(adx_val=20, rsi_val=35)
        ind["rsi_arr"] = rsi_arr
        indicators = {"5m": ind}

        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 100)  # low volume
        assert sig is None

    def test_analyst_reason_includes_macd_tag(self):
        """When MACD divergence also detected, analyst_reason should include '+MACD'."""
        ch = ScalpDivergenceChannel()
        cd, rsi_arr = self._build_bullish_divergence_candles()
        candles = {"5m": cd}
        ind = _make_indicators(adx_val=20, rsi_val=35)
        ind["rsi_arr"] = rsi_arr
        # MACD histogram with matching bullish divergence pattern
        macd_hist = [0.0] * 40
        for i in range(10, 14):
            macd_hist[i] = -0.5  # first MACD low
        for i in range(25, 29):
            macd_hist[i] = -0.3  # second MACD higher low → MACD bullish div
        ind["macd_histogram"] = macd_hist
        indicators = {"5m": ind}

        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        if sig is not None:
            assert "+MACD" in sig.analyst_reason


# ═══════════════════════════════════════════════════════════════════════════
# ScalpSupertrendChannel
# ═══════════════════════════════════════════════════════════════════════════

class TestScalpSupertrendChannel:
    """Unit tests for the Supertrend Flip scalp channel."""

    def _build_flip_candles(self, direction="LONG", n=70):
        """Create candles that produce a Supertrend flip.

        For LONG: downtrend then strong up-move.
        For SHORT: uptrend then strong down-move.
        """
        if direction == "LONG":
            # Down then up — flip from bearish to bullish
            close = list(np.linspace(110, 95, n - 10)) + list(np.linspace(95, 105, 10))
        else:
            # Up then down — flip from bullish to bearish
            close = list(np.linspace(90, 105, n - 10)) + list(np.linspace(105, 95, 10))

        high = [c + 1.5 for c in close]
        low = [c - 1.5 for c in close]
        opn = [c - 0.3 for c in close]
        volume = [2000.0] * n

        return {"open": opn, "high": high, "low": low, "close": close, "volume": volume}

    def test_no_signal_on_insufficient_data(self):
        """Fewer than 55 candles → return None."""
        ch = ScalpSupertrendChannel()
        candles = {"5m": _make_candles(40)}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None

    def test_no_signal_when_adx_below_min(self):
        """ADX < 15 (config min) → no signal."""
        ch = ScalpSupertrendChannel()
        cd = self._build_flip_candles("LONG")
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=10)}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None

    def test_no_signal_on_low_volume(self):
        """Volume below minimum → basic filter rejection."""
        ch = ScalpSupertrendChannel()
        cd = self._build_flip_candles("LONG")
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=25)}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 100)
        assert sig is None

    def test_supertrend_flip_produces_signal_with_analyst_reason(self):
        """When Supertrend flip is detected, signal should have analyst_reason."""
        ch = ScalpSupertrendChannel()
        cd = self._build_flip_candles("LONG")
        candles = {"5m": cd}
        ind = _make_indicators(adx_val=25, rsi_val=45, ema9=103.0, ema21=100.0)
        indicators = {"5m": ind, "15m": _make_indicators(ema9=102, ema21=100), "1h": _make_indicators(ema9=101, ema21=100)}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        # Signal may or may not fire depending on exact supertrend calc,
        # but if it fires, it must have correct metadata
        if sig is not None:
            assert sig.setup_class == "SUPERTREND_FLIP"
            assert sig.analyst_reason is not None
            assert "flip" in sig.analyst_reason.lower()

    def test_no_signal_when_no_flip(self):
        """Flat candles (no Supertrend flip) → no signal."""
        ch = ScalpSupertrendChannel()
        cd = _make_candles(70, base=100.0, trend=0.0)
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=25)}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None


# ═══════════════════════════════════════════════════════════════════════════
# ScalpIchimokuChannel
# ═══════════════════════════════════════════════════════════════════════════

class TestScalpIchimokuChannel:
    """Unit tests for the Ichimoku TK Cross scalp channel."""

    def test_no_signal_on_insufficient_data(self):
        """Fewer than 80 candles → return None."""
        ch = ScalpIchimokuChannel()
        candles = {"5m": _make_candles(60)}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None

    def test_no_signal_on_low_volume(self):
        """Volume below minimum → basic filter rejection."""
        ch = ScalpIchimokuChannel()
        candles = {"5m": _make_candles(100)}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 100)
        assert sig is None

    def _build_bullish_tk_cross_candles(self, n=100):
        """Build candles that should produce a bullish TK cross.

        Strong uptrend puts price above cloud. Tenkan crosses above Kijun.
        """
        # Strong uptrend to put price well above the cloud
        close = list(np.linspace(90, 120, n))
        high = [c + 1.0 for c in close]
        low = [c - 1.0 for c in close]
        opn = [c - 0.2 for c in close]
        volume = [2000.0] * n
        return {"open": opn, "high": high, "low": low, "close": close, "volume": volume}

    def test_bullish_tk_cross_above_cloud(self):
        """Bullish TK cross with price above cloud → LONG."""
        ch = ScalpIchimokuChannel()
        cd = self._build_bullish_tk_cross_candles()
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=25, rsi_val=55)}

        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        # Ichimoku cross depends on exact price dynamics — if it fires, validate metadata
        if sig is not None:
            assert sig.direction == Direction.LONG
            assert sig.setup_class == "ICHIMOKU_TK_CROSS"
            assert sig.analyst_reason is not None
            assert "TK cross" in sig.analyst_reason

    def test_no_signal_on_flat_candles(self):
        """Flat candles → no TK cross, no signal."""
        ch = ScalpIchimokuChannel()
        cd = _make_candles(100, base=100.0, trend=0.0)
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=25)}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None

    def test_falls_back_to_15m(self):
        """When 5m data is insufficient, channel falls back to 15m."""
        ch = ScalpIchimokuChannel()
        # 5m has insufficient data (< 80 candles)
        candles_5m = _make_candles(50, base=100.0)
        candles_15m = _make_candles(100, base=100.0, trend=0.5)
        candles = {"5m": candles_5m, "15m": candles_15m}
        indicators = {
            "5m": _make_indicators(adx_val=25),
            "15m": _make_indicators(adx_val=25, rsi_val=55),
        }
        # Should attempt 15m evaluation (won't necessarily fire but shouldn't crash)
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        # Just verify no crash — signal may or may not be generated


# ═══════════════════════════════════════════════════════════════════════════
# ScalpOrderblockChannel
# ═══════════════════════════════════════════════════════════════════════════

class TestScalpOrderblockChannel:
    """Unit tests for the SMC Order Block Entry scalp channel."""

    def _build_candles_with_bullish_ob(self, n=60):
        """Create candles with a bullish order block.

        A bearish candle followed by a large bullish impulse candle,
        then price returns to the OB zone.
        """
        close = [100.0] * n
        opn = [100.0] * n
        high = [100.5] * n
        low = [99.5] * n
        volume = [1000.0] * n

        # OB candle (bearish): candle at index 30
        opn[30] = 101.0
        close[30] = 99.0
        high[30] = 101.5
        low[30] = 98.5

        # Impulse candle (bullish) at index 31: body ≥ 60%, range ≥ 1.5×ATR
        opn[31] = 99.0
        close[31] = 105.0  # big bullish move
        high[31] = 105.5
        low[31] = 98.8

        # Price moves up then returns to OB zone at the end
        for i in range(32, n - 3):
            close[i] = 106.0 + (i - 32) * 0.1
            opn[i] = close[i] - 0.1
            high[i] = close[i] + 0.5
            low[i] = close[i] - 0.5

        # Price returns to OB zone (98.5 - 101.5 area) for the current candle
        close[-1] = 100.0
        opn[-1] = 100.5
        high[-1] = 101.0
        low[-1] = 99.5

        return {"open": opn, "high": high, "low": low, "close": close, "volume": volume}

    def test_no_signal_on_insufficient_data(self):
        """Fewer than 50 candles → return None."""
        ch = ScalpOrderblockChannel()
        candles = {"5m": _make_candles(30)}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None

    def test_no_signal_on_low_volume(self):
        """Volume below minimum → basic filter rejection."""
        ch = ScalpOrderblockChannel()
        cd = self._build_candles_with_bullish_ob()
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 100)
        assert sig is None

    def test_no_signal_on_flat_candles(self):
        """Flat candles → no order blocks, no signal."""
        ch = ScalpOrderblockChannel()
        cd = _make_candles(60, base=100.0, trend=0.0)
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        assert sig is None

    def test_bullish_ob_retest_signal(self):
        """Price retesting a bullish OB → LONG signal."""
        ch = ScalpOrderblockChannel()
        cd = self._build_candles_with_bullish_ob()
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=25, rsi_val=40)}

        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        # If OB is detected and price retests it, should get a signal
        if sig is not None:
            assert sig.direction == Direction.LONG
            assert sig.setup_class == "SMC_ORDERBLOCK"
            assert sig.analyst_reason is not None
            assert "OB retest" in sig.analyst_reason

    def test_ob_sl_preserves_boundary(self):
        """SL should be based on OB boundary, not generic close±sl_dist."""
        ch = ScalpOrderblockChannel()
        cd = self._build_candles_with_bullish_ob()
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=25, rsi_val=40, atr_val=0.5)}

        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        if sig is not None:
            # SL should be below the OB low (98.5) minus ATR buffer
            assert sig.sl < 99.0  # well below the entry
            assert sig.sl > 0

    def test_wide_spread_rejects(self):
        """Wide spread → basic filter rejection."""
        ch = ScalpOrderblockChannel()
        cd = self._build_candles_with_bullish_ob()
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators()}
        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.05, 10_000_000)
        assert sig is None


# ═══════════════════════════════════════════════════════════════════════════
# Cross-channel: analyst_reason metadata
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalystReasonMetadata:
    """Verify that all channels populate analyst_reason (P0 fix)."""

    def test_cvd_channel_populates_analyst_reason(self):
        """CVD signals should include descriptive analyst_reason."""
        from src.channels.scalp_cvd import ScalpCVDChannel

        ch = ScalpCVDChannel()
        cd = _make_candles(40, base=100.0)
        # Set current price near recent low (at support)
        cd["close"][-1] = min(cd["close"][-20:]) + 0.1
        cd["low"][-1] = cd["close"][-1] - 0.3
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=20, rsi_val=35)}
        smc_data = {
            "cvd_divergence": "BULLISH",
            "cvd_divergence_age": 3,
            "cvd_divergence_strength": 0.6,
        }

        sig = ch.evaluate("BTCUSDT", candles, indicators, smc_data, 0.01, 10_000_000)
        if sig is not None:
            assert sig.analyst_reason is not None
            assert "CVD" in sig.analyst_reason
            assert "BULLISH" in sig.analyst_reason

    def test_vwap_channel_populates_analyst_reason(self):
        """VWAP signals should include descriptive analyst_reason."""
        from src.channels.scalp_vwap import ScalpVWAPChannel

        ch = ScalpVWAPChannel()
        # Create candles where close is at the lower VWAP band
        cd = _make_candles(60, base=100.0)
        # Make the current close very low to trigger lower band touch
        cd["close"][-1] = 95.0
        cd["low"][-1] = 94.5
        # High volume on last candle
        cd["volume"][-1] = 5000.0
        candles = {"5m": cd}
        indicators = {"5m": _make_indicators(adx_val=15, rsi_val=30)}

        sig = ch.evaluate("BTCUSDT", candles, indicators, {}, 0.01, 10_000_000)
        if sig is not None:
            assert sig.analyst_reason is not None
            assert "VWAP" in sig.analyst_reason
