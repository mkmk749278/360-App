"""FastAPI REST + WebSocket server for the 360 Signals Android app.

Exposes:
  GET  /health                  → service health & uptime
  GET  /signals/active          → currently active signals
  GET  /signals/history         → last N completed signals
  GET  /stats                   → today's win/loss/winrate/avg_pnl + per_pair
  GET  /status                  → engine status + per_pair_breaker
  GET  /failed_signals          → dead-letter signal list
  POST /fcm/register            → register FCM push token
  POST /settings/signal_limits  → update per-channel signal limits at runtime
  WS   /ws/signals              → real-time signal push feed
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.utils import get_logger

log = get_logger("api_server")

# ---------------------------------------------------------------------------
# Engine reference singleton — populated by src.main after boot
# ---------------------------------------------------------------------------
_engine_ref: Optional[Any] = None
_start_time: float = time.time()
ENGINE_VERSION = "2.0"


def set_engine(engine: Any) -> None:
    """Wire the running engine instance into the API server."""
    global _engine_ref, _start_time
    _engine_ref = engine
    _start_time = time.time()


# ---------------------------------------------------------------------------
# Signal serialisation helper
# ---------------------------------------------------------------------------

def _signal_to_dict(sig: Any) -> Dict[str, Any]:
    """Convert a Signal dataclass to a JSON-safe dict."""
    d = dataclasses.asdict(sig)
    # Coerce Direction enum → string
    if hasattr(sig, "direction") and hasattr(sig.direction, "value"):
        d["direction"] = sig.direction.value
    # Coerce all datetime fields → ISO-8601 string
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    # Ensure required API fields are present with fallback defaults
    d.setdefault("id", d.get("signal_id", ""))
    d.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    # Compute rr_ratio server-side for accuracy
    try:
        entry = float(d.get("entry", 0) or 0)
        stop_loss = float(d.get("stop_loss", 0) or 0)
        tp1 = float(d.get("tp1", 0) or 0)
        risk = abs(entry - stop_loss)
        d["rr_ratio"] = round(abs(tp1 - entry) / risk, 2) if risk > 0 else 0.0
    except Exception:
        d.setdefault("rr_ratio", 0.0)
    return d


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[type-arg]
    log.info("API server started — listening for requests")
    yield
    log.info("API server shutting down")


app = FastAPI(
    title="360 Signals API",
    version=ENGINE_VERSION,
    description="REST + WebSocket API for the 360 Crypto Signal Engine",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "engine_version": ENGINE_VERSION,
    }


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

@app.get("/signals/active")
async def get_active_signals() -> List[Dict[str, Any]]:
    if _engine_ref is None:
        return []
    try:
        signals = _engine_ref.router.active_signals
        return [_signal_to_dict(s) for s in signals.values()]
    except Exception as exc:
        log.error("Error fetching active signals: {}", exc)
        return []


@app.get("/signals/history")
async def get_signal_history(limit: int = 50) -> List[Dict[str, Any]]:
    if _engine_ref is None:
        return []
    try:
        history: List[Any] = _engine_ref._signal_history
        limited = history[-limit:] if len(history) > limit else history
        return [_signal_to_dict(s) for s in reversed(limited)]
    except Exception as exc:
        log.error("Error fetching signal history: {}", exc)
        return []


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/stats")
async def get_stats() -> Dict[str, Any]:
    empty: Dict[str, Any] = {
        "wins": 0, "losses": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total": 0,
        "per_pair": [],
    }
    if _engine_ref is None:
        return empty
    try:
        tracker = _engine_ref._performance_tracker
        if tracker is None:
            return empty
        summary = tracker.get_daily_summary(window_days=1)
        # Per-pair scoreboard (7-day rolling window)
        per_pair: List[Dict[str, Any]] = []
        try:
            scoreboard = tracker.get_pair_scoreboard(window_days=7)
            for sym, data in scoreboard.items():
                per_pair.append({
                    "symbol": sym,
                    "win_rate": data.get("win_rate", 0.0),
                    "avg_pnl": data.get("avg_pnl", 0.0),
                    "total": data.get("count", 0),
                })
            per_pair.sort(key=lambda x: x["win_rate"], reverse=True)
        except Exception:
            pass
        return {
            "wins": summary.get("wins", 0),
            "losses": summary.get("losses", 0),
            "win_rate": round(summary.get("win_rate", 0.0), 1),
            "avg_pnl": round(summary.get("avg_pnl", 0.0), 2),
            "total": summary.get("total", 0),
            "per_pair": per_pair,
        }
    except Exception as exc:
        log.error("Error fetching stats: {}", exc)
        return empty


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@app.get("/status")
async def get_status() -> Dict[str, Any]:
    if _engine_ref is None:
        return {"engine": "starting"}
    try:
        cb = _engine_ref._circuit_breaker
        pair_mgr = _engine_ref.pair_mgr
        from config import SCAN_INTERVAL_SECONDS
        try:
            from src.regime import MarketRegimeDetector
            regime_obj = getattr(_engine_ref, "_regime_detector", None)
            regime = regime_obj.current_regime if regime_obj else "UNKNOWN"
        except Exception:
            regime = "UNKNOWN"

        # Per-pair circuit breaker state
        per_pair_breaker: Dict[str, bool] = {}
        try:
            symbols = getattr(pair_mgr, "symbols", [])
            for sym in symbols:
                if cb.is_symbol_tripped(sym):
                    per_pair_breaker[sym] = True
        except Exception:
            pass

        return {
            "pairs_count": len(getattr(pair_mgr, "symbols", [])),
            "scan_interval": SCAN_INTERVAL_SECONDS,
            "circuit_breaker_tripped": cb.is_tripped(),
            "circuit_breaker_state": "TRIPPED" if cb.is_tripped() else "OK",
            "circuit_breaker_status": cb.status_text(),
            "regime": str(regime),
            "active_signals_count": len(_engine_ref.router.active_signals),
            "per_pair_breaker": per_pair_breaker,
        }
    except Exception as exc:
        log.error("Error fetching status: {}", exc)
        return {"engine": "error", "detail": str(exc)}


# ---------------------------------------------------------------------------
# FCM Token Registration
# ---------------------------------------------------------------------------

_fcm_tokens: set = set()


@app.post("/fcm/register")
async def register_fcm_token(payload: Dict[str, Any]) -> Dict[str, str]:
    token = payload.get("token", "")
    if token:
        _fcm_tokens.add(token)
        log.info("FCM token registered (total: {})", len(_fcm_tokens))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Signal Limits — runtime update of per-channel max concurrent signals
# ---------------------------------------------------------------------------

# Map of accepted payload keys → config dict channel key
_SIGNAL_LIMIT_KEY_MAP: Dict[str, str] = {
    "MAX_SCALP_SIGNALS": "360_SCALP",
    "MAX_SCALP_FVG_SIGNALS": "360_SCALP_FVG",
    "MAX_SCALP_CVD_SIGNALS": "360_SCALP_CVD",
    "MAX_SCALP_VWAP_SIGNALS": "360_SCALP_VWAP",
    "MAX_SCALP_OBI_SIGNALS": "360_SCALP_OBI",
}


@app.post("/settings/signal_limits")
async def update_signal_limits(payload: Dict[str, int]) -> Dict[str, Any]:
    """Update per-channel max concurrent signal limits at runtime.

    Accepts a JSON body like ``{"MAX_SCALP_SIGNALS": 4, ...}``.
    Only recognised keys are applied; unknown keys are silently ignored.
    Values are clamped to ``[1, 10]``.
    """
    from config import MAX_CONCURRENT_SIGNALS_PER_CHANNEL

    updated: Dict[str, int] = {}
    for key, value in payload.items():
        channel = _SIGNAL_LIMIT_KEY_MAP.get(key)
        if channel is not None and isinstance(value, int) and 1 <= value <= 10:
            MAX_CONCURRENT_SIGNALS_PER_CHANNEL[channel] = value
            updated[key] = value
            log.info("Signal limit updated: {} = {} (channel {})", key, value, channel)

    return {"status": "ok", "updated": updated}


# ---------------------------------------------------------------------------
# Failed signals (dead-letter list)
# ---------------------------------------------------------------------------

@app.get("/failed_signals")
async def get_failed_signals() -> List[Dict[str, Any]]:
    """Return signals that failed all 5 delivery attempts (dead-letter list)."""
    if _engine_ref is None:
        return []
    try:
        return _engine_ref.router.dead_letter_signals
    except Exception as exc:
        log.error("Error fetching failed signals: {}", exc)
        return []


# ---------------------------------------------------------------------------
# WebSocket — real-time signal feed
# ---------------------------------------------------------------------------

@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket) -> None:
    await websocket.accept()
    log.info("WebSocket client connected: {}", websocket.client)

    if _engine_ref is None:
        await websocket.send_json({"error": "engine not ready"})
        await websocket.close()
        return

    router = _engine_ref.router
    queue: asyncio.Queue = router.subscribe_ws()

    # Send all currently active signals immediately on connect
    try:
        active = router.active_signals
        for sig in active.values():
            await websocket.send_json(_signal_to_dict(sig))
    except Exception as exc:
        log.debug("Error sending initial signals to WS client: {}", exc)

    try:
        while True:
            try:
                signal = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(_signal_to_dict(signal))
            except asyncio.TimeoutError:
                # Send a heartbeat ping so the connection stays alive
                try:
                    await websocket.send_json({"type": "heartbeat", "ts": time.time()})
                except Exception:
                    break
    except WebSocketDisconnect:
        log.info("WebSocket client disconnected: {}", websocket.client)
    except Exception as exc:
        log.warning("WebSocket error: {}", exc)
    finally:
        router.unsubscribe_ws(queue)
