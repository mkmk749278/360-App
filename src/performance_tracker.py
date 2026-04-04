"""Performance Tracker – records and analyses completed signal outcomes.

Persists data to ``data/signal_performance.json`` and exposes per-channel
stats with rolling 7-day and 30-day windows.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.performance_metrics import (
    calculate_drawdown_metrics,
    classify_trade_outcome,
    is_breakeven_pnl,
    normalize_pnl_pct,
)
from src.utils import get_logger

log = get_logger("performance_tracker")

_DEFAULT_STORAGE_PATH = "data/signal_performance.json"


@dataclass
class SignalRecord:
    """A single completed signal record."""

    signal_id: str
    channel: str
    symbol: str
    direction: str
    entry: float
    hit_tp: int        # 0 = none, 1 = TP1, 2 = TP2, 3 = TP3
    hit_sl: bool
    pnl_pct: float
    confidence: float
    outcome_label: str = ""
    pre_ai_confidence: float = 0.0
    post_ai_confidence: float = 0.0
    setup_class: str = ""
    market_phase: str = ""
    quality_tier: str = ""
    spread_pct: float = 0.0
    volume_24h_usd: float = 0.0
    hold_duration_sec: float = 0.0
    max_favorable_excursion_pct: float = 0.0
    max_adverse_excursion_pct: float = 0.0
    timestamp: float = field(default_factory=time.time)
    signal_quality_pnl_pct: float = 0.0   # TP-based PnL for signal quality stats
    signal_quality_hit_tp: int = 0         # highest TP reached (for signal quality classification)
    session_name: str = ""                 # Trading session label  (Rec 12)


@dataclass
class ChannelStats:
    """Aggregated statistics for a channel."""

    channel: str
    win_count: int = 0
    loss_count: int = 0
    breakeven_count: int = 0
    win_rate: float = 0.0
    avg_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    total_signals: int = 0


class PerformanceTracker:
    """Records completed signal outcomes and computes performance statistics.

    Parameters
    ----------
    storage_path:
        Path to the JSON file used for persistence.
    """

    def __init__(self, storage_path: str = _DEFAULT_STORAGE_PATH) -> None:
        self._path = Path(storage_path)
        self._records: List[SignalRecord] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        signal_id: str,
        channel: str,
        symbol: str,
        direction: str,
        entry: float,
        hit_tp: int,
        hit_sl: bool,
        pnl_pct: float,
        outcome_label: str = "",
        confidence: float = 0.0,
        pre_ai_confidence: float = 0.0,
        post_ai_confidence: float = 0.0,
        setup_class: str = "",
        market_phase: str = "",
        quality_tier: str = "",
        spread_pct: float = 0.0,
        volume_24h_usd: float = 0.0,
        hold_duration_sec: float = 0.0,
        max_favorable_excursion_pct: float = 0.0,
        max_adverse_excursion_pct: float = 0.0,
        signal_quality_pnl_pct: Optional[float] = None,
        signal_quality_hit_tp: Optional[int] = None,
        session_name: str = "",
    ) -> None:
        """Record the outcome of a completed signal."""
        # Default signal quality fields to the actual PnL values when not provided
        sq_pnl = signal_quality_pnl_pct if signal_quality_pnl_pct is not None else pnl_pct
        sq_hit_tp = signal_quality_hit_tp if signal_quality_hit_tp is not None else hit_tp
        record = SignalRecord(
            signal_id=signal_id,
            channel=channel,
            symbol=symbol,
            direction=direction,
            entry=entry,
            hit_tp=hit_tp,
            hit_sl=hit_sl,
            pnl_pct=normalize_pnl_pct(pnl_pct),
            outcome_label=(
                outcome_label
                or classify_trade_outcome(pnl_pct=pnl_pct, hit_tp=hit_tp, hit_sl=hit_sl)
            ),
            confidence=confidence,
            pre_ai_confidence=pre_ai_confidence,
            post_ai_confidence=post_ai_confidence,
            setup_class=setup_class,
            market_phase=market_phase,
            quality_tier=quality_tier,
            spread_pct=spread_pct,
            volume_24h_usd=volume_24h_usd,
            hold_duration_sec=hold_duration_sec,
            max_favorable_excursion_pct=max_favorable_excursion_pct,
            max_adverse_excursion_pct=max_adverse_excursion_pct,
            signal_quality_pnl_pct=normalize_pnl_pct(sq_pnl),
            signal_quality_hit_tp=sq_hit_tp,
            session_name=session_name,
        )
        self._records.append(record)
        self._save()
        log.debug(
            "Recorded outcome for %s: pnl=%.2f%% hit_sl=%s",
            signal_id,
            pnl_pct,
            hit_sl,
        )

    def get_stats(
        self,
        channel: Optional[str] = None,
        window_days: Optional[int] = None,
    ) -> ChannelStats:
        """Compute stats for a channel (or all channels if channel is None).

        Parameters
        ----------
        channel:
            Filter to a specific channel name.  Pass ``None`` for global stats.
        window_days:
            Rolling window in days.  Pass ``None`` for all-time stats.
        """
        records = self._filter(channel=channel, window_days=window_days)
        return self._compute_stats(channel or "ALL", records)

    def get_channel_scoreboard(self, window_days: int = 7) -> Dict[str, Dict[str, Any]]:
        """Return per-channel win/loss/winrate/avg_pnl for the last N days.

        Parameters
        ----------
        window_days:
            Rolling window in days (default: 7).

        Returns
        -------
        dict mapping channel name → stats dict with keys:
            ``wins``, ``losses``, ``breakeven``, ``total_pnl``, ``count``,
            ``win_rate``, ``avg_pnl``.
        """
        cutoff = time.time() - (window_days * 86400)
        recent = [r for r in self._records if r.timestamp >= cutoff]

        scoreboard: Dict[str, Dict[str, Any]] = {}
        for r in recent:
            ch = r.channel
            if ch not in scoreboard:
                scoreboard[ch] = {
                    "wins": 0,
                    "losses": 0,
                    "breakeven": 0,
                    "total_pnl": 0.0,
                    "count": 0,
                }
            entry = scoreboard[ch]
            entry["count"] += 1
            entry["total_pnl"] += r.pnl_pct

            if r.hit_sl:
                entry["losses"] += 1
            elif r.hit_tp > 0:
                entry["wins"] += 1
            else:
                entry["breakeven"] += 1

        # Compute derived stats
        for ch, data in scoreboard.items():
            total = data["wins"] + data["losses"]
            data["win_rate"] = round(data["wins"] / total * 100, 1) if total > 0 else 0.0
            data["avg_pnl"] = round(data["total_pnl"] / data["count"], 2) if data["count"] > 0 else 0.0

        return scoreboard

    def format_stats_message(
        self,
        channel: Optional[str] = None,
        window_days: Optional[int] = None,
    ) -> str:
        """Return a Telegram-ready account PnL performance summary.

        Parameters
        ----------
        channel:
            Optional channel name filter.
        window_days:
            Optional rolling window (7 or 30 days).
        """
        label = channel or "All Channels"
        window_label = f" (last {window_days}d)" if window_days else " (all time)"
        stats = self.get_stats(channel=channel, window_days=window_days)

        return (
            f"📊 *Account PnL Stats – {label}{window_label}*\n"
            f"Total signals: {stats.total_signals}\n"
            f"Wins: {stats.win_count} | Losses: {stats.loss_count} | "
            f"Breakeven: {stats.breakeven_count}\n"
            f"Win rate: {stats.win_rate:.1f}%\n"
            f"Avg PnL: {stats.avg_pnl_pct:+.2f}%\n"
            f"Best trade: {stats.best_trade:+.2f}%\n"
            f"Worst trade: {stats.worst_trade:+.2f}%\n"
            f"Max drawdown: {stats.max_drawdown:.2f}%"
        )

    def format_signal_quality_stats_message(
        self,
        channel: Optional[str] = None,
        window_days: Optional[int] = None,
    ) -> str:
        """Return a Telegram-ready signal quality (TP-based PnL) summary.

        Parameters
        ----------
        channel:
            Optional channel name filter.
        window_days:
            Optional rolling window (7 or 30 days).
        """
        label = channel or "All Channels"
        window_label = f" (last {window_days}d)" if window_days else " (all time)"
        records = self._filter(channel=channel, window_days=window_days)
        stats = self._compute_signal_quality_stats(channel or "ALL", records)

        return (
            f"🎯 *Signal Quality Stats – {label}{window_label}*\n"
            f"Total signals: {stats.total_signals}\n"
            f"Wins: {stats.win_count} | Losses: {stats.loss_count} | "
            f"Breakeven: {stats.breakeven_count}\n"
            f"Win rate: {stats.win_rate:.1f}%\n"
            f"Avg PnL: {stats.avg_pnl_pct:+.2f}%\n"
            f"Best trade: {stats.best_trade:+.2f}%\n"
            f"Worst trade: {stats.worst_trade:+.2f}%\n"
            f"Max drawdown: {stats.max_drawdown:.2f}%"
        )

    def get_top_trades(self, n: int = 3, window_days: int = 1) -> List[SignalRecord]:
        """Return the top *n* completed trades by signal-quality PnL within *window_days*.

        Only winning trades (positive PnL) are included, sorted descending by
        ``signal_quality_pnl_pct``.
        """
        records = self._filter(window_days=window_days)
        winners = [r for r in records if r.pnl_pct > 0]
        winners.sort(key=lambda r: r.signal_quality_pnl_pct, reverse=True)
        return winners[:n]

    def get_daily_summary(self, window_days: int = 1) -> Dict[str, Any]:
        """Return a summary dict suitable for the daily performance recap.

        Parameters
        ----------
        window_days:
            Rolling window in days (default: 1 = today).

        Returns
        -------
        dict with keys:
            ``total``, ``wins``, ``losses``, ``breakeven``,
            ``win_rate``, ``avg_pnl``, ``best_trade``, ``top_trades``.
        """
        records = self._filter(window_days=window_days)
        if not records:
            return {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "best_trade": None,
                "top_trades": [],
            }

        wins = sum(
            1 for r in records if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct)
        )
        losses = sum(
            1 for r in records if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct)
        )
        breakeven = sum(1 for r in records if is_breakeven_pnl(r.pnl_pct))
        total_decisive = wins + losses
        win_rate = (wins / total_decisive * 100.0) if total_decisive > 0 else 0.0
        avg_pnl = sum(r.pnl_pct for r in records) / len(records)

        top = self.get_top_trades(n=3, window_days=window_days)
        best = top[0] if top else None

        return {
            "total": len(records),
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "best_trade": best,
            "top_trades": top,
        }

    def reset_stats(self, channel: Optional[str] = None) -> int:
        """Clear all performance records, or only records for a specific channel.

        Parameters
        ----------
        channel:
            If provided, only clear records for this channel. If None, clear all records.

        Returns
        -------
        int
            Number of records that were cleared.
        """
        if channel:
            before = len(self._records)
            self._records = [r for r in self._records if r.channel != channel]
            cleared = before - len(self._records)
        else:
            cleared = len(self._records)
            self._records = []
        self._save()
        log.info("Performance stats reset: cleared %d records (channel=%s)", cleared, channel or "ALL")
        return cleared

    def all_channel_stats(self, window_days: Optional[int] = None) -> Dict[str, ChannelStats]:
        """Return a dict of channel → ChannelStats."""
        channels = {r.channel for r in self._records}
        result: Dict[str, ChannelStats] = {}
        for ch in channels:
            result[ch] = self.get_stats(channel=ch, window_days=window_days)
        return result

    def get_tp_stats(
        self,
        channel: Optional[str] = None,
        window_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Compute partial-TP hit rates and weighted PnL.

        Tracks how often each TP level (TP1/TP2/TP3) was reached, along with
        the average PnL contribution from each partial exit.

        Parameters
        ----------
        channel:
            Optional channel name filter.
        window_days:
            Optional rolling window in days.

        Returns
        -------
        dict with keys:
            ``total``, ``tp1_hits``, ``tp2_hits``, ``tp3_hits``,
            ``tp1_rate``, ``tp2_rate``, ``tp3_rate``,
            ``avg_pnl_at_tp1``, ``avg_pnl_at_tp2``, ``avg_pnl_at_tp3``,
            ``sl_hits``, ``sl_rate``.
        """
        records = self._filter(channel=channel, window_days=window_days)
        total = len(records)
        if total == 0:
            return {
                "total": 0,
                "tp1_hits": 0, "tp2_hits": 0, "tp3_hits": 0,
                "tp1_rate": 0.0, "tp2_rate": 0.0, "tp3_rate": 0.0,
                "avg_pnl_at_tp1": 0.0, "avg_pnl_at_tp2": 0.0, "avg_pnl_at_tp3": 0.0,
                "sl_hits": 0, "sl_rate": 0.0,
            }

        tp1_pnls: List[float] = []
        tp2_pnls: List[float] = []
        tp3_pnls: List[float] = []
        sl_hits = 0

        for r in records:
            hit = r.hit_tp
            pnl = r.signal_quality_pnl_pct  # TP-based PnL for signal quality
            if r.hit_sl:
                sl_hits += 1
            if hit >= 1:
                tp1_pnls.append(pnl)
            if hit >= 2:
                tp2_pnls.append(pnl)
            if hit >= 3:
                tp3_pnls.append(pnl)

        def _avg(pnls: List[float]) -> float:
            return round(sum(pnls) / len(pnls), 4) if pnls else 0.0

        return {
            "total": total,
            "tp1_hits": len(tp1_pnls),
            "tp2_hits": len(tp2_pnls),
            "tp3_hits": len(tp3_pnls),
            "tp1_rate": round(len(tp1_pnls) / total * 100.0, 1),
            "tp2_rate": round(len(tp2_pnls) / total * 100.0, 1),
            "tp3_rate": round(len(tp3_pnls) / total * 100.0, 1),
            "avg_pnl_at_tp1": _avg(tp1_pnls),
            "avg_pnl_at_tp2": _avg(tp2_pnls),
            "avg_pnl_at_tp3": _avg(tp3_pnls),
            "sl_hits": sl_hits,
            "sl_rate": round(sl_hits / total * 100.0, 1),
        }

    def format_tp_stats_message(
        self,
        channel: Optional[str] = None,
        window_days: Optional[int] = None,
    ) -> str:
        """Return a Telegram-ready TP hit-rate and partial-exit PnL summary.

        Parameters
        ----------
        channel:
            Optional channel name filter.
        window_days:
            Optional rolling window in days.
        """
        label = channel or "All Channels"
        window_label = f" (last {window_days}d)" if window_days else " (all time)"
        tp = self.get_tp_stats(channel=channel, window_days=window_days)

        if tp["total"] == 0:
            return f"📈 *TP Stats – {label}{window_label}*\nNo data yet."

        return (
            f"📈 *TP Stats – {label}{window_label}*\n"
            f"Total signals: {tp['total']}\n"
            f"TP1 hit: {tp['tp1_hits']} ({tp['tp1_rate']:.1f}%) | avg PnL: {tp['avg_pnl_at_tp1']:+.2f}%\n"
            f"TP2 hit: {tp['tp2_hits']} ({tp['tp2_rate']:.1f}%) | avg PnL: {tp['avg_pnl_at_tp2']:+.2f}%\n"
            f"TP3 hit: {tp['tp3_hits']} ({tp['tp3_rate']:.1f}%) | avg PnL: {tp['avg_pnl_at_tp3']:+.2f}%\n"
            f"SL hit: {tp['sl_hits']} ({tp['sl_rate']:.1f}%)"
        )

    # ------------------------------------------------------------------
    # Per-pair, per-regime, per-session analytics  (Rec 5, 12, 13)
    # ------------------------------------------------------------------

    def get_pair_stats(
        self,
        symbol: str,
        window_days: Optional[int] = None,
    ) -> ChannelStats:
        """Compute per-pair stats, optionally within a rolling window.

        Parameters
        ----------
        symbol:
            The trading pair symbol (e.g. ``"BTCUSDT"``).
        window_days:
            Optional rolling window in days.
        """
        records = self._filter(window_days=window_days)
        filtered = [r for r in records if r.symbol == symbol]
        return self._compute_stats(symbol, filtered)

    def get_pair_scoreboard(
        self,
        window_days: int = 7,
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-pair win/loss/winrate/avg_pnl for the last N days.

        Returns
        -------
        dict mapping symbol → stats dict with keys:
            ``wins``, ``losses``, ``breakeven``, ``total_pnl``, ``count``,
            ``win_rate``, ``avg_pnl``, ``max_drawdown``.
        """
        cutoff = time.time() - (window_days * 86400)
        recent = [r for r in self._records if r.timestamp >= cutoff]

        scoreboard: Dict[str, Dict[str, Any]] = {}
        for r in recent:
            sym = r.symbol
            if sym not in scoreboard:
                scoreboard[sym] = {
                    "wins": 0, "losses": 0, "breakeven": 0,
                    "total_pnl": 0.0, "count": 0, "pnls": [],
                }
            entry = scoreboard[sym]
            entry["count"] += 1
            entry["total_pnl"] += r.pnl_pct
            entry["pnls"].append(r.pnl_pct)

            if r.hit_sl:
                entry["losses"] += 1
            elif r.hit_tp > 0:
                entry["wins"] += 1
            else:
                entry["breakeven"] += 1

        for sym, data in scoreboard.items():
            total = data["wins"] + data["losses"]
            data["win_rate"] = round(data["wins"] / total * 100, 1) if total > 0 else 0.0
            data["avg_pnl"] = round(data["total_pnl"] / data["count"], 2) if data["count"] > 0 else 0.0
            _, data["max_drawdown"] = calculate_drawdown_metrics(data.pop("pnls"))

        return scoreboard

    def get_pair_rr(
        self,
        symbol: str,
        window_days: Optional[int] = None,
    ) -> float:
        """Return the average risk/reward ratio for a specific pair.

        R:R is computed as ``abs(avg_win) / abs(avg_loss)``.  Returns 0.0
        when there are insufficient trades.
        """
        records = self._filter(window_days=window_days)
        filtered = [r for r in records if r.symbol == symbol]
        wins = [r.pnl_pct for r in filtered if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct)]
        losses = [r.pnl_pct for r in filtered if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct)]
        if not wins or not losses:
            return 0.0
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))
        return round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    def get_stats_by_regime(
        self,
        window_days: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return performance stats grouped by market regime (market_phase).

        Returns
        -------
        dict mapping regime label → stats dict with keys:
            ``wins``, ``losses``, ``count``, ``win_rate``, ``avg_pnl``.
        """
        records = self._filter(window_days=window_days)
        by_regime: Dict[str, List[SignalRecord]] = {}
        for r in records:
            phase = r.market_phase or "UNKNOWN"
            by_regime.setdefault(phase, []).append(r)

        result: Dict[str, Dict[str, Any]] = {}
        for regime, recs in by_regime.items():
            wins = sum(1 for r in recs if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct))
            losses = sum(1 for r in recs if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct))
            total = wins + losses
            result[regime] = {
                "wins": wins,
                "losses": losses,
                "count": len(recs),
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
                "avg_pnl": round(sum(r.pnl_pct for r in recs) / len(recs), 2) if recs else 0.0,
            }
        return result

    def get_stats_by_session(
        self,
        window_days: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return performance stats grouped by trading session name.

        Returns
        -------
        dict mapping session name → stats dict with keys:
            ``wins``, ``losses``, ``count``, ``win_rate``, ``avg_pnl``.
        """
        records = self._filter(window_days=window_days)
        by_session: Dict[str, List[SignalRecord]] = {}
        for r in records:
            session = r.session_name or "UNKNOWN"
            by_session.setdefault(session, []).append(r)

        result: Dict[str, Dict[str, Any]] = {}
        for session, recs in by_session.items():
            wins = sum(1 for r in recs if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct))
            losses = sum(1 for r in recs if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct))
            total = wins + losses
            result[session] = {
                "wins": wins,
                "losses": losses,
                "count": len(recs),
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
                "avg_pnl": round(sum(r.pnl_pct for r in recs) / len(recs), 2) if recs else 0.0,
            }
        return result

    # ------------------------------------------------------------------
    # Per-pair regime / session / weekday / consistency  (pair analysis)
    # ------------------------------------------------------------------

    def get_pair_stats_by_regime(
        self,
        symbol: str,
        window_days: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-pair stats grouped by market regime.

        Parameters
        ----------
        symbol:
            Trading pair symbol (e.g. ``"BTCUSDT"``).
        window_days:
            Optional rolling window in days.

        Returns
        -------
        dict mapping regime label → stats dict with keys:
            ``wins``, ``losses``, ``count``, ``win_rate``, ``avg_pnl``.
        """
        records = self._filter(window_days=window_days)
        filtered = [r for r in records if r.symbol == symbol]
        by_regime: Dict[str, List[SignalRecord]] = {}
        for r in filtered:
            phase = r.market_phase or "UNKNOWN"
            by_regime.setdefault(phase, []).append(r)

        result: Dict[str, Dict[str, Any]] = {}
        for regime, recs in by_regime.items():
            wins = sum(1 for r in recs if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct))
            losses = sum(1 for r in recs if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct))
            total = wins + losses
            result[regime] = {
                "wins": wins,
                "losses": losses,
                "count": len(recs),
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
                "avg_pnl": round(sum(r.pnl_pct for r in recs) / len(recs), 2) if recs else 0.0,
            }
        return result

    def get_pair_stats_by_session(
        self,
        symbol: str,
        window_days: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-pair stats grouped by trading session.

        Parameters
        ----------
        symbol:
            Trading pair symbol.
        window_days:
            Optional rolling window in days.

        Returns
        -------
        dict mapping session name → stats dict.
        """
        records = self._filter(window_days=window_days)
        filtered = [r for r in records if r.symbol == symbol]
        by_session: Dict[str, List[SignalRecord]] = {}
        for r in filtered:
            session = r.session_name or "UNKNOWN"
            by_session.setdefault(session, []).append(r)

        result: Dict[str, Dict[str, Any]] = {}
        for session, recs in by_session.items():
            wins = sum(1 for r in recs if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct))
            losses = sum(1 for r in recs if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct))
            total = wins + losses
            result[session] = {
                "wins": wins,
                "losses": losses,
                "count": len(recs),
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
                "avg_pnl": round(sum(r.pnl_pct for r in recs) / len(recs), 2) if recs else 0.0,
            }
        return result

    def get_pair_stats_by_weekday(
        self,
        symbol: str,
        window_days: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-pair stats grouped by weekday (Mon=0 … Sun=6).

        Parameters
        ----------
        symbol:
            Trading pair symbol.
        window_days:
            Optional rolling window in days.

        Returns
        -------
        dict mapping day name → stats dict with ``wins``, ``losses``,
        ``count``, ``win_rate``, ``avg_pnl``, ``is_weekend``.
        """
        import datetime as _dt

        _DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        records = self._filter(window_days=window_days)
        filtered = [r for r in records if r.symbol == symbol]
        by_day: Dict[str, List[SignalRecord]] = {}
        for r in filtered:
            day_idx = _dt.datetime.fromtimestamp(r.timestamp, tz=_dt.timezone.utc).weekday()
            day_name = _DAY_NAMES[day_idx]
            by_day.setdefault(day_name, []).append(r)

        result: Dict[str, Dict[str, Any]] = {}
        for day_name, recs in by_day.items():
            wins = sum(1 for r in recs if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct))
            losses = sum(1 for r in recs if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct))
            total = wins + losses
            result[day_name] = {
                "wins": wins,
                "losses": losses,
                "count": len(recs),
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
                "avg_pnl": round(sum(r.pnl_pct for r in recs) / len(recs), 2) if recs else 0.0,
                "is_weekend": day_name in ("Sat", "Sun"),
            }
        return result

    def get_pair_consistency(
        self,
        symbol: str,
        window_days: int = 30,
        chunk_size: int = 7,
    ) -> Dict[str, Any]:
        """Evaluate signal consistency over rolling weekly chunks.

        Parameters
        ----------
        symbol:
            Trading pair symbol.
        window_days:
            Total lookback period in days.
        chunk_size:
            Number of days per chunk for consistency scoring.

        Returns
        -------
        dict with ``chunks`` (list of per-chunk win rates), ``avg_wr``,
        ``std_wr``, ``trend`` (IMPROVING/DEGRADING/STABLE),
        ``is_consistent`` (bool).
        """
        import math as _math

        records = self._filter(window_days=window_days)
        filtered = sorted(
            (r for r in records if r.symbol == symbol),
            key=lambda r: r.timestamp,
        )
        if not filtered:
            return {
                "chunks": [],
                "avg_wr": 0.0,
                "std_wr": 0.0,
                "trend": "STABLE",
                "is_consistent": True,
            }

        chunk_seconds = chunk_size * 86_400.0
        start_ts = filtered[0].timestamp
        chunks: list[float] = []

        chunk_start = start_ts
        while chunk_start < filtered[-1].timestamp + 1:
            chunk_end = chunk_start + chunk_seconds
            chunk_recs = [r for r in filtered if chunk_start <= r.timestamp < chunk_end]
            if chunk_recs:
                wins = sum(
                    1 for r in chunk_recs
                    if r.pnl_pct > 0 and not is_breakeven_pnl(r.pnl_pct)
                )
                losses = sum(
                    1 for r in chunk_recs
                    if r.pnl_pct < 0 and not is_breakeven_pnl(r.pnl_pct)
                )
                total = wins + losses
                wr = round(wins / total * 100, 1) if total > 0 else 50.0
                chunks.append(wr)
            chunk_start = chunk_end

        if not chunks:
            return {
                "chunks": [],
                "avg_wr": 0.0,
                "std_wr": 0.0,
                "trend": "STABLE",
                "is_consistent": True,
            }

        avg_wr = sum(chunks) / len(chunks)
        variance = sum((c - avg_wr) ** 2 for c in chunks) / len(chunks) if len(chunks) > 1 else 0.0
        std_wr = _math.sqrt(variance)

        # Trend: compare first half avg vs second half avg
        if len(chunks) >= 2:
            mid = len(chunks) // 2
            first_half = sum(chunks[:mid]) / mid
            second_half = sum(chunks[mid:]) / len(chunks[mid:])
            diff = second_half - first_half
            if diff > 10:
                trend = "IMPROVING"
            elif diff < -10:
                trend = "DEGRADING"
            else:
                trend = "STABLE"
        else:
            trend = "STABLE"

        is_consistent = std_wr < 15.0 and all(c >= 30.0 for c in chunks)

        return {
            "chunks": chunks,
            "avg_wr": round(avg_wr, 1),
            "std_wr": round(std_wr, 1),
            "trend": trend,
            "is_consistent": is_consistent,
        }

    def get_pair_pnl_list(
        self,
        symbol: str,
        window_days: Optional[int] = None,
    ) -> List[float]:
        """Return chronologically ordered PnL percentages for a pair."""
        records = self._filter(window_days=window_days)
        filtered = sorted(
            (r for r in records if r.symbol == symbol),
            key=lambda r: r.timestamp,
        )
        return [r.pnl_pct for r in filtered]

    def get_pair_mfe_mae(
        self,
        symbol: str,
        window_days: Optional[int] = None,
    ) -> Dict[str, List[float]]:
        """Return MFE and MAE lists for a pair."""
        records = self._filter(window_days=window_days)
        filtered = [r for r in records if r.symbol == symbol]
        return {
            "mfe": [r.max_favorable_excursion_pct for r in filtered],
            "mae": [r.max_adverse_excursion_pct for r in filtered],
        }

    def get_all_traded_symbols(
        self,
        window_days: Optional[int] = None,
    ) -> List[str]:
        """Return a deduplicated list of all symbols with recorded outcomes."""
        records = self._filter(window_days=window_days)
        return list(dict.fromkeys(r.symbol for r in records))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _filter(
        self,
        channel: Optional[str] = None,
        window_days: Optional[int] = None,
    ) -> List[SignalRecord]:
        """Return records filtered by channel and/or time window."""
        records = self._records
        if channel:
            records = [r for r in records if r.channel == channel]
        if window_days:
            cutoff = time.time() - window_days * 86_400.0
            records = [r for r in records if r.timestamp >= cutoff]
        return records

    @staticmethod
    def _compute_stats(channel: str, records: List[SignalRecord]) -> ChannelStats:
        """Compute aggregate stats from a list of records."""
        stats = ChannelStats(channel=channel)
        if not records:
            return stats

        stats.total_signals = len(records)
        for record in records:
            if is_breakeven_pnl(record.pnl_pct):
                stats.breakeven_count += 1
            elif record.pnl_pct > 0:
                stats.win_count += 1
            else:
                stats.loss_count += 1
        total = stats.win_count + stats.loss_count
        stats.win_rate = (stats.win_count / total * 100.0) if total > 0 else 0.0

        pnls = [r.pnl_pct for r in records]
        stats.avg_pnl_pct = sum(pnls) / len(pnls) if pnls else 0.0
        stats.best_trade = max(pnls) if pnls else 0.0
        stats.worst_trade = min(pnls) if pnls else 0.0

        _, stats.max_drawdown = calculate_drawdown_metrics(pnls)

        return stats

    @staticmethod
    def _compute_signal_quality_stats(channel: str, records: List[SignalRecord]) -> ChannelStats:
        """Compute aggregate stats using signal quality (TP-based) PnL."""
        stats = ChannelStats(channel=channel)
        if not records:
            return stats

        stats.total_signals = len(records)
        for record in records:
            sq_pnl = record.signal_quality_pnl_pct
            if is_breakeven_pnl(sq_pnl):
                stats.breakeven_count += 1
            elif sq_pnl > 0:
                stats.win_count += 1
            else:
                stats.loss_count += 1
        total = stats.win_count + stats.loss_count
        stats.win_rate = (stats.win_count / total * 100.0) if total > 0 else 0.0

        pnls = [r.signal_quality_pnl_pct for r in records]
        stats.avg_pnl_pct = sum(pnls) / len(pnls) if pnls else 0.0
        stats.best_trade = max(pnls) if pnls else 0.0
        stats.worst_trade = min(pnls) if pnls else 0.0

        _, stats.max_drawdown = calculate_drawdown_metrics(pnls)

        return stats

    def _save(self) -> None:
        """Persist records to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(r) for r in self._records]
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            log.warning("Failed to save performance data: %s", exc)

    def _load(self) -> None:
        """Load records from disk if the file exists."""
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data: List[Dict[str, Any]] = json.load(fh)
            self._records = []
            for item in data:
                # Backward compatibility: old records without signal quality fields
                # default signal_quality_pnl_pct to pnl_pct and signal_quality_hit_tp to hit_tp
                if "signal_quality_pnl_pct" not in item:
                    item["signal_quality_pnl_pct"] = item.get("pnl_pct", 0.0)
                if "signal_quality_hit_tp" not in item:
                    item["signal_quality_hit_tp"] = item.get("hit_tp", 0)
                if "session_name" not in item:
                    item["session_name"] = ""
                self._records.append(SignalRecord(**item))
            for record in self._records:
                record.pnl_pct = normalize_pnl_pct(record.pnl_pct)
                record.signal_quality_pnl_pct = normalize_pnl_pct(record.signal_quality_pnl_pct)
                if not record.outcome_label:
                    record.outcome_label = classify_trade_outcome(
                        pnl_pct=record.pnl_pct,
                        hit_tp=record.hit_tp,
                        hit_sl=record.hit_sl,
                    )
            log.info("Loaded %d performance records from %s", len(self._records), self._path)
        except Exception as exc:
            log.warning("Failed to load performance data: %s", exc)
