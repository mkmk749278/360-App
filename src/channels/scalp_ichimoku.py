"""360_SCALP_ICHIMOKU – Ichimoku TK Cross Scalp ⚡

Trigger : Tenkan-sen crosses Kijun-sen (TK cross) on 5m/15m.
Logic   : Bullish TK cross (Tenkan crosses above Kijun) + price above cloud → LONG
          Bearish TK cross (Tenkan crosses below Kijun) + price below cloud → SHORT
Filters : Price must be on correct side of Kumo (cloud), spread, volume
Risk    : SL at Kijun-sen level, TP at cloud boundary and beyond
Signal ID prefix: "SICH-"
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from config import CHANNEL_SCALP_ICHIMOKU
from src.channels.base import BaseChannel, Signal, build_channel_signal
from src.filters import check_rsi
from src.indicators import ichimoku as compute_ichimoku
from src.smc import Direction
from src.utils import get_logger

log = get_logger("scalp_ichimoku")

# Minimum candle count required for Ichimoku (senkou_b=52 + kijun shift=26).
_MIN_CANDLES: int = 80


class ScalpIchimokuChannel(BaseChannel):
    """Ichimoku TK Cross scalp trigger."""

    def __init__(self) -> None:
        super().__init__(CHANNEL_SCALP_ICHIMOKU)

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
        # Try 5m first, fall back to 15m
        for tf in ("5m", "15m"):
            sig = self._evaluate_tf(
                symbol, tf, candles, indicators, smc_data,
                spread_pct, volume_24h_usd, regime,
            )
            if sig is not None:
                return sig
        return None

    # ------------------------------------------------------------------

    def _evaluate_tf(
        self,
        symbol: str,
        tf: str,
        candles: Dict[str, dict],
        indicators: Dict[str, dict],
        smc_data: dict,
        spread_pct: float,
        volume_24h_usd: float,
        regime: str = "",
    ) -> Optional[Signal]:
        cd = candles.get(tf)
        if cd is None or len(cd.get("close", [])) < _MIN_CANDLES:
            return None

        _pair_profile = smc_data.get("pair_profile")
        if not self._pass_basic_filters(spread_pct, volume_24h_usd):
            return None

        ind = indicators.get(tf, {})
        thresholds = self._get_pair_adjusted_thresholds(_pair_profile)

        closes = list(cd.get("close", []))
        highs = list(cd.get("high", closes))
        lows = list(cd.get("low", closes))

        close = float(closes[-1])

        # Compute Ichimoku from raw candle data
        h_arr = np.array(highs, dtype=np.float64)
        l_arr = np.array(lows, dtype=np.float64)
        c_arr = np.array(closes, dtype=np.float64)

        ichi = compute_ichimoku(h_arr, l_arr, c_arr)
        tenkan_sen = ichi["tenkan_sen"]
        kijun_sen = ichi["kijun_sen"]
        senkou_a = ichi["senkou_span_a"]
        senkou_b = ichi["senkou_span_b"]

        # Need at least 2 valid tenkan/kijun values for cross detection
        if (len(tenkan_sen) < 2 or len(kijun_sen) < 2
                or np.isnan(tenkan_sen[-1]) or np.isnan(tenkan_sen[-2])
                or np.isnan(kijun_sen[-1]) or np.isnan(kijun_sen[-2])):
            return None

        tenkan_now = float(tenkan_sen[-1])
        tenkan_prev = float(tenkan_sen[-2])
        kijun_now = float(kijun_sen[-1])
        kijun_prev = float(kijun_sen[-2])

        # Detect TK cross
        bullish_cross = tenkan_prev <= kijun_prev and tenkan_now > kijun_now
        bearish_cross = tenkan_prev >= kijun_prev and tenkan_now < kijun_now

        if not bullish_cross and not bearish_cross:
            return None

        # Cloud boundaries at current bar
        cloud_top_val = senkou_a[-1] if not np.isnan(senkou_a[-1]) else None
        cloud_bot_val = senkou_b[-1] if not np.isnan(senkou_b[-1]) else None

        # If cloud data is unavailable, skip cloud filter
        if cloud_top_val is not None and cloud_bot_val is not None:
            cloud_top = max(float(cloud_top_val), float(cloud_bot_val))
            cloud_bot = min(float(cloud_top_val), float(cloud_bot_val))
        else:
            cloud_top = None
            cloud_bot = None

        direction: Optional[Direction] = None
        if bullish_cross:
            # Price must be above cloud for LONG
            if cloud_top is not None and close <= cloud_top:
                return None
            direction = Direction.LONG
        elif bearish_cross:
            # Price must be below cloud for SHORT
            if cloud_bot is not None and close >= cloud_bot:
                return None
            direction = Direction.SHORT

        if direction is None:
            return None

        # Volume confirmation: TK crosses without volume participation may be weak.
        # Current volume must be ≥ 1.2× the 20-bar average.
        volumes = list(cd.get("volume", []))
        if len(volumes) >= 21:
            avg_vol = sum(float(v) for v in volumes[-21:-1]) / 20
            current_vol = float(volumes[-1])
            if avg_vol > 0 and current_vol < avg_vol * 1.2:
                return None

        # RSI extreme gate
        if not check_rsi(
            ind.get("rsi_last"),
            overbought=thresholds["rsi_ob"],
            oversold=thresholds["rsi_os"],
            direction=direction.value,
        ):
            return None

        # SL at Kijun-sen level
        atr_val = ind.get("atr_last")
        atr_for_sl = atr_val if (atr_val is not None and atr_val > 0) else close * 0.002
        sl_dist = abs(close - kijun_now)
        # Ensure sl_dist isn't too tight
        sl_dist = max(sl_dist, close * self.config.sl_pct_range[0] / 100)

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
            id_prefix="SICH",
            atr_val=atr_for_sl,
            setup_class="ICHIMOKU_TK_CROSS",
            regime=regime,
            atr_percentile=_regime_ctx.atr_percentile if _regime_ctx else 50.0,
            pair_tier=_pair_profile.tier if _pair_profile else "MIDCAP",
        )
        if sig is not None:
            cross_label = "Bullish" if direction == Direction.LONG else "Bearish"
            sig.analyst_reason = f"Ichimoku {cross_label} TK cross ({tf})"
        return sig
