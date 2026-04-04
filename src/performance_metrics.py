"""Shared PnL, drawdown, and outcome classification helpers."""

from __future__ import annotations

import math
from typing import Iterable, List, Tuple

_MIN_PNL_PCT = -99.99
_BREAKEVEN_PNL_THRESHOLD_PCT = 0.01


def normalize_pnl_pct(pnl_pct: float) -> float:
    """Clamp realized PnL to a sane lower bound."""
    return max(float(pnl_pct), _MIN_PNL_PCT)


def is_breakeven_pnl(pnl_pct: float) -> bool:
    """Return True when realized PnL is close enough to treat as breakeven."""
    return abs(normalize_pnl_pct(pnl_pct)) < _BREAKEVEN_PNL_THRESHOLD_PCT


def classify_trade_outcome(pnl_pct: float, hit_tp: int = 0, hit_sl: bool = False) -> str:
    """Classify the final realized trade outcome.

    The classification is semantic rather than purely mechanical:
    - stop exits with negative realized PnL remain ``SL_HIT``
    - stop exits around flat are ``BREAKEVEN_EXIT``
    - stop exits with positive realized PnL become ``PROFIT_LOCKED``
    - a final TP completion is ``FULL_TP_HIT``
    - exits that are neither stop nor TP completions fall back to ``CLOSED``
    """
    normalized_pnl = normalize_pnl_pct(pnl_pct)
    if hit_tp >= 3 and not hit_sl:
        return "FULL_TP_HIT"
    if hit_sl:
        if is_breakeven_pnl(normalized_pnl):
            return "BREAKEVEN_EXIT"
        if normalized_pnl < 0.0:
            return "SL_HIT"
        return "PROFIT_LOCKED"
    if hit_tp > 0:
        return f"TP{hit_tp}_HIT"
    return "CLOSED"


def calculate_trade_pnl_pct(entry_price: float, exit_price: float, direction: str) -> float:
    """Calculate realized PnL % for a long or short trade."""
    if entry_price <= 0 or exit_price <= 0:
        return 0.0

    direction_name = direction.upper()
    if direction_name == "SHORT":
        pnl_pct = (entry_price - exit_price) / entry_price * 100.0
    else:
        pnl_pct = (exit_price - entry_price) / entry_price * 100.0
    return normalize_pnl_pct(pnl_pct)


def calculate_drawdown_metrics(pnl_pcts: Iterable[float]) -> Tuple[float, float]:
    """Return current and maximum drawdown (%) from a compounded equity curve."""
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0

    for pnl_pct in pnl_pcts:
        equity *= max(0.0, 1.0 + normalize_pnl_pct(pnl_pct) / 100.0)
        if equity > peak:
            peak = equity
        drawdown = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    current_drawdown = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
    return current_drawdown, max_drawdown


# ---------------------------------------------------------------------------
# Extended performance metrics  (Rec 15)
# ---------------------------------------------------------------------------


def risk_reward_ratio(pnl_pcts: List[float]) -> float:
    """Compute risk/reward ratio as ``avg_win / abs(avg_loss)``.

    Returns 0.0 when there are no wins or no losses.
    """
    wins = [p for p in pnl_pcts if p > 0 and not is_breakeven_pnl(p)]
    losses = [p for p in pnl_pcts if p < 0 and not is_breakeven_pnl(p)]
    if not wins or not losses:
        return 0.0
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    return round(avg_win / avg_loss, 4) if avg_loss > 0 else 0.0


def profit_factor(pnl_pcts: List[float]) -> float:
    """Compute profit factor as ``sum(wins) / abs(sum(losses))``.

    Returns 0.0 when there are no losses.
    """
    gross_profit = sum(p for p in pnl_pcts if p > 0)
    gross_loss = abs(sum(p for p in pnl_pcts if p < 0))
    if gross_loss == 0:
        return 0.0
    return round(gross_profit / gross_loss, 4)


def expectancy(pnl_pcts: List[float]) -> float:
    """Compute per-trade expectancy (average PnL per trade).

    Returns 0.0 when there are no trades.
    """
    if not pnl_pcts:
        return 0.0
    return round(sum(pnl_pcts) / len(pnl_pcts), 4)


def sharpe_ratio(pnl_pcts: List[float], risk_free_rate: float = 0.0) -> float:
    """Compute annualised Sharpe ratio from a list of per-trade PnL percentages.

    Uses a simple approximation: ``mean(excess) / std(pnl) * sqrt(N)``
    where *N* is the number of trades as an annualisation factor proxy.
    Returns 0.0 when standard deviation is zero or fewer than 2 trades.
    """
    if len(pnl_pcts) < 2:
        return 0.0
    mean_pnl = sum(pnl_pcts) / len(pnl_pcts)
    excess = mean_pnl - risk_free_rate
    variance = sum((p - mean_pnl) ** 2 for p in pnl_pcts) / (len(pnl_pcts) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return round(excess / std * math.sqrt(len(pnl_pcts)), 4)


def win_rate(pnl_pcts: List[float]) -> float:
    """Compute win rate as a percentage (0–100).

    Breakeven trades are excluded from the count.
    """
    wins = sum(1 for p in pnl_pcts if p > 0 and not is_breakeven_pnl(p))
    losses = sum(1 for p in pnl_pcts if p < 0 and not is_breakeven_pnl(p))
    total = wins + losses
    return round(wins / total * 100.0, 2) if total > 0 else 0.0


def mfe_mae_analysis(
    mfe_pcts: List[float],
    mae_pcts: List[float],
) -> dict:
    """Compute average and max MFE/MAE from parallel lists.

    Parameters
    ----------
    mfe_pcts:
        Max favorable excursion percentages per trade.
    mae_pcts:
        Max adverse excursion percentages per trade.

    Returns
    -------
    dict with ``avg_mfe``, ``max_mfe``, ``avg_mae``, ``max_mae``.
    """
    return {
        "avg_mfe": round(sum(mfe_pcts) / len(mfe_pcts), 4) if mfe_pcts else 0.0,
        "max_mfe": round(max(mfe_pcts), 4) if mfe_pcts else 0.0,
        "avg_mae": round(sum(mae_pcts) / len(mae_pcts), 4) if mae_pcts else 0.0,
        "max_mae": round(max(mae_pcts), 4) if mae_pcts else 0.0,
    }
