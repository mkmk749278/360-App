"""360_SCALP_VWAP – VWAP Band Bounce Scalp ⚡

Trigger : Price touches VWAP ±1SD band with volume confirmation.
Logic   : Price touches lower_band_1 (VWAP − 1SD) → LONG (mean reversion)
          Price touches upper_band_1 (VWAP + 1SD) → SHORT (mean reversion)
Filters : Must be in RANGING or QUIET regime (mean-reversion only, not trending)
          Current volume > 1.3× average (volume confirmation)
Risk    : SL beyond ±2SD band, TP at VWAP center
Signal ID prefix: "SVWP-"
"""

from __future__ import annotations

from typing import Dict, Optional

from config import CHANNEL_SCALP_VWAP
from src.channels.base import BaseChannel, Signal, build_channel_signal
from src.filters import check_rsi
from src.regime import MarketRegime
from src.smc import Direction
from src.vwap import compute_vwap

# Minimum volume ratio (current / average) required to confirm the bounce.
# Set to 1.5× for institutional-grade bounce confirmation — lower ratios often
# produce weak mean-reversion setups that fail to reach VWAP center.
_MIN_VOLUME_RATIO: float = 1.5

# ATR percentage reference used to scale the volume ratio adaptively.
# When current ATR% is at or above this level, the full _MIN_VOLUME_RATIO is
# applied.  Below it the ratio scales down linearly (floor 1.2×) so that
# low-volatility markets still pass the volume confirmation gate.
_ATR_PCT_VOL_SCALE_REF: float = 0.3

# Regimes where VWAP bounce scalps are valid (mean-reversion only)
_VALID_REGIMES = frozenset({MarketRegime.RANGING, MarketRegime.QUIET})


class ScalpVWAPChannel(BaseChannel):
    """VWAP Band Bounce scalp trigger."""

    def __init__(self) -> None:
        super().__init__(CHANNEL_SCALP_VWAP)

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
        # Regime gate: only valid in RANGING or QUIET
        # Note: regime_result is not directly available in evaluate(); the
        # scanner's regime gating happens upstream.  We rely on the scanner
        # to have already filtered out trending regimes via the regime-channel
        # compatibility matrix.  For defensive validation, check ADX as a proxy.
        for tf in ("5m", "15m"):
            sig = self._evaluate_tf(
                symbol, tf, candles, indicators, smc_data, spread_pct, volume_24h_usd, regime
            )
            if sig is not None:
                return sig
        return None

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
        if cd is None or len(cd.get("close", [])) < 20:
            return None

        _pair_profile = smc_data.get("pair_profile")
        if not self._pass_basic_filters(spread_pct, volume_24h_usd):
            return None

        ind = indicators.get(tf, {})
        thresholds = self._get_pair_adjusted_thresholds(_pair_profile)

        # ADX check: only valid in low-ADX (ranging/quiet) environment
        adx_val = ind.get("adx_last")
        if adx_val is not None and adx_val > self.config.adx_max:
            return None

        highs = list(cd.get("high", []))
        lows = list(cd.get("low", []))
        closes = list(cd.get("close", []))
        volumes = list(cd.get("volume", []))

        if len(closes) < 20 or len(volumes) < 20:
            return None

        # Compute VWAP with ±1SD bands
        vwap_result = compute_vwap(highs[-50:], lows[-50:], closes[-50:], volumes[-50:])
        if vwap_result is None:
            return None

        close = float(closes[-1])
        lower_band_1 = vwap_result.lower_band_1
        upper_band_1 = vwap_result.upper_band_1
        lower_band_2 = vwap_result.lower_band_2
        upper_band_2 = vwap_result.upper_band_2
        vwap_mid = vwap_result.vwap

        # Volume confirmation: current volume must exceed average by a
        # regime-adaptive ratio.  In low-volatility (QUIET) markets valid
        # mean-reversion bounces often show only moderate volume uptick, so
        # the threshold is relaxed to avoid filtering legitimate setups.
        avg_vol = sum(float(v) for v in volumes[-20:-1]) / 19
        current_vol = float(volumes[-1])
        atr_val = ind.get("atr_last")
        if atr_val is not None and close > 0:
            atr_pct = (atr_val / close) * 100.0
            # In low ATR environments, lower the volume ratio requirement
            effective_vol_ratio = max(1.2, _MIN_VOLUME_RATIO * min(1.0, atr_pct / _ATR_PCT_VOL_SCALE_REF))
        else:
            effective_vol_ratio = _MIN_VOLUME_RATIO
        if avg_vol <= 0 or current_vol < avg_vol * effective_vol_ratio:
            return None

        # Determine direction based on VWAP band touch.
        # ATR-adaptive proximity buffer: allow close within 0.5×ATR of the
        # band boundary so setups are not rejected for missing exact touch.
        atr_buf = (atr_val * 0.5) if atr_val is not None else 0.0
        direction: Optional[Direction] = None
        if close <= lower_band_1 + atr_buf:
            direction = Direction.LONG
        elif close >= upper_band_1 - atr_buf:
            direction = Direction.SHORT
        else:
            return None

        # RSI extreme gate: use pair-specific OB/OS levels when available
        if not check_rsi(ind.get("rsi_last"), overbought=thresholds["rsi_ob"], oversold=thresholds["rsi_os"], direction=direction.value):
            return None

        # SL: beyond ±2SD band
        if direction == Direction.LONG:
            sl = lower_band_2 - (vwap_result.std_dev * 0.1)
            tp1 = vwap_mid  # TP at VWAP center
        else:
            sl = upper_band_2 + (vwap_result.std_dev * 0.1)
            tp1 = vwap_mid  # TP at VWAP center

        sl_dist = abs(close - sl)
        if sl_dist <= 0:
            return None

        if direction == Direction.LONG:
            tp2 = close + sl_dist * self.config.tp_ratios[1]
            tp3 = close + sl_dist * self.config.tp_ratios[2]
        else:
            tp2 = close - sl_dist * self.config.tp_ratios[1]
            tp3 = close - sl_dist * self.config.tp_ratios[2]

        if direction == Direction.LONG and sl >= close:
            return None
        if direction == Direction.SHORT and sl <= close:
            return None

        atr_val = ind.get("atr_last", close * 0.002)

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
            id_prefix="SVWP",
            atr_val=atr_val,
            vwap_price=vwap_mid,
            setup_class="VWAP_BOUNCE",
            regime=regime,
            atr_percentile=_regime_ctx.atr_percentile if _regime_ctx else 50.0,
            pair_tier=_pair_profile.tier if _pair_profile else "MIDCAP",
        )
        if sig is not None:
            band_label = "lower" if direction == Direction.LONG else "upper"
            sig.analyst_reason = (
                f"VWAP {band_label} band bounce ({tf}), VWAP={vwap_mid:.2f}"
            )

        return sig
