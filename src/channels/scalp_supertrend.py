"""360_SCALP_SUPERTREND – Supertrend Flip Scalp ⚡

Trigger : Supertrend direction flips (DOWN→UP = LONG, UP→DOWN = SHORT) on 5m.
Logic   : Entry on the first candle after Supertrend flips direction.
          Requires EMA alignment confirmation (EMA9 > EMA21 for LONG, vice versa).
Filters : Volume spike (1.3x avg), spread, ADX > 15
Risk    : SL at Supertrend line, TP based on ATR multiples
Signal ID prefix: "SSTR-"
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from config import CHANNEL_SCALP_SUPERTREND
from src.channels.base import BaseChannel, Signal, build_channel_signal
from src.filters import check_rsi
from src.indicators import ema as compute_ema, supertrend as compute_supertrend
from src.mtf import mtf_gate_scalp_supertrend
from src.smc import Direction
from src.utils import get_logger

log = get_logger("scalp_supertrend")

# Minimum volume ratio (current / 20-bar average) required for confirmation.
_MIN_VOLUME_RATIO: float = 1.3

# EMA periods for trend-alignment confirmation.
_EMA_FAST: int = 9
_EMA_SLOW: int = 21

# Minimum candle count needed to compute Supertrend + EMAs reliably.
_MIN_CANDLES: int = 55


class ScalpSupertrendChannel(BaseChannel):
    """Supertrend Flip scalp trigger."""

    def __init__(self) -> None:
        super().__init__(CHANNEL_SCALP_SUPERTREND)

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
        if m5 is None or len(m5.get("close", [])) < _MIN_CANDLES:
            return None

        _pair_profile = smc_data.get("pair_profile")
        if not self._pass_basic_filters(spread_pct, volume_24h_usd):
            return None

        ind = indicators.get("5m", {})
        thresholds = self._get_pair_adjusted_thresholds(_pair_profile)

        # ADX gate – need some trend strength for a meaningful flip
        adx_val = ind.get("adx_last")
        if adx_val is not None and adx_val < self.config.adx_min:
            return None

        closes = list(m5.get("close", []))
        highs = list(m5.get("high", closes))
        lows = list(m5.get("low", closes))
        volumes = list(m5.get("volume", []))

        close = float(closes[-1])

        # Compute Supertrend from raw candle data (we need full arrays)
        h_arr = np.array(highs, dtype=np.float64)
        l_arr = np.array(lows, dtype=np.float64)
        c_arr = np.array(closes, dtype=np.float64)

        st_line, st_dir = compute_supertrend(h_arr, l_arr, c_arr)

        # Need at least 2 valid direction values for flip detection
        if len(st_dir) < 2 or np.isnan(st_dir[-1]) or np.isnan(st_dir[-2]):
            return None

        prev_dir = float(st_dir[-2])
        curr_dir = float(st_dir[-1])

        # Detect flip: previous direction != current direction
        if prev_dir == curr_dir:
            return None

        if curr_dir == 1.0:
            direction = Direction.LONG
        elif curr_dir == -1.0:
            direction = Direction.SHORT
        else:
            return None

        # EMA alignment confirmation
        ema_fast = compute_ema(c_arr, _EMA_FAST)
        ema_slow = compute_ema(c_arr, _EMA_SLOW)
        if np.isnan(ema_fast[-1]) or np.isnan(ema_slow[-1]):
            return None

        if direction == Direction.LONG and ema_fast[-1] <= ema_slow[-1]:
            return None
        if direction == Direction.SHORT and ema_fast[-1] >= ema_slow[-1]:
            return None

        # Volume confirmation: current volume > 1.3× 20-bar average
        if len(volumes) >= 21:
            avg_vol = sum(float(v) for v in volumes[-21:-1]) / 20
            current_vol = float(volumes[-1])
            if avg_vol > 0 and current_vol < avg_vol * _MIN_VOLUME_RATIO:
                return None

        # RSI extreme gate
        if not check_rsi(
            ind.get("rsi_last"),
            overbought=thresholds["rsi_ob"],
            oversold=thresholds["rsi_os"],
            direction=direction.value,
        ):
            return None

        # MTF gate — require at least 2 higher TFs to agree on the flip direction
        mtf_indicators = {
            tf: indicators.get(tf, {})
            for tf in ("15m", "1h")
            if indicators.get(tf)
        }
        mtf_ok, _mtf_reason = mtf_gate_scalp_supertrend(mtf_indicators, direction.value)
        if not mtf_ok:
            return None

        # SL at Supertrend line value
        st_val = float(st_line[-1]) if not np.isnan(st_line[-1]) else None
        atr_val = ind.get("atr_last")
        atr_for_sl = atr_val if (atr_val is not None and atr_val > 0) else close * 0.002

        if st_val is not None and st_val > 0:
            sl_dist = abs(close - st_val)
            # Ensure sl_dist isn't too tight
            sl_dist = max(sl_dist, close * self.config.sl_pct_range[0] / 100)
        else:
            sl_dist = max(close * self.config.sl_pct_range[0] / 100, atr_for_sl * 0.8)

        if direction == Direction.LONG:
            sl = close - sl_dist
            tp1 = close + sl_dist * self.config.tp_ratios[0]
            tp2 = close + sl_dist * self.config.tp_ratios[1]
            tp3 = close + sl_dist * self.config.tp_ratios[2]
        else:
            sl = close + sl_dist
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
            id_prefix="SSTR",
            atr_val=atr_for_sl,
            setup_class="SUPERTREND_FLIP",
            regime=regime,
            atr_percentile=_regime_ctx.atr_percentile if _regime_ctx else 50.0,
            pair_tier=_pair_profile.tier if _pair_profile else "MIDCAP",
        )
        if sig is not None:
            flip_label = "DOWN→UP" if direction == Direction.LONG else "UP→DOWN"
            sig.analyst_reason = f"Supertrend flip {flip_label}"
        return sig
