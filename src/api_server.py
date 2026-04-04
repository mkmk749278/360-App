"""FastAPI REST + WebSocket server for the 360 Signals Android app.

Exposes:
  GET  /health           → service health & uptime
  GET  /signals/active   → currently active signals
  GET  /signals/history  → last N completed signals
  GET  /stats            → today's win/loss/winrate/avg_pnl
  GET  /status           → engine status
  WS   /ws/signals       → real-time signal push feed
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
    if _engine_ref is None:
        return {"wins": 0, "losses": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total": 0}
    try:
        tracker = _engine_ref._performance_tracker
        summary = tracker.get_daily_summary(window_days=1)
        return {
            "wins": summary.get("wins", 0),
            "losses": summary.get("losses", 0),
            "win_rate": round(summary.get("win_rate", 0.0), 1),
            "avg_pnl": round(summary.get("avg_pnl", 0.0), 2),
            "total": summary.get("total", 0),
        }
    except Exception as exc:
        log.error("Error fetching stats: {}", exc)
        return {"wins": 0, "losses": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total": 0}


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

        return {
            "pairs_count": len(getattr(pair_mgr, "symbols", [])),
            "scan_interval": SCAN_INTERVAL_SECONDS,
            "circuit_breaker_tripped": cb.is_tripped(),
            "circuit_breaker_status": cb.status_text(),
            "regime": str(regime),
            "active_signals_count": len(_engine_ref.router.active_signals),
        }
    except Exception as exc:
        log.error("Error fetching status: {}", exc)
        return {"engine": "error", "detail": str(exc)}


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
