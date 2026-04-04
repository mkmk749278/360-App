"""360_SCALP_DIVERGENCE – RSI/MACD Divergence Scalp ⚡

Trigger : Hidden or regular RSI/MACD divergence on 5m timeframe.
Logic   : BULLISH divergence → LONG (price lower low, RSI/MACD higher low)
          BEARISH divergence → SHORT (price higher high, RSI/MACD lower high)
          Hidden divergence: trend continuation (price higher low, RSI lower low → LONG)
Filters : ADX < 40 (divergence fails in strong trends), spread, volume
Risk    : SL below recent swing, TP1 1.5R, TP2 2.5R
Signal ID prefix: "SDIV-"
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from config import CHANNEL_SCALP_DIVERGENCE
from src.channels.base import BaseChannel, Signal, build_channel_signal
from src.filters import check_rsi
from src.indicators import macd as compute_macd, rsi as compute_rsi
from src.mtf import mtf_gate_scalp_divergence
from src.smc import Direction
from src.utils import get_logger

log = get_logger("scalp_divergence")

# Lookback window (in candles) for divergence detection.
_DIV_LOOKBACK: int = 20

# Minimum fraction of clean (non-NaN) RSI values required for divergence detection.
_MIN_RSI_CLEAN_RATIO: float = 0.5

# ADX ceiling – divergences are unreliable in very strong trends.
_ADX_MAX: float = 40.0


def _find_local_lows(arr: list[float], window: int = 3) -> list[tuple[int, float]]:
    """Return (index, value) pairs for local minima in *arr*."""
    pts: list[tuple[int, float]] = []
    for i in range(window, len(arr) - window):
        if arr[i] == min(arr[i - window: i + window + 1]):
            pts.append((i, arr[i]))
    return pts


def _find_local_highs(arr: list[float], window: int = 3) -> list[tuple[int, float]]:
    """Return (index, value) pairs for local maxima in *arr*."""
    pts: list[tuple[int, float]] = []
    for i in range(window, len(arr) - window):
        if arr[i] == max(arr[i - window: i + window + 1]):
            pts.append((i, arr[i]))
    return pts


class ScalpDivergenceChannel(BaseChannel):
    """RSI / MACD Divergence scalp trigger."""

    def __init__(self) -> None:
        super().__init__(CHANNEL_SCALP_DIVERGENCE)

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
        if m5 is None or len(m5.get("close", [])) < _DIV_LOOKBACK + 10:
            return None

        _pair_profile = smc_data.get("pair_profile")
        if not self._pass_basic_filters(spread_pct, volume_24h_usd):
            return None

        ind = indicators.get("5m", {})
        thresholds = self._get_pair_adjusted_thresholds(_pair_profile)

        # ADX gate – divergences are unreliable in very strong trends
        adx_val = ind.get("adx_last")
        if adx_val is not None and adx_val > _ADX_MAX:
            return None

        closes = list(m5.get("close", []))
        highs = list(m5.get("high", closes))
        lows = list(m5.get("low", closes))

        close = float(closes[-1])

        # Compute RSI array over the lookback window.
        # Drop NaN values instead of replacing with 50.0 to avoid creating
        # artificial swing points that produce false divergence detections.
        rsi_arr_raw = ind.get("rsi_arr")
        if rsi_arr_raw is None or len(rsi_arr_raw) < _DIV_LOOKBACK:
            rsi_arr_raw = compute_rsi(np.array(closes, dtype=np.float64))
        rsi_clean = [float(v) for v in rsi_arr_raw[-_DIV_LOOKBACK:] if not np.isnan(v)]
        if len(rsi_clean) < int(_DIV_LOOKBACK * _MIN_RSI_CLEAN_RATIO):
            return None  # Too many NaN values — insufficient RSI data
        rsi_arr = rsi_clean

        # Compute MACD histogram for confirmation
        macd_hist: Optional[list[float]] = None
        macd_data = ind.get("macd_histogram") or ind.get("macd_hist")
        if macd_data is not None and len(macd_data) >= _DIV_LOOKBACK:
            macd_hist = [float(v) if not np.isnan(v) else 0.0 for v in macd_data[-_DIV_LOOKBACK:]]
        else:
            _, _, hist_raw = compute_macd(np.array(closes, dtype=np.float64))
            if len(hist_raw) >= _DIV_LOOKBACK:
                macd_hist = [float(v) if not np.isnan(v) else 0.0 for v in hist_raw[-_DIV_LOOKBACK:]]

        price_window = [float(c) for c in closes[-_DIV_LOOKBACK:]]
        low_window = [float(l) for l in lows[-_DIV_LOOKBACK:]]
        high_window = [float(h) for h in highs[-_DIV_LOOKBACK:]]

        direction: Optional[Direction] = None
        div_type: str = ""

        # --- Regular bullish: price lower low, RSI higher low → LONG ---
        price_lows = _find_local_lows(low_window)
        rsi_lows = _find_local_lows(rsi_arr)
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            p1, p2 = price_lows[-2], price_lows[-1]
            r1, r2 = rsi_lows[-2], rsi_lows[-1]
            if p2[1] < p1[1] and r2[1] > r1[1]:
                direction = Direction.LONG
                div_type = "REGULAR_BULL"

        # --- Regular bearish: price higher high, RSI lower high → SHORT ---
        if direction is None:
            price_highs = _find_local_highs(high_window)
            rsi_highs = _find_local_highs(rsi_arr)
            if len(price_highs) >= 2 and len(rsi_highs) >= 2:
                p1, p2 = price_highs[-2], price_highs[-1]
                r1, r2 = rsi_highs[-2], rsi_highs[-1]
                if p2[1] > p1[1] and r2[1] < r1[1]:
                    direction = Direction.SHORT
                    div_type = "REGULAR_BEAR"

        # --- Hidden bullish: price higher low, RSI lower low → LONG ---
        if direction is None and len(price_lows) >= 2 and len(rsi_lows) >= 2:
            p1, p2 = price_lows[-2], price_lows[-1]
            r1, r2 = rsi_lows[-2], rsi_lows[-1]
            if p2[1] > p1[1] and r2[1] < r1[1]:
                direction = Direction.LONG
                div_type = "HIDDEN_BULL"

        # --- Hidden bearish: price lower high, RSI higher high → SHORT ---
        if direction is None:
            price_highs = _find_local_highs(high_window)
            rsi_highs = _find_local_highs(rsi_arr)
            if len(price_highs) >= 2 and len(rsi_highs) >= 2:
                p1, p2 = price_highs[-2], price_highs[-1]
                r1, r2 = rsi_highs[-2], rsi_highs[-1]
                if p2[1] < p1[1] and r2[1] > r1[1]:
                    direction = Direction.SHORT
                    div_type = "HIDDEN_BEAR"

        if direction is None:
            return None

        # MACD histogram confirmation boost (not required but tracked)
        macd_confirmed = False
        if macd_hist is not None:
            macd_lows = _find_local_lows(macd_hist)
            macd_highs = _find_local_highs(macd_hist)
            if direction == Direction.LONG and len(macd_lows) >= 2:
                m1, m2 = macd_lows[-2], macd_lows[-1]
                if m2[1] > m1[1]:
                    macd_confirmed = True
            elif direction == Direction.SHORT and len(macd_highs) >= 2:
                m1, m2 = macd_highs[-2], macd_highs[-1]
                if m2[1] < m1[1]:
                    macd_confirmed = True

        # RSI extreme gate
        if not check_rsi(
            ind.get("rsi_last"),
            overbought=thresholds["rsi_ob"],
            oversold=thresholds["rsi_os"],
            direction=direction.value,
        ):
            return None

        # MTF gate — 15m RSI must not strongly oppose divergence direction
        mtf_indicators = {
            tf: indicators.get(tf, {})
            for tf in ("15m", "1h")
            if indicators.get(tf)
        }
        mtf_ok, _mtf_reason = mtf_gate_scalp_divergence(mtf_indicators, direction.value)
        if not mtf_ok:
            return None

        # SL / TP computation
        atr_val = ind.get("atr_last")
        atr_for_sl = atr_val if (atr_val is not None and atr_val > 0) else close * 0.002
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
            id_prefix="SDIV",
            atr_val=atr_for_sl,
            setup_class="RSI_MACD_DIVERGENCE",
            regime=regime,
            atr_percentile=_regime_ctx.atr_percentile if _regime_ctx else 50.0,
            pair_tier=_pair_profile.tier if _pair_profile else "MIDCAP",
        )
        if sig is not None:
            macd_tag = " +MACD" if macd_confirmed else ""
            sig.analyst_reason = f"{div_type} divergence{macd_tag}"
        return sig
