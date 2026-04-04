"""360_SCALP_ORDERBLOCK – SMC Order Block Entry Scalp ⚡

Trigger : Price retests an identified order block (supply/demand zone).
Logic   : Price returns to bullish order block (last bearish candle before impulsive move up) → LONG
          Price returns to bearish order block (last bullish candle before impulsive move down) → SHORT
Filters : Order block must be "fresh" (not previously tested), volume, spread
Risk    : SL beyond order block boundary, TP based on impulse size
Signal ID prefix: "SORB-"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from config import CHANNEL_SCALP_ORDERBLOCK
from src.channels.base import BaseChannel, Signal, build_channel_signal
from src.filters import check_rsi
from src.indicators import atr as compute_atr
from src.smc import Direction
from src.utils import get_logger

log = get_logger("scalp_orderblock")

# Lookback window for order block scanning.
_OB_LOOKBACK: int = 50

# An impulsive candle's body must be at least this fraction of its range.
_IMPULSE_BODY_RATIO: float = 0.60

# Impulse range must be at least this multiple of ATR.
_IMPULSE_ATR_MULT: float = 1.5


@dataclass
class _OrderBlock:
    """Internal representation of a detected order block."""

    direction: str  # "BULLISH" or "BEARISH"
    ob_high: float  # top of the OB candle
    ob_low: float   # bottom of the OB candle
    ob_index: int   # index within the lookback window
    impulse_size: float  # absolute size of the impulse move
    touched: bool = False  # True if price has already retested this OB


def _detect_order_blocks(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    atr_arr: np.ndarray,
) -> List[_OrderBlock]:
    """Scan candle data for order blocks.

    A bullish OB is the last bearish candle before a bullish impulse.
    A bearish OB is the last bullish candle before a bearish impulse.
    """
    n = len(closes)
    blocks: List[_OrderBlock] = []

    for i in range(1, n - 1):
        rng = highs[i] - lows[i]
        if rng <= 0:
            continue

        atr_val = float(atr_arr[i]) if i < len(atr_arr) and not np.isnan(atr_arr[i]) else None
        if atr_val is None or atr_val <= 0:
            continue

        body = abs(closes[i] - opens[i])

        # Check if candle i is impulsive
        if body / rng < _IMPULSE_BODY_RATIO:
            continue
        if rng < atr_val * _IMPULSE_ATR_MULT:
            continue

        # Bullish impulse (close > open): OB = previous bearish candle
        if closes[i] > opens[i]:
            # Look at previous candle – must be bearish
            if i > 0 and closes[i - 1] < opens[i - 1]:
                ob = _OrderBlock(
                    direction="BULLISH",
                    ob_high=highs[i - 1],
                    ob_low=lows[i - 1],
                    ob_index=i - 1,
                    impulse_size=closes[i] - opens[i],
                )
                blocks.append(ob)

        # Bearish impulse (close < open): OB = previous bullish candle
        elif closes[i] < opens[i]:
            if i > 0 and closes[i - 1] > opens[i - 1]:
                ob = _OrderBlock(
                    direction="BEARISH",
                    ob_high=highs[i - 1],
                    ob_low=lows[i - 1],
                    ob_index=i - 1,
                    impulse_size=opens[i] - closes[i],
                )
                blocks.append(ob)

    return blocks


def _mark_touched(
    blocks: List[_OrderBlock],
    closes: List[float],
    highs: List[float],
    lows: List[float],
) -> None:
    """Mark order blocks that have been previously touched (no longer fresh)."""
    n = len(closes)
    for ob in blocks:
        # Check candles between OB formation and the second-to-last bar
        for j in range(ob.ob_index + 2, n - 1):
            if ob.direction == "BULLISH":
                # Price dipped into OB range
                if lows[j] <= ob.ob_high and closes[j] >= ob.ob_low:
                    ob.touched = True
                    break
            else:
                # Price rose into OB range
                if highs[j] >= ob.ob_low and closes[j] <= ob.ob_high:
                    ob.touched = True
                    break


class ScalpOrderblockChannel(BaseChannel):
    """SMC Order Block Entry scalp trigger."""

    def __init__(self) -> None:
        super().__init__(CHANNEL_SCALP_ORDERBLOCK)

    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        candles: Dict[str, dict],
        indicators: Dict[str, dict],
        smc_data: dict,
        spread_pct: float,
        volume_24h_usd: float,
        regime: str = "",
    ) -> Optional[Signal]:
        m5 = candles.get("5m")
        if m5 is None or len(m5.get("close", [])) < _OB_LOOKBACK:
            return None

        _pair_profile = smc_data.get("pair_profile")
        if not self._pass_basic_filters(spread_pct, volume_24h_usd):
            return None

        ind = indicators.get("5m", {})
        thresholds = self._get_pair_adjusted_thresholds(_pair_profile)

        opens = [float(v) for v in list(m5.get("open", []))[-_OB_LOOKBACK:]]
        highs = [float(v) for v in list(m5.get("high", []))[-_OB_LOOKBACK:]]
        lows = [float(v) for v in list(m5.get("low", []))[-_OB_LOOKBACK:]]
        closes = [float(v) for v in list(m5.get("close", []))[-_OB_LOOKBACK:]]

        if len(opens) < _OB_LOOKBACK or len(closes) < _OB_LOOKBACK:
            return None

        close = closes[-1]

        # Compute ATR for impulse detection
        h_arr = np.array(highs, dtype=np.float64)
        l_arr = np.array(lows, dtype=np.float64)
        c_arr = np.array(closes, dtype=np.float64)
        atr_arr = compute_atr(h_arr, l_arr, c_arr)

        blocks = _detect_order_blocks(opens, highs, lows, closes, atr_arr)
        if not blocks:
            return None

        # Mark previously-touched OBs
        _mark_touched(blocks, closes, highs, lows)

        # Find the most recent fresh OB that price is currently retesting
        direction: Optional[Direction] = None
        best_ob: Optional[_OrderBlock] = None

        for ob in reversed(blocks):
            if ob.touched:
                continue

            if ob.direction == "BULLISH":
                # Price close within OB range → retest
                if ob.ob_low <= close <= ob.ob_high:
                    direction = Direction.LONG
                    best_ob = ob
                    break
            elif ob.direction == "BEARISH":
                if ob.ob_low <= close <= ob.ob_high:
                    direction = Direction.SHORT
                    best_ob = ob
                    break

        if direction is None or best_ob is None:
            return None

        # RSI extreme gate
        if not check_rsi(
            ind.get("rsi_last"),
            overbought=thresholds["rsi_ob"],
            oversold=thresholds["rsi_os"],
            direction=direction.value,
        ):
            return None

        # SL beyond the far edge of the order block
        atr_val = ind.get("atr_last")
        atr_for_sl = atr_val if (atr_val is not None and atr_val > 0) else close * 0.002

        if direction == Direction.LONG:
            sl = best_ob.ob_low - atr_for_sl * 0.2
            sl_dist = abs(close - sl)
        else:
            sl = best_ob.ob_high + atr_for_sl * 0.2
            sl_dist = abs(close - sl)

        # Ensure sl_dist isn't too tight (floor only — don't overwrite the
        # structural OB-boundary SL with a generic close±sl_dist value)
        min_sl_dist = close * self.config.sl_pct_range[0] / 100
        if sl_dist < min_sl_dist:
            sl_dist = min_sl_dist
            if direction == Direction.LONG:
                sl = close - sl_dist
            else:
                sl = close + sl_dist

        if direction == Direction.LONG:
            tp1 = close + sl_dist * self.config.tp_ratios[0]
            tp2 = close + sl_dist * self.config.tp_ratios[1]
            tp3 = close + sl_dist * self.config.tp_ratios[2]
        else:
            tp1 = close - sl_dist * self.config.tp_ratios[0]
            tp2 = close - sl_dist * self.config.tp_ratios[1]
            tp3 = close - sl_dist * self.config.tp_ratios[2]

        if direction == Direction.LONG and sl >= close:
            return None
        if direction == Direction.SHORT and sl <= close:
            return None

        _regime_ctx = smc_data.get("regime_context")
        sig = build_channel_signal(
            config=self.config,
            symbol=symbol,
            direction=direction,
            close=close,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            sl_dist=sl_dist,
            id_prefix="SORB",
            atr_val=atr_for_sl,
            setup_class="SMC_ORDERBLOCK",
            regime=regime,
            atr_percentile=_regime_ctx.atr_percentile if _regime_ctx else 50.0,
            pair_tier=_pair_profile.tier if _pair_profile else "MIDCAP",
        )
        if sig is not None:
            ob_type = "Bullish" if direction == Direction.LONG else "Bearish"
            sig.analyst_reason = (
                f"{ob_type} OB retest [{best_ob.ob_low:.2f}-{best_ob.ob_high:.2f}]"
            )
        return sig
