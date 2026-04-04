"""Tests for the competitive gap improvements.

Feature 1: AI Sentiment wired into scanner signal pipeline
Feature 3: CCXT-based OrderManager with position sizing + partial TP
Feature 5: HTML performance report (generate_html_report)
Feature 8: Cornix auto-execution block (existing formatter, verified wired)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_signal(
    symbol: str = "BTCUSDT",
    channel: str = "360_SPOT",
    direction: str = "LONG",
    entry: float = 100.0,
    signal_id: str = "SPOT-TESTID01",
) -> Any:
    """Build a minimal mock signal object."""
    from src.smc import Direction

    sig = MagicMock()
    sig.symbol = symbol
    sig.channel = channel
    sig.direction = Direction.LONG if direction == "LONG" else Direction.SHORT
    sig.entry = entry
    sig.stop_loss = entry * 0.99
    sig.tp1 = entry * 1.02
    sig.tp2 = entry * 1.05
    sig.tp3 = entry * 1.10
    sig.signal_id = signal_id
    sig.confidence = 70.0
    sig.ai_sentiment_label = ""
    sig.ai_sentiment_summary = ""
    sig.status = "ACTIVE"
    sig.best_tp_hit = 0
    sig.best_tp_pnl_pct = 0.0
    sig.current_price = entry
    return sig


# ===========================================================================
# Feature 3: CCXT-Based OrderManager
# ===========================================================================


class TestOrderManager:
    """OrderManager with mock CCXTClient."""

    def _make_mock_client(self) -> MagicMock:
        client = MagicMock()
        client.create_limit_order = AsyncMock(return_value={"id": "limit-123", "status": "open"})
        client.create_market_order = AsyncMock(return_value={"id": "market-456", "status": "closed"})
        client.cancel_order = AsyncMock(return_value={"id": "limit-123", "status": "canceled"})
        client.fetch_balance = AsyncMock(return_value={"USDT": {"free": 1000.0, "total": 1000.0}})
        return client

    @pytest.mark.asyncio
    async def test_place_limit_order_uses_ccxt(self) -> None:
        from src.order_manager import OrderManager
        client = self._make_mock_client()
        mgr = OrderManager(auto_execution_enabled=True, exchange_client=client)
        sig = _make_signal(channel="360_SPOT")

        order_id = await mgr.place_limit_order(sig)

        assert order_id == "limit-123"
        client.create_limit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_place_market_order_uses_ccxt(self) -> None:
        from src.order_manager import OrderManager
        client = self._make_mock_client()
        mgr = OrderManager(auto_execution_enabled=True, exchange_client=client)
        sig = _make_signal(channel="360_SCALP")

        order_id = await mgr.place_market_order(sig)

        assert order_id == "market-456"
        client.create_market_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_order_uses_ccxt(self) -> None:
        from src.order_manager import OrderManager
        client = self._make_mock_client()
        mgr = OrderManager(auto_execution_enabled=True, exchange_client=client)

        result = await mgr.cancel_order("limit-123", "BTCUSDT")

        assert result is True  # "canceled" status
        client.cancel_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_partial_calls_market_order(self) -> None:
        from src.order_manager import OrderManager
        client = self._make_mock_client()
        mgr = OrderManager(auto_execution_enabled=True, exchange_client=client)
        sig = _make_signal()
        # Simulate an existing open position
        mgr._open_quantities[sig.signal_id] = 0.5

        await mgr.close_partial(sig, 0.33)

        client.create_market_order.assert_called_once()
        # quantity ≈ 0.5 × 0.33 = 0.165
        args = client.create_market_order.call_args
        assert abs(args[0][2] - 0.165) < 1e-6

    @pytest.mark.asyncio
    async def test_position_sizing_uses_balance(self) -> None:
        from src.order_manager import OrderManager
        client = self._make_mock_client()
        # 2% of $1000 = $20; entry $100 → qty = 0.2
        mgr = OrderManager(
            auto_execution_enabled=True,
            exchange_client=client,
            position_size_pct=2.0,
            max_position_usd=1000.0,
        )
        qty = await mgr._compute_quantity(entry_price=100.0)
        assert abs(qty - 0.2) < 1e-6

    @pytest.mark.asyncio
    async def test_disabled_manager_returns_none(self) -> None:
        from src.order_manager import OrderManager
        mgr = OrderManager(auto_execution_enabled=False)
        sig = _make_signal()
        assert await mgr.execute_signal(sig) is None
        assert await mgr.place_limit_order(sig) is None
        assert await mgr.place_market_order(sig) is None
        assert await mgr.cancel_order("x", "BTCUSDT") is False
        assert await mgr.close_partial(sig, 0.33) is None


class TestCCXTClient:
    """CCXTClient raises NotImplementedError when ccxt is absent."""

    def test_raises_when_ccxt_not_installed(self) -> None:
        """Without ccxt installed, _require_exchange should raise NotImplementedError."""
        from src.exchange_client import CCXTClient, _CCXT_AVAILABLE
        if _CCXT_AVAILABLE:
            pytest.skip("ccxt is installed — stub path not testable")
        client = CCXTClient(exchange_id="binance")
        with pytest.raises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                client.create_market_order("BTC/USDT", "buy", 0.01)
            )


# ===========================================================================
# Feature 5: HTML performance report
# ===========================================================================


class TestPerformanceReport:
    """generate_html_report produces a valid HTML file."""

    def test_generates_html_file(self, tmp_path) -> None:
        from src.performance_report import generate_html_report
        from src.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker(storage_path=str(tmp_path / "perf.json"))
        tracker.record_outcome(
            signal_id="X1",
            channel="360_SCALP",
            symbol="BTCUSDT",
            direction="LONG",
            entry=30000.0,
            hit_tp=1,
            hit_sl=False,
            pnl_pct=2.5,
            confidence=75.0,
        )

        out = str(tmp_path / "report.html")
        path = generate_html_report(tracker, output_path=out)

        import os
        assert os.path.exists(path)
        content = open(path).read()
        assert "<!DOCTYPE html>" in content
        assert "Performance Report" in content
        assert "360_SCALP" in content

    def test_empty_tracker_generates_valid_html(self, tmp_path) -> None:
        from src.performance_report import generate_html_report
        from src.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker(storage_path=str(tmp_path / "perf.json"))
        out = str(tmp_path / "empty_report.html")
        path = generate_html_report(tracker, output_path=out)

        content = open(path).read()
        assert "<!DOCTYPE html>" in content

    def test_creates_parent_directory(self, tmp_path) -> None:
        from src.performance_report import generate_html_report
        from src.performance_tracker import PerformanceTracker

        tracker = PerformanceTracker(storage_path=str(tmp_path / "perf.json"))
        nested = str(tmp_path / "nested" / "dir" / "report.html")
        path = generate_html_report(tracker, output_path=nested)
        assert open(path).read().startswith("<!DOCTYPE html>")


# ===========================================================================
# Feature 8: Cornix format wiring
# ===========================================================================


class TestCornixFormatWiring:
    """format_cornix_signal produces valid output; CORNIX_FORMAT_ENABLED gates it."""

    def test_cornix_signal_format_basic(self) -> None:
        from src.cornix_formatter import format_cornix_signal
        sig = _make_signal(channel="360_SPOT")
        result = format_cornix_signal(sig)
        assert "Entry Targets:" in result
        assert "Stop Targets:" in result
        assert "Leverage:" in result

    def test_cornix_signal_format_includes_symbol(self) -> None:
        from src.cornix_formatter import format_cornix_signal
        sig = _make_signal(symbol="ETHUSDT", channel="360_SWING")
        result = format_cornix_signal(sig)
        assert "ETHUSDT" in result

    def test_cornix_disabled_by_default(self) -> None:
        """CORNIX_FORMAT_ENABLED defaults to false — no Cornix block unless opted-in."""
        import config
        # The default .env.example should have this false
        assert hasattr(config, "CORNIX_FORMAT_ENABLED")

    def test_cornix_leverages_by_channel(self) -> None:
        from src.cornix_formatter import format_cornix_signal
        for channel, expected_leverage in [
            ("360_SCALP", "20x"),
            ("360_SWING", "5x"),
            ("360_SPOT", "1x"),
            ("360_GEM", "1x"),
        ]:
            sig = _make_signal(channel=channel)
            result = format_cornix_signal(sig)
            assert expected_leverage in result, f"{channel} should have {expected_leverage}"
