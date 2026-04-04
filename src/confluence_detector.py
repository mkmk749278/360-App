"""Cross-strategy confluence detector.

Detects when multiple channel strategies fire signals for the same
(symbol, direction) within a short time window, indicating higher-quality
setups backed by multiple independent confirmations.

When confluence is detected, the highest-confidence signal is selected and
boosted with a "Multi-Strategy Confluence" label.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class _PendingSignal:
    channel: str
    confidence: float
    signal: Any
    timestamp: float


@dataclass
class ConfluenceResult:
    best_signal: Any
    contributing_channels: List[str]
    confluence_boost: float
    label: str = "Multi-Strategy Confluence"
    strategy_count: int = 0


class ConfluenceDetector:
    """Detects multi-strategy confluence for the same (symbol, direction)."""

    def __init__(
        self,
        window_seconds: float = 60.0,
        min_strategies: int = 2,
    ) -> None:
        self.window_seconds = window_seconds
        self.min_strategies = min_strategies
        self._recent_signals: Dict[Tuple[str, str], List[_PendingSignal]] = {}

    def record_signal(self, signal: Any) -> None:
        """Record a signal from a channel evaluation."""
        key = (signal.symbol, signal.direction.value if hasattr(signal.direction, "value") else str(signal.direction))
        pending = _PendingSignal(
            channel=signal.channel,
            confidence=signal.confidence,
            signal=signal,
            timestamp=time.monotonic(),
        )
        self._recent_signals.setdefault(key, []).append(pending)

    def check_confluence(
        self, symbol: str, direction: str
    ) -> Optional[ConfluenceResult]:
        """Return a ConfluenceResult if enough strategies agree, else None."""
        key = (symbol, direction)
        entries = self._recent_signals.get(key)
        if not entries:
            return None

        # Prune expired entries
        cutoff = time.monotonic() - self.window_seconds
        entries[:] = [e for e in entries if e.timestamp >= cutoff]
        if not entries:
            self._recent_signals.pop(key, None)
            return None

        if len(entries) < self.min_strategies:
            return None

        # Pick highest-confidence signal
        best = max(entries, key=lambda e: e.confidence)
        count = len(entries)
        if count == 2:
            boost = 5.0
        elif count == 3:
            boost = 8.0
        else:
            boost = 12.0

        return ConfluenceResult(
            best_signal=best.signal,
            contributing_channels=[e.channel for e in entries],
            confluence_boost=boost,
            strategy_count=count,
        )

    def flush_symbol(self, symbol: str, direction: str) -> None:
        """Clear pending signals after confluence is consumed."""
        self._recent_signals.pop((symbol, direction), None)
