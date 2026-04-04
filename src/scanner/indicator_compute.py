"""Per-pair indicator computation extracted from scanner.py.

This module contains a pure function ``compute_indicators()`` that takes
raw OHLCV numpy arrays and returns a flat dictionary of computed
indicator values.  It mirrors the logic previously embedded in
``Scanner._compute_indicators()`` but is independently testable.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np

from src.indicators import (
    adx, atr, bollinger_bands, ema, heikin_ashi, ichimoku,
    keltner_channels, macd, mfi, momentum, rsi, stochastic_rsi,
    supertrend, volume_profile, williams_r,
)

logger = logging.getLogger(__name__)

# Minimum candle requirements for each indicator group
_MIN_EMA_FAST = 21
_MIN_EMA_SLOW = 200
_MIN_ADX = 30
_MIN_RSI = 15
_MIN_ATR = 15
_MIN_BB = 20
_MIN_MACD = 35  # slow_period(26) + signal_period(9)
_MIN_MOMENTUM = 4
_MIN_STOCH_RSI = 30  # rsi_period(14) + stoch_period(14) + smoothing
_MIN_SUPERTREND = 12  # period(10) + 1 + margin
_MIN_ICHIMOKU = 78  # senkou_b(52) + kijun(26)
_MIN_HEIKIN_ASHI = 2
_MIN_VOLUME_PROFILE = 20
_MIN_KELTNER = 21  # max(ema_period(20), atr_period(10)+1)
_MIN_WILLIAMS_R = 14
_MIN_MFI = 15  # period(14) + 1
_MIN_FOR_FULL = 50  # minimum for a "useful" indicator set


def compute_indicators(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
) -> Dict[str, Any]:
    """Compute all standard indicators for a single pair/timeframe.

    Parameters
    ----------
    closes : np.ndarray
        1-D array of close prices.
    highs : np.ndarray
        1-D array of high prices.
    lows : np.ndarray
        1-D array of low prices.
    volumes : np.ndarray
        1-D array of volume values.

    Returns
    -------
    dict
        Flat dict of indicator values. Returns empty dict if
        insufficient data (< 50 bars).
    """
    closes = np.asarray(closes, dtype=np.float64).ravel()
    highs = np.asarray(highs, dtype=np.float64).ravel()
    lows = np.asarray(lows, dtype=np.float64).ravel()
    volumes = np.asarray(volumes, dtype=np.float64).ravel()

    n = len(closes)
    if n < _MIN_FOR_FULL:
        return {}

    result: Dict[str, Any] = {}

    # ── EMA ──────────────────────────────────────────────────────────
    if n >= _MIN_EMA_FAST:
        ema9_arr = ema(closes, 9)
        ema21_arr = ema(closes, 21)
        result["ema9"] = ema9_arr
        result["ema9_last"] = float(ema9_arr[-1])
        result["ema21"] = ema21_arr
        result["ema21_last"] = float(ema21_arr[-1])
        # EMA50 if possible
        if n >= 50:
            ema50_arr = ema(closes, 50)
            result["ema50"] = ema50_arr
            result["ema50_last"] = float(ema50_arr[-1])

    if n >= _MIN_EMA_SLOW:
        ema200_arr = ema(closes, 200)
        result["ema200"] = ema200_arr
        result["ema200_last"] = float(ema200_arr[-1])

    # ── ADX ──────────────────────────────────────────────────────────
    if n >= _MIN_ADX:
        adx_arr = adx(highs, lows, closes, 14)
        valid = adx_arr[~np.isnan(adx_arr)]
        result["adx_last"] = float(valid[-1]) if len(valid) else None
        result["adx"] = adx_arr

    # ── RSI ──────────────────────────────────────────────────────────
    if n >= _MIN_RSI:
        rsi_arr = rsi(closes, 14)
        valid_rsi = rsi_arr[~np.isnan(rsi_arr)]
        result["rsi"] = float(valid_rsi[-1]) if len(valid_rsi) else None
        result["rsi_arr"] = rsi_arr

    # ── ATR ──────────────────────────────────────────────────────────
    if n >= _MIN_ATR:
        atr_arr = atr(highs, lows, closes, 14)
        valid_atr = atr_arr[~np.isnan(atr_arr)]
        result["atr_last"] = float(valid_atr[-1]) if len(valid_atr) else None
        result["atr"] = atr_arr
        # ATR percentage relative to close
        if result.get("atr_last") and closes[-1] > 0:
            result["atr_pct"] = result["atr_last"] / closes[-1] * 100

    # ── Bollinger Bands ──────────────────────────────────────────────
    if n >= _MIN_BB:
        upper, middle, lower = bollinger_bands(closes, 20, 2.0)
        result["bb_upper"] = float(upper[-1]) if not np.isnan(upper[-1]) else None
        result["bb_middle"] = float(middle[-1]) if not np.isnan(middle[-1]) else None
        result["bb_lower"] = float(lower[-1]) if not np.isnan(lower[-1]) else None
        if result["bb_upper"] and result["bb_lower"] and result["bb_lower"] > 0:
            result["bb_width_pct"] = (
                (result["bb_upper"] - result["bb_lower"]) / result["bb_middle"] * 100
            )

    # ── MACD ─────────────────────────────────────────────────────────
    if n >= _MIN_MACD:
        ml, sl_line, hist = macd(closes)
        result["macd_histogram_last"] = (
            float(hist[-1]) if not np.isnan(hist[-1]) else None
        )
        result["macd_histogram_prev"] = (
            float(hist[-2]) if len(hist) > 1 and not np.isnan(hist[-2]) else None
        )
        result["macd_line_last"] = float(ml[-1]) if not np.isnan(ml[-1]) else None
        result["macd_signal_last"] = float(sl_line[-1]) if not np.isnan(sl_line[-1]) else None

    # ── Momentum ─────────────────────────────────────────────────────
    if n >= _MIN_MOMENTUM:
        mom = momentum(closes, 3)
        result["momentum_last"] = (
            float(mom[-1]) if not np.isnan(mom[-1]) else None
        )

    # ── Volume statistics ────────────────────────────────────────────
    if len(volumes) >= 20:
        vol_sma = np.mean(volumes[-20:])
        result["volume_sma20"] = float(vol_sma)
        result["volume_last"] = float(volumes[-1])
        if vol_sma > 0:
            result["volume_ratio"] = float(volumes[-1] / vol_sma)

    # ── Stochastic RSI ──────────────────────────────────────────────
    if n >= _MIN_STOCH_RSI:
        k_line, d_line = stochastic_rsi(closes)
        valid_k = k_line[~np.isnan(k_line)]
        valid_d = d_line[~np.isnan(d_line)]
        result["stoch_rsi_k"] = float(valid_k[-1]) if len(valid_k) else None
        result["stoch_rsi_d"] = float(valid_d[-1]) if len(valid_d) else None

    # ── Supertrend ──────────────────────────────────────────────────
    if n >= _MIN_SUPERTREND:
        st_line, st_dir = supertrend(highs, lows, closes)
        valid_st = st_line[~np.isnan(st_line)]
        valid_dir = st_dir[~np.isnan(st_dir)]
        result["supertrend_line"] = float(valid_st[-1]) if len(valid_st) else None
        result["supertrend_direction"] = float(valid_dir[-1]) if len(valid_dir) else None

    # ── Ichimoku ────────────────────────────────────────────────────
    if n >= _MIN_ICHIMOKU:
        ichi = ichimoku(highs, lows, closes)
        ts = ichi["tenkan_sen"]
        ks = ichi["kijun_sen"]
        sa = ichi["senkou_span_a"]
        sb = ichi["senkou_span_b"]
        result["ichimoku_tenkan"] = float(ts[-1]) if not np.isnan(ts[-1]) else None
        result["ichimoku_kijun"] = float(ks[-1]) if not np.isnan(ks[-1]) else None
        result["ichimoku_cloud_top"] = float(sa[-1]) if not np.isnan(sa[-1]) else None
        result["ichimoku_cloud_bottom"] = float(sb[-1]) if not np.isnan(sb[-1]) else None

    # ── Heikin-Ashi ─────────────────────────────────────────────────
    if n >= _MIN_HEIKIN_ASHI:
        # Use closes as proxy for opens when opens are not available
        ha_o, _ha_h, _ha_l, ha_c = heikin_ashi(closes, highs, lows, closes)
        result["ha_close_last"] = float(ha_c[-1])
        if ha_c[-1] > ha_o[-1]:
            result["ha_trend"] = "BULLISH"
        elif ha_c[-1] < ha_o[-1]:
            result["ha_trend"] = "BEARISH"
        else:
            result["ha_trend"] = "NEUTRAL"

    # ── Volume Profile ──────────────────────────────────────────────
    if n >= _MIN_VOLUME_PROFILE and len(volumes) >= _MIN_VOLUME_PROFILE:
        vp = volume_profile(closes, volumes)
        result["volume_poc"] = vp["poc"]
        result["volume_vah"] = vp["vah"]
        result["volume_val"] = vp["val"]

    # ── Keltner Channels ────────────────────────────────────────────
    if n >= _MIN_KELTNER:
        k_upper, k_mid, k_lower = keltner_channels(highs, lows, closes)
        result["keltner_upper"] = float(k_upper[-1]) if not np.isnan(k_upper[-1]) else None
        result["keltner_lower"] = float(k_lower[-1]) if not np.isnan(k_lower[-1]) else None
        result["keltner_mid"] = float(k_mid[-1]) if not np.isnan(k_mid[-1]) else None

    # ── Williams %R ─────────────────────────────────────────────────
    if n >= _MIN_WILLIAMS_R:
        wr = williams_r(highs, lows, closes)
        valid_wr = wr[~np.isnan(wr)]
        result["williams_r"] = float(valid_wr[-1]) if len(valid_wr) else None

    # ── MFI ─────────────────────────────────────────────────────────
    if n >= _MIN_MFI and len(volumes) >= _MIN_MFI:
        mfi_arr = mfi(highs, lows, closes, volumes)
        valid_mfi = mfi_arr[~np.isnan(mfi_arr)]
        result["mfi"] = float(valid_mfi[-1]) if len(valid_mfi) else None

    return result


def compute_indicators_for_candle_dict(candle_dict: Dict[str, dict]) -> Dict[str, dict]:
    """Compute indicators for each timeframe in a candle dict.

    Mirrors the structure returned by the old ``Scanner._compute_indicators()``:
    uses the same key names (``rsi_last``, ``bb_upper_last``, ``bb_mid_last``,
    ``bb_lower_last``) so that downstream scanner logic is unaffected.

    Parameters
    ----------
    candle_dict : dict
        Mapping of timeframe → dict with keys: "high", "low", "close"
        (each being a list or array).

    Returns
    -------
    dict
        Mapping of timeframe → indicator result dict compatible with the
        original ``Scanner._compute_indicators()`` output.
    """
    indicators: Dict[str, dict] = {}
    for tf_key, cd in candle_dict.items():
        try:
            h = np.asarray(cd.get("high", []), dtype=np.float64).ravel()
            lo = np.asarray(cd.get("low", []), dtype=np.float64).ravel()
            c = np.asarray(cd.get("close", []), dtype=np.float64).ravel()
            v = np.asarray(cd.get("volume", cd.get("vol", [])), dtype=np.float64).ravel()
            ind: dict = {}
            if len(c) >= 21:
                ind["ema9_last"] = float(ema(c, 9)[-1])
                ind["ema21_last"] = float(ema(c, 21)[-1])
            if len(c) >= 200:
                ind["ema200_last"] = float(ema(c, 200)[-1])
            if len(c) >= 30:
                a = adx(h, lo, c, 14)
                valid = a[~np.isnan(a)]
                ind["adx_last"] = float(valid[-1]) if len(valid) else None
            if len(c) >= 15:
                a = atr(h, lo, c, 14)
                valid = a[~np.isnan(a)]
                ind["atr_last"] = float(valid[-1]) if len(valid) else None
            if len(c) >= 15:
                r = rsi(c, 14)
                valid = r[~np.isnan(r)]
                ind["rsi_last"] = float(valid[-1]) if len(valid) else None
            if len(c) >= 20:
                u, m, lower = bollinger_bands(c, 20)
                ind["bb_upper_last"] = float(u[-1]) if not np.isnan(u[-1]) else None
                ind["bb_mid_last"] = float(m[-1]) if not np.isnan(m[-1]) else None
                ind["bb_lower_last"] = float(lower[-1]) if not np.isnan(lower[-1]) else None
            if len(c) >= 4:
                mom = momentum(c, 3)
                ind["momentum_last"] = float(mom[-1]) if not np.isnan(mom[-1]) else None
            if len(c) >= 35:  # slow_period(26) + signal_period(9)
                ml, sl_line, hist = macd(c)
                ind["macd_histogram_last"] = (
                    float(hist[-1]) if not np.isnan(hist[-1]) else None
                )
                ind["macd_histogram_prev"] = (
                    float(hist[-2]) if len(hist) > 1 and not np.isnan(hist[-2]) else None
                )
            # ── New indicators ──────────────────────────────────────
            if len(c) >= _MIN_STOCH_RSI:
                k_line, d_line = stochastic_rsi(c)
                vk = k_line[~np.isnan(k_line)]
                vd = d_line[~np.isnan(d_line)]
                ind["stoch_rsi_k"] = float(vk[-1]) if len(vk) else None
                ind["stoch_rsi_d"] = float(vd[-1]) if len(vd) else None
            if len(c) >= _MIN_SUPERTREND:
                st_line, st_dir = supertrend(h, lo, c)
                vs = st_line[~np.isnan(st_line)]
                vdir = st_dir[~np.isnan(st_dir)]
                ind["supertrend_line"] = float(vs[-1]) if len(vs) else None
                ind["supertrend_direction"] = float(vdir[-1]) if len(vdir) else None
            if len(c) >= _MIN_ICHIMOKU:
                ichi = ichimoku(h, lo, c)
                ts = ichi["tenkan_sen"]
                ks = ichi["kijun_sen"]
                sa = ichi["senkou_span_a"]
                sb = ichi["senkou_span_b"]
                ind["ichimoku_tenkan"] = float(ts[-1]) if not np.isnan(ts[-1]) else None
                ind["ichimoku_kijun"] = float(ks[-1]) if not np.isnan(ks[-1]) else None
                ind["ichimoku_cloud_top"] = float(sa[-1]) if not np.isnan(sa[-1]) else None
                ind["ichimoku_cloud_bottom"] = float(sb[-1]) if not np.isnan(sb[-1]) else None
            if len(c) >= _MIN_HEIKIN_ASHI:
                ha_o, _ha_h, _ha_l, ha_c = heikin_ashi(c, h, lo, c)
                ind["ha_close_last"] = float(ha_c[-1])
                if ha_c[-1] > ha_o[-1]:
                    ind["ha_trend"] = "BULLISH"
                elif ha_c[-1] < ha_o[-1]:
                    ind["ha_trend"] = "BEARISH"
                else:
                    ind["ha_trend"] = "NEUTRAL"
            if len(c) >= _MIN_VOLUME_PROFILE and len(v) >= _MIN_VOLUME_PROFILE:
                vp = volume_profile(c, v)
                ind["volume_poc"] = vp["poc"]
                ind["volume_vah"] = vp["vah"]
                ind["volume_val"] = vp["val"]
            if len(c) >= _MIN_KELTNER:
                k_upper, k_mid, k_lower = keltner_channels(h, lo, c)
                ind["keltner_upper"] = float(k_upper[-1]) if not np.isnan(k_upper[-1]) else None
                ind["keltner_lower"] = float(k_lower[-1]) if not np.isnan(k_lower[-1]) else None
                ind["keltner_mid"] = float(k_mid[-1]) if not np.isnan(k_mid[-1]) else None
            if len(c) >= _MIN_WILLIAMS_R:
                wr = williams_r(h, lo, c)
                vwr = wr[~np.isnan(wr)]
                ind["williams_r"] = float(vwr[-1]) if len(vwr) else None
            if len(c) >= _MIN_MFI and len(v) >= _MIN_MFI:
                mfi_arr = mfi(h, lo, c, v)
                vmfi = mfi_arr[~np.isnan(mfi_arr)]
                ind["mfi"] = float(vmfi[-1]) if len(vmfi) else None
            indicators[tf_key] = ind
        except Exception as exc:
            logger.warning("Indicator computation failed for %s: %s", tf_key, exc)
            indicators[tf_key] = {}
    return indicators
