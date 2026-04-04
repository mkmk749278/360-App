"""Technical indicators used across all channels.

All functions accept numpy arrays (or lists) and return numpy arrays.
They are pure-compute, no I/O.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def ema(close: NDArray, period: int) -> NDArray:
    """Exponential Moving Average."""
    arr = np.asarray(close, dtype=np.float64)
    out = np.full_like(arr, np.nan)
    if len(arr) < period:
        return out
    k = 2.0 / (period + 1)
    out[period - 1] = np.mean(arr[:period])
    for i in range(period, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def sma(close: NDArray, period: int) -> NDArray:
    """Simple Moving Average."""
    arr = np.asarray(close, dtype=np.float64)
    out = np.full_like(arr, np.nan)
    if len(arr) < period:
        return out
    cumsum = np.cumsum(arr)
    cumsum[period:] = cumsum[period:] - cumsum[:-period]
    out[period - 1:] = cumsum[period - 1:] / period
    return out


# ---------------------------------------------------------------------------
# ADX (Average Directional Index)
# ---------------------------------------------------------------------------

def adx(high: NDArray, low: NDArray, close: NDArray, period: int = 14) -> NDArray:
    """Average Directional Index (Wilder smoothing)."""
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    out = np.full(n, np.nan)
    if n < period * 2:
        return out

    tr = np.maximum(h[1:] - l[1:],
                     np.maximum(np.abs(h[1:] - c[:-1]),
                                np.abs(l[1:] - c[:-1])))
    up_move = h[1:] - h[:-1]
    dn_move = l[:-1] - l[1:]
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)

    atr_val = np.zeros(len(tr))
    atr_val[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr_val[i] = (atr_val[i - 1] * (period - 1) + tr[i]) / period

    sm_plus = np.zeros(len(tr))
    sm_minus = np.zeros(len(tr))
    sm_plus[period - 1] = np.mean(plus_dm[:period])
    sm_minus[period - 1] = np.mean(minus_dm[:period])
    for i in range(period, len(tr)):
        sm_plus[i] = (sm_plus[i - 1] * (period - 1) + plus_dm[i]) / period
        sm_minus[i] = (sm_minus[i - 1] * (period - 1) + minus_dm[i]) / period

    with np.errstate(divide="ignore", invalid="ignore"):
        di_plus = np.where(atr_val > 0, 100 * sm_plus / atr_val, 0.0)
        di_minus = np.where(atr_val > 0, 100 * sm_minus / atr_val, 0.0)
        di_sum = di_plus + di_minus
        dx = np.where(di_sum > 0, 100 * np.abs(di_plus - di_minus) / di_sum, 0.0)

    adx_val = np.zeros(len(dx))
    start = 2 * period - 1
    if start < len(dx):
        adx_val[start] = np.mean(dx[period:start + 1])
    for i in range(start + 1, len(dx)):
        adx_val[i] = (adx_val[i - 1] * (period - 1) + dx[i]) / period

    out[2 * period:] = adx_val[2 * period - 1: len(dx)]
    return out


# ---------------------------------------------------------------------------
# ATR (Average True Range)
# ---------------------------------------------------------------------------

def atr(high: NDArray, low: NDArray, close: NDArray, period: int = 14) -> NDArray:
    """Average True Range (Wilder smoothing)."""
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out

    tr = np.maximum(h[1:] - l[1:],
                     np.maximum(np.abs(h[1:] - c[:-1]),
                                np.abs(l[1:] - c[:-1])))
    atr_arr = np.zeros(len(tr))
    atr_arr[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr_arr[i] = (atr_arr[i - 1] * (period - 1) + tr[i]) / period

    out[period:] = atr_arr[period - 1:]
    return out


# ---------------------------------------------------------------------------
# RSI (Relative Strength Index)
# ---------------------------------------------------------------------------

def rsi(close: NDArray, period: int = 14) -> NDArray:
    """Relative Strength Index (Wilder smoothing)."""
    arr = np.asarray(close, dtype=np.float64)
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out

    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    # First valid RSI value
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + np.mean(gains[:period]) / max(np.mean(losses[:period]), 1e-10))
    return out


# ---------------------------------------------------------------------------
# MACD (Moving Average Convergence Divergence)
# ---------------------------------------------------------------------------

def macd(
    close: NDArray,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[NDArray, NDArray, NDArray]:
    """MACD (Moving Average Convergence Divergence).

    Computes the MACD line (fast EMA − slow EMA), the signal line (EMA of
    the MACD line), and the histogram (MACD − signal).

    Parameters
    ----------
    close:
        Array of closing prices.
    fast_period:
        Period for the fast EMA (default 12).
    slow_period:
        Period for the slow EMA (default 26).
    signal_period:
        Period for the signal-line EMA (default 9).

    Returns
    -------
    tuple[NDArray, NDArray, NDArray]
        ``(macd_line, signal_line, histogram)`` – all the same length as
        *close*.  Elements are ``NaN`` until enough data is available.
    """
    arr = np.asarray(close, dtype=np.float64)
    n = len(arr)
    nan_out = np.full(n, np.nan)

    if n < slow_period:
        return nan_out.copy(), nan_out.copy(), nan_out.copy()

    fast_ema = ema(arr, fast_period)
    slow_ema = ema(arr, slow_period)
    macd_line = fast_ema - slow_ema  # NaN wherever slow_ema is NaN

    # Compute signal line as EMA of the valid portion of macd_line
    signal_line = np.full(n, np.nan)
    valid_mask = ~np.isnan(macd_line)
    valid_macd = macd_line[valid_mask]
    if len(valid_macd) >= signal_period:
        sig = ema(valid_macd, signal_period)
        # Map back to original indices
        indices = np.where(valid_mask)[0]
        signal_line[indices] = sig

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def bollinger_bands(
    close: NDArray, period: int = 20, num_std: float = 2.0
) -> tuple[NDArray, NDArray, NDArray]:
    """Return (upper, middle, lower) Bollinger Bands."""
    mid = sma(close, period)
    arr = np.asarray(close, dtype=np.float64)
    std = np.full_like(arr, np.nan)
    for i in range(period - 1, len(arr)):
        std[i] = np.std(arr[i - period + 1: i + 1], ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


# ---------------------------------------------------------------------------
# Volume Delta (simple tick-level approximation)
# ---------------------------------------------------------------------------

def volume_delta(buy_vol: NDArray, sell_vol: NDArray) -> NDArray:
    """Cumulative Volume Delta."""
    return np.cumsum(np.asarray(buy_vol, dtype=np.float64)
                     - np.asarray(sell_vol, dtype=np.float64))


# ---------------------------------------------------------------------------
# Momentum (% change over N candles)
# ---------------------------------------------------------------------------

def momentum(close: NDArray, n: int = 3) -> NDArray:
    """Percentage change over *n* candles."""
    arr = np.asarray(close, dtype=np.float64)
    out = np.full_like(arr, np.nan)
    if len(arr) <= n:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        out[n:] = (arr[n:] - arr[:-n]) / arr[:-n] * 100.0
    return out


# ---------------------------------------------------------------------------
# Stochastic RSI
# ---------------------------------------------------------------------------

def stochastic_rsi(
    close: NDArray,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_period: int = 3,
    d_period: int = 3,
) -> tuple[NDArray, NDArray]:
    """Stochastic RSI oscillator.

    Computes RSI first, then applies the stochastic oscillator formula
    on the RSI values.

    Parameters
    ----------
    close : NDArray
        Array of closing prices.
    rsi_period : int
        Look-back for the RSI calculation (default 14).
    stoch_period : int
        Look-back for the stochastic min/max window (default 14).
    k_period : int
        SMA smoothing period for the %K line (default 3).
    d_period : int
        SMA smoothing period for the %D line (default 3).

    Returns
    -------
    tuple[NDArray, NDArray]
        ``(k_line, d_line)`` scaled 0-100.
    """
    arr = np.asarray(close, dtype=np.float64)
    n = len(arr)
    nan_out = np.full(n, np.nan)
    if n < rsi_period + stoch_period:
        return nan_out.copy(), nan_out.copy()

    rsi_arr = rsi(arr, rsi_period)

    # Stochastic on RSI values
    stoch_raw = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(rsi_arr[i]):
            continue
        start = max(0, i - stoch_period + 1)
        window = rsi_arr[start: i + 1]
        window = window[~np.isnan(window)]
        if len(window) < stoch_period:
            continue
        rsi_low = np.min(window)
        rsi_high = np.max(window)
        if rsi_high - rsi_low == 0:
            stoch_raw[i] = 100.0
        else:
            stoch_raw[i] = (rsi_arr[i] - rsi_low) / (rsi_high - rsi_low) * 100.0

    # SMA smoothing on the valid portion, mapped back to original indices
    k_line = np.full(n, np.nan)
    valid_mask = ~np.isnan(stoch_raw)
    valid_stoch = stoch_raw[valid_mask]
    if len(valid_stoch) >= k_period:
        k_smooth = sma(valid_stoch, k_period)
        k_line[np.where(valid_mask)[0]] = k_smooth

    d_line = np.full(n, np.nan)
    valid_k_mask = ~np.isnan(k_line)
    valid_k = k_line[valid_k_mask]
    if len(valid_k) >= d_period:
        d_smooth = sma(valid_k, d_period)
        d_line[np.where(valid_k_mask)[0]] = d_smooth

    return k_line, d_line


# ---------------------------------------------------------------------------
# Supertrend
# ---------------------------------------------------------------------------

def supertrend(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[NDArray, NDArray]:
    """Supertrend indicator.

    Parameters
    ----------
    high, low, close : NDArray
        Price arrays.
    period : int
        ATR look-back period (default 10).
    multiplier : float
        ATR multiplier for band width (default 3.0).

    Returns
    -------
    tuple[NDArray, NDArray]
        ``(supertrend_line, direction)`` where direction is 1.0 (UP)
        or -1.0 (DOWN).
    """
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    st_line = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    if n < period + 1:
        return st_line, direction

    atr_arr = atr(h, l, c, period)
    hl2 = (h + l) / 2.0

    upper_band = np.full(n, np.nan)
    lower_band = np.full(n, np.nan)

    for i in range(n):
        if np.isnan(atr_arr[i]):
            continue
        upper_band[i] = hl2[i] + multiplier * atr_arr[i]
        lower_band[i] = hl2[i] - multiplier * atr_arr[i]

    # Band flip logic
    first_valid = None
    for i in range(n):
        if not np.isnan(upper_band[i]):
            first_valid = i
            break
    if first_valid is None:
        return st_line, direction

    # Initialize at first valid index
    direction[first_valid] = 1.0
    st_line[first_valid] = lower_band[first_valid]

    for i in range(first_valid + 1, n):
        if np.isnan(upper_band[i]):
            continue

        # Adjust bands based on previous bands
        if lower_band[i] > lower_band[i - 1] or c[i - 1] < lower_band[i - 1]:
            pass  # keep current lower_band[i]
        else:
            lower_band[i] = lower_band[i - 1]

        if upper_band[i] < upper_band[i - 1] or c[i - 1] > upper_band[i - 1]:
            pass  # keep current upper_band[i]
        else:
            upper_band[i] = upper_band[i - 1]

        # Direction logic
        prev_dir = direction[i - 1] if not np.isnan(direction[i - 1]) else 1.0
        if prev_dir == 1.0:
            if c[i] < lower_band[i]:
                direction[i] = -1.0
                st_line[i] = upper_band[i]
            else:
                direction[i] = 1.0
                st_line[i] = lower_band[i]
        else:
            if c[i] > upper_band[i]:
                direction[i] = 1.0
                st_line[i] = lower_band[i]
            else:
                direction[i] = -1.0
                st_line[i] = upper_band[i]

    return st_line, direction


# ---------------------------------------------------------------------------
# Ichimoku Cloud
# ---------------------------------------------------------------------------

def ichimoku(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
) -> dict[str, NDArray]:
    """Ichimoku Cloud components.

    Parameters
    ----------
    high, low, close : NDArray
        Price arrays.
    tenkan : int
        Tenkan-sen (conversion line) period (default 9).
    kijun : int
        Kijun-sen (base line) period (default 26).
    senkou_b : int
        Senkou Span B period (default 52).

    Returns
    -------
    dict
        Keys: ``tenkan_sen``, ``kijun_sen``, ``senkou_span_a``,
        ``senkou_span_b``.  All same length as input.
    """
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    _c = np.asarray(close, dtype=np.float64)
    n = len(_c)

    def _donchian_mid(src_h: NDArray, src_l: NDArray, period: int) -> NDArray:
        out = np.full(n, np.nan)
        for i in range(period - 1, n):
            out[i] = (np.max(src_h[i - period + 1: i + 1])
                      + np.min(src_l[i - period + 1: i + 1])) / 2.0
        return out

    tenkan_sen = _donchian_mid(h, l, tenkan)
    kijun_sen = _donchian_mid(h, l, kijun)

    # Senkou Span A = (tenkan + kijun) / 2, shifted forward kijun periods
    span_a_raw = np.full(n, np.nan)
    valid = ~(np.isnan(tenkan_sen) | np.isnan(kijun_sen))
    span_a_raw[valid] = (tenkan_sen[valid] + kijun_sen[valid]) / 2.0
    senkou_span_a = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(span_a_raw[i]) and i + kijun < n:
            senkou_span_a[i + kijun] = span_a_raw[i]

    # Senkou Span B = donchian mid over senkou_b, shifted forward kijun periods
    span_b_raw = _donchian_mid(h, l, senkou_b)
    senkou_span_b = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(span_b_raw[i]) and i + kijun < n:
            senkou_span_b[i + kijun] = span_b_raw[i]

    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_span_a": senkou_span_a,
        "senkou_span_b": senkou_span_b,
    }


# ---------------------------------------------------------------------------
# Heikin-Ashi
# ---------------------------------------------------------------------------

def heikin_ashi(
    open_arr: NDArray,
    high: NDArray,
    low: NDArray,
    close: NDArray,
) -> tuple[NDArray, NDArray, NDArray, NDArray]:
    """Heikin-Ashi candlestick values.

    Parameters
    ----------
    open_arr, high, low, close : NDArray
        Standard OHLC arrays.

    Returns
    -------
    tuple[NDArray, NDArray, NDArray, NDArray]
        ``(ha_open, ha_high, ha_low, ha_close)``
    """
    o = np.asarray(open_arr, dtype=np.float64)
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)

    ha_close = (o + h + l + c) / 4.0
    ha_open = np.empty(n, dtype=np.float64)
    ha_open[0] = o[0]
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0

    ha_high = np.maximum(h, np.maximum(ha_open, ha_close))
    ha_low = np.minimum(l, np.minimum(ha_open, ha_close))

    return ha_open, ha_high, ha_low, ha_close


# ---------------------------------------------------------------------------
# Volume Profile
# ---------------------------------------------------------------------------

def volume_profile(
    close: NDArray,
    volume: NDArray,
    num_bins: int = 20,
) -> dict[str, Any]:
    """Volume Profile with Point of Control and Value Area.

    Parameters
    ----------
    close : NDArray
        Array of closing prices.
    volume : NDArray
        Array of volume values.
    num_bins : int
        Number of price bins (default 20).

    Returns
    -------
    dict
        Keys: ``poc`` (float), ``vah`` (float), ``val`` (float),
        ``profile`` (NDArray), ``bin_edges`` (NDArray).
    """
    c = np.asarray(close, dtype=np.float64)
    v = np.asarray(volume, dtype=np.float64)
    n = len(c)

    if n == 0 or np.all(v == 0):
        return {
            "poc": np.nan,
            "vah": np.nan,
            "val": np.nan,
            "profile": np.array([], dtype=np.float64),
            "bin_edges": np.array([], dtype=np.float64),
        }

    price_min, price_max = float(np.nanmin(c)), float(np.nanmax(c))
    if price_min == price_max:
        return {
            "poc": price_min,
            "vah": price_min,
            "val": price_min,
            "profile": np.array([float(np.nansum(v))], dtype=np.float64),
            "bin_edges": np.array([price_min, price_max], dtype=np.float64),
        }

    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    profile = np.zeros(num_bins, dtype=np.float64)
    bin_indices = np.digitize(c, bin_edges) - 1
    bin_indices = np.clip(bin_indices, 0, num_bins - 1)
    for i in range(n):
        profile[bin_indices[i]] += v[i]

    # Point of Control – price level (bin mid) with highest volume
    poc_idx = int(np.argmax(profile))
    poc = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2.0

    # Value Area – 70 % of total volume centered around POC
    total_vol = float(np.sum(profile))
    target_vol = total_vol * 0.70
    va_vol = profile[poc_idx]
    lo_idx, hi_idx = poc_idx, poc_idx
    while va_vol < target_vol and (lo_idx > 0 or hi_idx < num_bins - 1):
        expand_lo = profile[lo_idx - 1] if lo_idx > 0 else 0.0
        expand_hi = profile[hi_idx + 1] if hi_idx < num_bins - 1 else 0.0
        if expand_lo >= expand_hi and lo_idx > 0:
            lo_idx -= 1
            va_vol += profile[lo_idx]
        elif hi_idx < num_bins - 1:
            hi_idx += 1
            va_vol += profile[hi_idx]
        else:
            lo_idx -= 1
            va_vol += profile[lo_idx]

    val = (bin_edges[lo_idx] + bin_edges[lo_idx + 1]) / 2.0
    vah = (bin_edges[hi_idx] + bin_edges[hi_idx + 1]) / 2.0

    return {
        "poc": float(poc),
        "vah": float(vah),
        "val": float(val),
        "profile": profile,
        "bin_edges": bin_edges,
    }


# ---------------------------------------------------------------------------
# Keltner Channels
# ---------------------------------------------------------------------------

def keltner_channels(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> tuple[NDArray, NDArray, NDArray]:
    """Keltner Channels (EMA ± multiplier × ATR).

    Parameters
    ----------
    high, low, close : NDArray
        Price arrays.
    ema_period : int
        Period for the middle EMA line (default 20).
    atr_period : int
        Period for ATR (default 10).
    multiplier : float
        ATR multiplier for channel width (default 2.0).

    Returns
    -------
    tuple[NDArray, NDArray, NDArray]
        ``(upper, middle, lower)``
    """
    c = np.asarray(close, dtype=np.float64)
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    n = len(c)
    nan_out = np.full(n, np.nan)
    if n < max(ema_period, atr_period + 1):
        return nan_out.copy(), nan_out.copy(), nan_out.copy()

    middle = ema(c, ema_period)
    atr_arr = atr(h, l, c, atr_period)
    upper = middle + multiplier * atr_arr
    lower = middle - multiplier * atr_arr
    return upper, middle, lower


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------

def williams_r(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    period: int = 14,
) -> NDArray:
    """Williams %R oscillator (range -100 to 0).

    Parameters
    ----------
    high, low, close : NDArray
        Price arrays.
    period : int
        Look-back period (default 14).

    Returns
    -------
    NDArray
        Williams %R values, NaN-padded for insufficient data.
    """
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    out = np.full(n, np.nan)
    if n < period:
        return out

    for i in range(period - 1, n):
        hh = np.max(h[i - period + 1: i + 1])
        ll = np.min(l[i - period + 1: i + 1])
        if hh - ll == 0:
            out[i] = 0.0
        else:
            out[i] = (hh - c[i]) / (hh - ll) * -100.0
    return out


# ---------------------------------------------------------------------------
# Money Flow Index (MFI)
# ---------------------------------------------------------------------------

def mfi(
    high: NDArray,
    low: NDArray,
    close: NDArray,
    volume: NDArray,
    period: int = 14,
) -> NDArray:
    """Money Flow Index (volume-weighted RSI).

    Parameters
    ----------
    high, low, close, volume : NDArray
        Price and volume arrays.
    period : int
        Look-back period (default 14).

    Returns
    -------
    NDArray
        MFI values (0-100), NaN-padded for insufficient data.
    """
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    v = np.asarray(volume, dtype=np.float64)
    n = len(c)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out

    tp = (h + l + c) / 3.0
    raw_mf = tp * v

    for i in range(period, n):
        pos_flow = 0.0
        neg_flow = 0.0
        for j in range(i - period + 1, i + 1):
            if tp[j] > tp[j - 1]:
                pos_flow += raw_mf[j]
            elif tp[j] < tp[j - 1]:
                neg_flow += raw_mf[j]
        if neg_flow == 0:
            out[i] = 100.0
        else:
            ratio = pos_flow / neg_flow
            out[i] = 100.0 - 100.0 / (1.0 + ratio)
    return out
