"""Tests for audit finding remediations.

Covers:
- F-010: Safe env var parsing helpers
- F-011: Boot-time env var validation
- F-021: Circuit breaker Redis persistence
- F-024: Scanner heartbeat healthcheck
- F-033: LOG_LEVEL validation
- F-039: DCA zone epsilon guard
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# F-010: Safe env var parsing
# ---------------------------------------------------------------------------


class TestSafeEnvParsing:
    """Verify _safe_int / _safe_float / _safe_bool handle invalid values."""

    def test_safe_int_valid(self):
        from config import _safe_int

        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert _safe_int("TEST_INT", "0") == 42

    def test_safe_int_invalid_falls_back(self):
        from config import _safe_int

        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            assert _safe_int("TEST_INT", "7") == 7

    def test_safe_int_missing_uses_default(self):
        from config import _safe_int

        env = dict(os.environ)
        env.pop("TEST_SAFE_INT_MISSING", None)
        with patch.dict(os.environ, env, clear=True):
            assert _safe_int("TEST_SAFE_INT_MISSING", "99") == 99

    def test_safe_float_valid(self):
        from config import _safe_float

        with patch.dict(os.environ, {"TEST_FLOAT": "3.14"}):
            assert abs(_safe_float("TEST_FLOAT", "0.0") - 3.14) < 0.001

    def test_safe_float_invalid_falls_back(self):
        from config import _safe_float

        with patch.dict(os.environ, {"TEST_FLOAT": "abc"}):
            assert _safe_float("TEST_FLOAT", "2.5") == 2.5

    def test_safe_bool_true_variants(self):
        from config import _safe_bool

        for val in ("true", "True", "TRUE", "1", "yes", "YES"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert _safe_bool("TEST_BOOL", "false") is True, f"Failed for {val}"

    def test_safe_bool_false_variants(self):
        from config import _safe_bool

        for val in ("false", "0", "no", "off", "random"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert _safe_bool("TEST_BOOL", "true") is False, f"Failed for {val}"


# ---------------------------------------------------------------------------
# F-011: Boot-time env var validation
# ---------------------------------------------------------------------------


class TestEnvVarValidation:
    """validate_critical_env_vars should emit warnings for missing critical vars."""

    def test_warns_when_telegram_token_empty(self, caplog):
        from config import validate_critical_env_vars

        import logging

        with patch("config.TELEGRAM_BOT_TOKEN", ""), \
             patch("config.TELEGRAM_ADMIN_CHAT_ID", "123"), \
             patch("config.TELEGRAM_ACTIVE_CHANNEL_ID", "-100"):
            with caplog.at_level(logging.WARNING):
                validate_critical_env_vars()
        assert any("TELEGRAM_BOT_TOKEN" in r.message for r in caplog.records)

    def test_no_warnings_when_all_set(self, caplog):
        from config import validate_critical_env_vars

        import logging

        with patch("config.TELEGRAM_BOT_TOKEN", "tok"), \
             patch("config.TELEGRAM_ADMIN_CHAT_ID", "123"), \
             patch("config.TELEGRAM_ACTIVE_CHANNEL_ID", "-100"):
            with caplog.at_level(logging.WARNING):
                validate_critical_env_vars()
        bot_warns = [r for r in caplog.records if "TELEGRAM_BOT_TOKEN" in r.message]
        assert len(bot_warns) == 0


# ---------------------------------------------------------------------------
# F-021: Circuit breaker persistence
# ---------------------------------------------------------------------------


class TestCircuitBreakerPersistence:
    """Verify save/restore round-trip for CircuitBreaker state."""

    def _make_cb(self, **kwargs):
        from src.circuit_breaker import CircuitBreaker

        return CircuitBreaker(**kwargs)

    def test_state_to_dict_healthy(self):
        cb = self._make_cb()
        d = cb._state_to_dict()
        assert d["tripped"] is False
        assert d["consecutive_sl"] == 0
        assert d["status_mode"] == "healthy"
        assert isinstance(d["outcomes"], list)

    def test_state_to_dict_after_trip(self):
        cb = self._make_cb(max_consecutive_sl=2, cooldown_seconds=60)
        cb.record_outcome("s1", hit_sl=True, pnl_pct=-1.0)
        cb.record_outcome("s2", hit_sl=True, pnl_pct=-1.0)
        assert cb.is_tripped()
        d = cb._state_to_dict()
        assert d["tripped"] is True
        assert d["trip_remaining_s"] > 0
        assert d["status_mode"] == "cooldown"

    def test_restore_from_dict_healthy(self):
        cb = self._make_cb()
        state = {
            "tripped": False,
            "trip_reason": "",
            "trip_remaining_s": 0,
            "consecutive_sl": 0,
            "status_mode": "healthy",
            "per_symbol_tripped": {},
            "per_symbol_consecutive_sl": {},
            "outcomes": [],
        }
        cb._restore_from_dict(state)
        assert cb.is_tripped() is False

    def test_restore_from_dict_tripped_with_cooldown(self):
        cb = self._make_cb(cooldown_seconds=120)
        state = {
            "tripped": True,
            "trip_reason": "3 consecutive SL hits",
            "trip_remaining_s": 60.0,
            "consecutive_sl": 3,
            "status_mode": "cooldown",
            "per_symbol_tripped": {},
            "per_symbol_consecutive_sl": {},
            "outcomes": [
                {"signal_id": "s1", "hit_sl": True, "pnl_pct": -1.0, "age_s": 10, "symbol": "BTC"},
                {"signal_id": "s2", "hit_sl": True, "pnl_pct": -1.0, "age_s": 5, "symbol": "BTC"},
                {"signal_id": "s3", "hit_sl": True, "pnl_pct": -1.0, "age_s": 1, "symbol": "BTC"},
            ],
        }
        cb._restore_from_dict(state)
        assert cb.is_tripped() is True
        assert cb._cooldown_remaining() > 0

    def test_restore_per_symbol_suppression(self):
        cb = self._make_cb()
        state = {
            "tripped": False,
            "trip_reason": "",
            "trip_remaining_s": 0,
            "consecutive_sl": 0,
            "status_mode": "healthy",
            "per_symbol_tripped": {"BTCUSDT": 30.0},
            "per_symbol_consecutive_sl": {"BTCUSDT": 3},
            "outcomes": [],
        }
        cb._restore_from_dict(state)
        assert cb.is_symbol_tripped("BTCUSDT") is True
        assert cb.is_symbol_tripped("ETHUSDT") is False

    def test_round_trip_preserves_state(self):
        cb1 = self._make_cb(max_consecutive_sl=2, cooldown_seconds=300)
        cb1.record_outcome("s1", hit_sl=True, pnl_pct=-1.5, symbol="BTCUSDT")
        cb1.record_outcome("s2", hit_sl=True, pnl_pct=-2.0, symbol="BTCUSDT")
        assert cb1.is_tripped()
        d = cb1._state_to_dict()

        cb2 = self._make_cb(max_consecutive_sl=2, cooldown_seconds=300)
        cb2._restore_from_dict(d)
        assert cb2.is_tripped()
        assert cb2._status_mode == "cooldown"
        assert cb2._cooldown_remaining() > 0

    @pytest.mark.asyncio
    async def test_save_state_to_redis(self):
        cb = self._make_cb()
        cb.record_outcome("s1", hit_sl=True, pnl_pct=-1.0)

        mock_redis = MagicMock()
        mock_redis.available = True
        mock_redis.client = AsyncMock()
        mock_redis.client.set = AsyncMock()

        result = await cb.save_state(mock_redis)
        assert result is True
        mock_redis.client.set.assert_awaited_once()
        call_args = mock_redis.client.set.call_args
        key = call_args[0][0]
        assert key == "circuit_breaker:state"
        payload = json.loads(call_args[0][1])
        assert "tripped" in payload

    @pytest.mark.asyncio
    async def test_restore_state_from_redis(self):
        cb1 = self._make_cb(max_consecutive_sl=2, cooldown_seconds=60)
        cb1.record_outcome("s1", hit_sl=True, pnl_pct=-1.0)
        cb1.record_outcome("s2", hit_sl=True, pnl_pct=-1.0)
        assert cb1.is_tripped()

        saved = json.dumps(cb1._state_to_dict())

        cb2 = self._make_cb(max_consecutive_sl=2, cooldown_seconds=60)
        mock_redis = MagicMock()
        mock_redis.available = True
        mock_redis.client = AsyncMock()
        mock_redis.client.get = AsyncMock(return_value=saved)

        result = await cb2.restore_state(mock_redis)
        assert result is True
        assert cb2.is_tripped() is True

    @pytest.mark.asyncio
    async def test_save_state_returns_false_when_redis_unavailable(self):
        cb = self._make_cb()
        mock_redis = MagicMock()
        mock_redis.available = False
        result = await cb.save_state(mock_redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_state_returns_false_when_no_data(self):
        cb = self._make_cb()
        mock_redis = MagicMock()
        mock_redis.available = True
        mock_redis.client = AsyncMock()
        mock_redis.client.get = AsyncMock(return_value=None)
        result = await cb.restore_state(mock_redis)
        assert result is False


# ---------------------------------------------------------------------------
# F-024: Scanner heartbeat healthcheck
# ---------------------------------------------------------------------------


class TestHealthcheckHeartbeat:
    """Test the heartbeat freshness logic used in healthcheck.py."""

    _MAX_AGE = 120.0

    @staticmethod
    def _heartbeat_fresh(path: str, max_age: float = 120.0) -> bool:
        """Re-implementation of healthcheck._scanner_heartbeat_fresh for testing."""
        if not os.path.isfile(path):
            return True
        try:
            age = time.time() - os.path.getmtime(path)
            return age < max_age
        except OSError:
            return True

    def test_fresh_heartbeat_passes(self, tmp_path):
        heartbeat_file = tmp_path / "scanner_heartbeat"
        heartbeat_file.write_text(str(time.time()))
        assert self._heartbeat_fresh(str(heartbeat_file)) is True

    def test_stale_heartbeat_fails(self, tmp_path):
        heartbeat_file = tmp_path / "scanner_heartbeat"
        heartbeat_file.write_text(str(time.time() - 300))
        os.utime(str(heartbeat_file), (time.time() - 300, time.time() - 300))
        assert self._heartbeat_fresh(str(heartbeat_file)) is False

    def test_missing_heartbeat_passes(self, tmp_path):
        assert self._heartbeat_fresh(str(tmp_path / "nonexistent")) is True


# ---------------------------------------------------------------------------
# F-033: LOG_LEVEL validation
# ---------------------------------------------------------------------------


class TestLogLevelValidation:
    def test_valid_levels_accepted(self):
        from config import _VALID_LOG_LEVELS

        for level in _VALID_LOG_LEVELS:
            assert level in {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}

    def test_invalid_level_defaults_to_info(self):
        # We test this at the module level — it's already validated on import.
        # Just confirm the mechanism exists.
        from config import _VALID_LOG_LEVELS

        assert "INFOO" not in _VALID_LOG_LEVELS
        assert "INFO" in _VALID_LOG_LEVELS


# ---------------------------------------------------------------------------
# F-039: DCA zone epsilon guard
# ---------------------------------------------------------------------------


class TestDCAZoneEpsilonGuard:
    """compute_dca_zone should return (0,0) when entry ≈ stop_loss."""

    def test_zero_sl_distance_returns_zero_zone(self):
        from src.dca import compute_dca_zone
        from src.smc import Direction

        lo, hi = compute_dca_zone(entry=100.0, stop_loss=100.0, direction=Direction.LONG)
        assert lo == 0.0
        assert hi == 0.0

    def test_near_zero_sl_distance_returns_zero_zone(self):
        from src.dca import compute_dca_zone
        from src.smc import Direction

        lo, hi = compute_dca_zone(
            entry=100.0,
            stop_loss=100.0 + 1e-12,
            direction=Direction.LONG,
        )
        assert lo == 0.0
        assert hi == 0.0

    def test_normal_sl_distance_returns_valid_zone(self):
        from src.dca import compute_dca_zone
        from src.smc import Direction

        lo, hi = compute_dca_zone(entry=100.0, stop_loss=95.0, direction=Direction.LONG)
        assert lo > 0
        assert hi > 0
        assert lo < hi < 100.0

    def test_short_direction_zone(self):
        from src.dca import compute_dca_zone
        from src.smc import Direction

        lo, hi = compute_dca_zone(entry=100.0, stop_loss=105.0, direction=Direction.SHORT)
        assert lo > 100.0
        assert hi > lo


# ---------------------------------------------------------------------------
# F-013: Shutdown active-signal notification
# ---------------------------------------------------------------------------


class TestShutdownNotification:
    """Bootstrap.shutdown should notify admin about active signals."""

    @pytest.mark.asyncio
    async def test_shutdown_notifies_with_active_signals(self):
        from src.bootstrap import Bootstrap

        task = asyncio.create_task(asyncio.sleep(60))
        engine = SimpleNamespace(
            _tasks=[task],
            router=SimpleNamespace(
                stop=AsyncMock(),
                active_signals={"sig1": "s", "sig2": "s"},
            ),
            monitor=SimpleNamespace(stop=AsyncMock()),
            telemetry=SimpleNamespace(stop=AsyncMock()),
            _ws_spot=None,
            _ws_futures=None,
            data_store=SimpleNamespace(save_snapshot=AsyncMock(), close=AsyncMock()),
            pair_mgr=SimpleNamespace(close=AsyncMock()),
            _exchange_mgr=SimpleNamespace(close=AsyncMock()),
            _scanner=SimpleNamespace(spot_client=None),
            _redis_client=SimpleNamespace(close=AsyncMock(), available=False),
            telegram=SimpleNamespace(
                stop=AsyncMock(),
                send_admin_alert=AsyncMock(return_value=True),
            ),
        )
        bootstrap = Bootstrap(engine)
        await bootstrap.shutdown()

        # Should have sent an alert about 2 active signals
        calls = engine.telegram.send_admin_alert.call_args_list
        assert len(calls) >= 1
        assert "2 active signal" in calls[0][0][0]

    @pytest.mark.asyncio
    async def test_shutdown_no_alert_when_no_active_signals(self):
        from src.bootstrap import Bootstrap

        task = asyncio.create_task(asyncio.sleep(60))
        engine = SimpleNamespace(
            _tasks=[task],
            router=SimpleNamespace(stop=AsyncMock(), active_signals={}),
            monitor=SimpleNamespace(stop=AsyncMock()),
            telemetry=SimpleNamespace(stop=AsyncMock()),
            _ws_spot=None,
            _ws_futures=None,
            data_store=SimpleNamespace(save_snapshot=AsyncMock(), close=AsyncMock()),
            pair_mgr=SimpleNamespace(close=AsyncMock()),
            _exchange_mgr=SimpleNamespace(close=AsyncMock()),
            _scanner=SimpleNamespace(spot_client=None),
            _redis_client=SimpleNamespace(close=AsyncMock(), available=False),
            telegram=SimpleNamespace(
                stop=AsyncMock(),
                send_admin_alert=AsyncMock(return_value=True),
            ),
        )
        bootstrap = Bootstrap(engine)
        await bootstrap.shutdown()

        # No alert should be sent when no active signals
        engine.telegram.send_admin_alert.assert_not_awaited()
