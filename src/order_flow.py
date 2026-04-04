"""Order-flow analytics: Open Interest, Liquidations, and CVD Divergence.

Provides institutional-grade signal confirmation tools:

* **OI Trend** – classifies whether open interest is rising (new positions) or
  falling (position closures / liquidations) to distinguish genuine breakouts
  from stop-hunts.
* **Liquidations** – tracks forced position-closure events from the Binance
  Futures ``forceOrder`` stream so squeeze scenarios can be identified.
* **CVD Divergence** – detects divergence between Cumulative Volume Delta and
  price (e.g. price makes a lower low but CVD a higher low → bullish divergence,
  suggesting smart money is absorbing selling pressure).

Validation logic
----------------
A *bullish* Liquidity Sweep (price dips below a low and recovers) is only
considered high-quality when:

1. Open Interest is **falling** – signals that existing positions are being
   closed / liquidated rather than aggressive new shorts entering the market.
2. Meaningful **liquidation volume** has occurred in the recent window – further
   evidence that the sweep was a stop-hunt rather than a genuine breakdown.

If Open Interest is **rising** during a sweep in the opposite direction to the
proposed signal, the signal should be **invalidated** (e.g. OI rising while
price sweeps downward indicates aggressive new shorts; a long signal here is
unlikely to succeed).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

import aiohttp
import numpy as np

from src.utils import get_logger

log = get_logger("order_flow")

# Maximum number of OI snapshots kept per symbol.
# At one snapshot per minute this covers ~3 hours.
_OI_HISTORY_SIZE: int = 200

# Maximum number of liquidation events kept per symbol.
_LIQ_HISTORY_SIZE: int = 500

# Maximum number of per-candle CVD snapshots kept per symbol.
_CVD_HISTORY_SIZE: int = 500

# Default OI REST polling interval (seconds).
OI_POLL_INTERVAL: float = 60.0

# Minimum OI change (%) to classify trend as RISING or FALLING.
_OI_CHANGE_THRESHOLD_PCT: float = 0.5


class OITrend(str, Enum):
    """Classification of recent open-interest direction."""
    RISING = "RISING"
    FALLING = "FALLING"
    NEUTRAL = "NEUTRAL"


@dataclass
class OISnapshot:
    """A single open-interest reading."""
    timestamp: float   # time.monotonic()
    open_interest: float  # OI in base-asset units


@dataclass
class LiquidationEvent:
    """A single forced-order (liquidation) event from the ``forceOrder`` stream."""
    timestamp: float   # time.monotonic()
    symbol: str
    side: str          # "BUY" = short position liq'd; "SELL" = long position liq'd
    qty: float         # quantity liquidated (base asset)
    price: float       # average fill price


# ---------------------------------------------------------------------------
# Pure functions (no I/O, easily unit-testable)
# ---------------------------------------------------------------------------

def classify_oi_trend(
    snapshots: List[OISnapshot],
    lookback: int = 5,
) -> OITrend:
    """Classify OI as RISING / FALLING / NEUTRAL using the last *lookback* snapshots.

    A change of at least :data:`_OI_CHANGE_THRESHOLD_PCT` % is required to
    avoid noise-driven mis-classification on nearly flat OI.

    Parameters
    ----------
    snapshots:
        Ordered list of OI readings (oldest first).
    lookback:
        Number of most-recent snapshots to compare against the earliest in the
        window.  Defaults to 5.

    Returns
    -------
    OITrend
        ``FALLING`` when OI has dropped ≥ threshold, ``RISING`` when it has
        increased ≥ threshold, otherwise ``NEUTRAL``.
    """
    if len(snapshots) < 2:
        return OITrend.NEUTRAL

    recent = snapshots[-lookback:]
    if len(recent) < 2:
        return OITrend.NEUTRAL

    first_oi = recent[0].open_interest
    last_oi = recent[-1].open_interest
    if first_oi <= 0:
        return OITrend.NEUTRAL

    change_pct = (last_oi - first_oi) / first_oi * 100.0
    if change_pct <= -_OI_CHANGE_THRESHOLD_PCT:
        return OITrend.FALLING
    if change_pct >= _OI_CHANGE_THRESHOLD_PCT:
        return OITrend.RISING
    return OITrend.NEUTRAL


def is_squeeze(
    oi_trend: OITrend,
    liq_vol_usd: float,
    liq_threshold_usd: float = 0.0,
) -> bool:
    """Return ``True`` when a *squeeze* (stop-hunt) scenario is confirmed.

    A squeeze is defined as OI falling **and** meaningful liquidation volume
    occurring within the recent time window.  This combination indicates that
    the sweep candle was forcing existing position-holders to close rather than
    attracting fresh sellers / buyers.

    Parameters
    ----------
    oi_trend:
        Current OI trend classification.
    liq_vol_usd:
        Total USD value of liquidations in the recent window.
    liq_threshold_usd:
        Minimum USD liquidation volume required.  Defaults to 0 (any liquidation
        activity is sufficient when OI is falling).
    """
    return (
        oi_trend == OITrend.FALLING
        and liq_vol_usd > liq_threshold_usd
    )


def is_oi_invalidated(
    oi_trend: OITrend,
    signal_direction: str,
    oi_change_pct: float = 0.0,
) -> bool:
    """Return ``True`` when rising OI contradicts the proposed signal direction.

    Rising OI during a bearish sweep (price dipping below a low) signals that
    **new shorts** are aggressively entering – a long signal fired here will
    fight the incoming trend.  Similarly, rising OI during a bullish sweep
    indicates new longs piling in, which can front-run a reversal downward.

    Small OI moves (below 1%) are treated as market noise and will NOT
    invalidate the signal.  This prevents spurious rejections on Binance
    perpetuals where OI fluctuates by sub-1% amounts between every kline.

    Parameters
    ----------
    oi_trend:
        Current OI trend classification.
    signal_direction:
        ``"LONG"`` or ``"SHORT"``.
    oi_change_pct:
        Fractional OI change magnitude (e.g. ``0.015`` = 1.5%).  When the
        absolute value is below 0.01 (1%) the change is treated as noise and
        the signal is not invalidated.
    """
    if oi_trend != OITrend.RISING:
        return False
    # Only invalidate if the OI rise is significant (> 1%)
    return abs(oi_change_pct) >= 0.01


def detect_cvd_divergence(
    close: np.ndarray,
    cvd: np.ndarray,
    lookback: int = 20,
) -> Optional[str]:
    """Detect CVD / price divergence over the last *lookback* candles.

    Compares the first and second halves of the window to identify divergence
    between price extremes and CVD extremes.

    Returns
    -------
    ``"BULLISH"``
        Price makes a lower low in the second half of the window but CVD makes
        a higher low → smart money is quietly absorbing sell pressure.
    ``"BEARISH"``
        Price makes a higher high in the second half but CVD makes a lower high
        → distribution / hidden selling into strength.
    ``None``
        No clear divergence detected.
    """
    if len(close) < lookback or len(cvd) < lookback:
        return None

    price_window = np.asarray(close[-lookback:], dtype=np.float64)
    cvd_window = np.asarray(cvd[-lookback:], dtype=np.float64)

    if len(price_window) < 4:
        return None

    half = len(price_window) // 2

    # ------------------------------------------------------------------
    # Bullish divergence: price lower low + CVD higher low
    # ------------------------------------------------------------------
    price_first_low = float(np.min(price_window[:half]))
    price_second_low = float(np.min(price_window[half:]))
    cvd_first_low = float(np.min(cvd_window[:half]))
    cvd_second_low = float(np.min(cvd_window[half:]))

    if price_second_low < price_first_low and cvd_second_low > cvd_first_low:
        return "BULLISH"

    # ------------------------------------------------------------------
    # Bearish divergence: price higher high + CVD lower high
    # ------------------------------------------------------------------
    price_first_high = float(np.max(price_window[:half]))
    price_second_high = float(np.max(price_window[half:]))
    cvd_first_high = float(np.max(cvd_window[:half]))
    cvd_second_high = float(np.max(cvd_window[half:]))

    if price_second_high > price_first_high and cvd_second_high < cvd_first_high:
        return "BEARISH"

    return None


# ---------------------------------------------------------------------------
# OrderFlowStore – per-symbol mutable state
# ---------------------------------------------------------------------------

class OrderFlowStore:
    """Stores and queries per-symbol open-interest, liquidation, and CVD data.

    Thread-safe for single-threaded asyncio use (no locking needed).

    Typical lifecycle
    -----------------
    1. :meth:`add_oi_snapshot` – called by :class:`OIPoller` every minute.
    2. :meth:`add_liquidation` – called by the WS message handler on every
       ``forceOrder`` event.
    3. :meth:`update_cvd_from_tick` – called by the WS message handler on every
       ``trade`` event.
    4. :meth:`snapshot_cvd_at_candle_close` – called on every closed kline to
       align CVD with candle boundaries for divergence detection.
    5. :meth:`get_oi_trend` / :meth:`get_recent_liq_volume_usd` /
       :meth:`get_cvd_divergence` – queried by :class:`src.detector.SMCDetector`
       during the scan cycle.
    """

    def __init__(self) -> None:
        self._oi: Dict[str, Deque[OISnapshot]] = {}
        self._liqs: Dict[str, Deque[LiquidationEvent]] = {}
        # Running CVD (in quote-currency units) per symbol – reset-free rolling sum
        self._running_cvd: Dict[str, float] = {}
        # CVD values snapshotted at each candle close (candle-aligned for divergence)
        self._cvd_candle: Dict[str, Deque[float]] = {}

    # ------------------------------------------------------------------
    # OI
    # ------------------------------------------------------------------

    def add_oi_snapshot(self, symbol: str, open_interest: float) -> None:
        """Record a new OI reading for *symbol*."""
        if symbol not in self._oi:
            self._oi[symbol] = deque(maxlen=_OI_HISTORY_SIZE)
        self._oi[symbol].append(
            OISnapshot(timestamp=time.monotonic(), open_interest=open_interest)
        )

    def get_oi_trend(self, symbol: str, lookback: int = 5) -> OITrend:
        """Return the current OI trend for *symbol*."""
        snaps = list(self._oi.get(symbol, []))
        return classify_oi_trend(snaps, lookback)

    def get_oi_change_pct(self, symbol: str, lookback: int = 5) -> float:
        """Return the fractional OI change over the last *lookback* snapshots.

        Returns ``0.0`` when insufficient data is available.  The value is a
        fraction (e.g. ``0.015`` = 1.5% increase), consistent with the
        ``oi_change_pct`` parameter of :func:`is_oi_invalidated`.
        """
        snaps = list(self._oi.get(symbol, []))
        if len(snaps) < 2:
            return 0.0
        recent = snaps[-lookback:]
        if len(recent) < 2:
            return 0.0
        first_oi = recent[0].open_interest
        last_oi = recent[-1].open_interest
        if first_oi <= 0:
            return 0.0
        return (last_oi - first_oi) / first_oi

    # ------------------------------------------------------------------
    # Liquidations
    # ------------------------------------------------------------------

    def add_liquidation(self, event: LiquidationEvent) -> None:
        """Record a liquidation event."""
        sym = event.symbol
        if sym not in self._liqs:
            self._liqs[sym] = deque(maxlen=_LIQ_HISTORY_SIZE)
        self._liqs[sym].append(event)

    def get_recent_liq_volume_usd(
        self,
        symbol: str,
        window_seconds: float = 300.0,
        side: Optional[str] = None,
    ) -> float:
        """Total USD liquidation volume for *symbol* in the last *window_seconds*.

        Parameters
        ----------
        symbol:
            Trading pair symbol (uppercase, e.g. ``"BTCUSDT"``).
        window_seconds:
            Look-back window in seconds.  Defaults to 5 minutes.
        side:
            Optional side filter – ``"BUY"`` (short liq'd), ``"SELL"`` (long
            liq'd), or ``None`` for both.
        """
        evts: Deque[LiquidationEvent] = self._liqs.get(symbol, deque())
        cutoff = time.monotonic() - window_seconds
        total = 0.0
        for e in evts:
            if e.timestamp < cutoff:
                continue
            if side is not None and e.side != side:
                continue
            total += e.qty * e.price
        return total

    # ------------------------------------------------------------------
    # CVD
    # ------------------------------------------------------------------

    def update_cvd_from_tick(
        self,
        symbol: str,
        buy_vol_usd: float,
        sell_vol_usd: float,
    ) -> None:
        """Update the running CVD from a single trade tick.

        Parameters
        ----------
        symbol:
            Trading pair symbol (uppercase).
        buy_vol_usd:
            Quote-currency volume of the aggressive *buy* side of the tick
            (``qty × price`` when ``isBuyerMaker == False``).
        sell_vol_usd:
            Quote-currency volume of the aggressive *sell* side of the tick
            (``qty × price`` when ``isBuyerMaker == True``).
        """
        delta = buy_vol_usd - sell_vol_usd
        self._running_cvd[symbol] = self._running_cvd.get(symbol, 0.0) + delta

    def snapshot_cvd_at_candle_close(self, symbol: str) -> None:
        """Record the current CVD value at a candle-close boundary.

        Call this from the kline WebSocket handler whenever a closed candle
        (``k.x == True``) is received.  Aligns CVD snapshots with candle
        boundaries so that :meth:`get_cvd_divergence` can compare CVD and price
        on the same time grid.
        """
        if symbol not in self._cvd_candle:
            self._cvd_candle[symbol] = deque(maxlen=_CVD_HISTORY_SIZE)
        self._cvd_candle[symbol].append(
            self._running_cvd.get(symbol, 0.0)
        )

    def get_cvd_history(self, symbol: str) -> np.ndarray:
        """Return the candle-aligned CVD history as a numpy array."""
        hist = self._cvd_candle.get(symbol, deque())
        return np.array(list(hist), dtype=np.float64)

    def get_cvd_divergence(
        self,
        symbol: str,
        close: np.ndarray,
        lookback: int = 20,
    ) -> Optional[str]:
        """Detect CVD divergence vs price for *symbol*.

        Aligns the CVD candle history with the tail of *close* (shortest
        length wins) before calling :func:`detect_cvd_divergence`.

        Returns ``"BULLISH"``, ``"BEARISH"``, or ``None``.
        """
        cvd = self.get_cvd_history(symbol)
        min_len = min(len(close), len(cvd))
        if min_len < lookback:
            return None
        return detect_cvd_divergence(
            close[-min_len:], cvd[-min_len:], lookback
        )


# ---------------------------------------------------------------------------
# OIPoller – async REST polling for Binance Futures OI
# ---------------------------------------------------------------------------

class OIPoller:
    """Background task that polls Binance Futures REST for Open Interest data.

    Polls ``/fapi/v1/openInterest`` for each tracked futures symbol every
    :attr:`interval` seconds and writes results to an :class:`OrderFlowStore`.

    Parameters
    ----------
    store:
        Shared :class:`OrderFlowStore` instance.
    futures_rest_base:
        Binance Futures REST base URL (e.g. ``"https://fapi.binance.com"``).
    interval:
        Polling interval in seconds.  Defaults to :data:`OI_POLL_INTERVAL`.
    """

    def __init__(
        self,
        store: OrderFlowStore,
        futures_rest_base: str,
        interval: float = OI_POLL_INTERVAL,
    ) -> None:
        self._store = store
        self._base = futures_rest_base.rstrip("/")
        self._interval = interval
        self._symbols: List[str] = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None

    def set_symbols(self, symbols: List[str]) -> None:
        """Set the futures symbols to poll."""
        self._symbols = list(symbols)

    async def start(self) -> None:
        """Start the polling loop in the background."""
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._poll_loop())
        log.info("OIPoller started for {} symbols (interval={}s)", len(self._symbols), self._interval)

    async def stop(self) -> None:
        """Cancel the polling loop and close the HTTP session."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._task = None

    async def _poll_loop(self) -> None:
        assert self._session is not None
        try:
            while True:
                for sym in list(self._symbols):
                    await self._fetch_oi(sym)
                    await asyncio.sleep(0.1)  # brief gap between requests
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    async def _fetch_oi(self, symbol: str) -> None:
        assert self._session is not None
        url = f"{self._base}/fapi/v1/openInterest"
        try:
            async with self._session.get(
                url,
                params={"symbol": symbol},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    log.debug("OI fetch {} status {}", symbol, resp.status)
                    return
                data: Any = await resp.json()
                oi_str = data.get("openInterest")
                if oi_str is None:
                    return
                self._store.add_oi_snapshot(symbol, float(oi_str))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("OI fetch error for {}: {}", symbol, exc)


# ---------------------------------------------------------------------------
# Additional order-flow analytics
# ---------------------------------------------------------------------------


def detect_absorption(
    trades_or_ticks: Optional[List[Dict[str, Any]]] = None,
    window: int = 20,
) -> Dict[str, Any]:
    """Detect absorption: large volume at a price level without proportional price movement.

    Absorption occurs when significant volume is transacted at a tight price
    range (< 0.1 % width) – indicating a large passive participant absorbing
    aggressive flow – yet price fails to move through that level.

    Parameters
    ----------
    trades_or_ticks:
        List of dicts with ``'price'``, ``'qty'``, ``'is_buyer'`` keys.
    window:
        Number of most-recent ticks to analyse.

    Returns
    -------
    dict with ``detected``, ``side``, ``volume_absorbed``, ``price_level``,
    ``strength`` (0–1).
    """
    neutral: Dict[str, Any] = {
        "detected": False,
        "side": "NONE",
        "volume_absorbed": 0.0,
        "price_level": 0.0,
        "strength": 0.0,
    }

    if not trades_or_ticks:
        return neutral

    ticks = trades_or_ticks[-window:]
    if len(ticks) < 2:
        return neutral

    try:
        prices = np.array([float(t["price"]) for t in ticks], dtype=np.float64)
        qtys = np.array([float(t["qty"]) for t in ticks], dtype=np.float64)
        sides = [bool(t["is_buyer"]) for t in ticks]
    except (KeyError, TypeError, ValueError):
        return neutral

    mid_price = (prices.min() + prices.max()) / 2.0
    if mid_price <= 0:
        return neutral

    price_range_pct = (prices.max() - prices.min()) / mid_price

    # Volume per price level (rounded to 4 decimal places for grouping)
    vol_by_price: Dict[float, float] = {}
    buy_vol_by_price: Dict[float, float] = {}
    sell_vol_by_price: Dict[float, float] = {}
    for p, q, is_buy in zip(prices, qtys, sides):
        rp = round(float(p), 4)
        vol_by_price[rp] = vol_by_price.get(rp, 0.0) + float(q)
        if is_buy:
            buy_vol_by_price[rp] = buy_vol_by_price.get(rp, 0.0) + float(q)
        else:
            sell_vol_by_price[rp] = sell_vol_by_price.get(rp, 0.0) + float(q)

    total_vol = float(qtys.sum())
    if total_vol <= 0:
        return neutral

    # Find the price level with the most volume
    top_price = max(vol_by_price, key=vol_by_price.get)  # type: ignore[arg-type]
    top_vol = vol_by_price[top_price]

    # Absorption = top-level volume is in the top 20 % AND price range is tight
    vol_concentration = top_vol / total_vol
    is_concentrated = vol_concentration >= 0.20
    is_tight_range = price_range_pct < 0.001  # < 0.1 %

    if not (is_concentrated and is_tight_range):
        return neutral

    buy_at_level = buy_vol_by_price.get(top_price, 0.0)
    sell_at_level = sell_vol_by_price.get(top_price, 0.0)
    side = "BUY" if buy_at_level >= sell_at_level else "SELL"

    strength = min(1.0, vol_concentration / 0.5)  # normalise: 50 %+ → 1.0

    return {
        "detected": True,
        "side": side,
        "volume_absorbed": top_vol,
        "price_level": top_price,
        "strength": round(strength, 4),
    }


def classify_aggressive_passive(
    trades_or_ticks: Optional[List[Dict[str, Any]]] = None,
    window: int = 50,
) -> Dict[str, Any]:
    """Classify recent trades as aggressive (market orders) vs passive (limit fills).

    An aggressive buy is a trade where the buyer is the taker (``is_buyer=True``),
    and an aggressive sell is where the seller is the taker (``is_buyer=False``).

    Parameters
    ----------
    trades_or_ticks:
        List of dicts with ``'price'``, ``'qty'``, ``'is_buyer'``, ``'time'`` keys.
    window:
        Number of most-recent trades to consider.

    Returns
    -------
    dict with ``aggressive_buy_pct``, ``aggressive_sell_pct``, ``passive_pct``,
    ``net_aggression`` (−1 to 1), ``sample_size``.
    """
    neutral: Dict[str, Any] = {
        "aggressive_buy_pct": 0.0,
        "aggressive_sell_pct": 0.0,
        "passive_pct": 1.0,
        "net_aggression": 0.0,
        "sample_size": 0,
    }

    if not trades_or_ticks:
        return neutral

    ticks = trades_or_ticks[-window:]
    if not ticks:
        return neutral

    agg_buy_vol = 0.0
    agg_sell_vol = 0.0
    total_vol = 0.0

    for t in ticks:
        try:
            qty = float(t["qty"])
            is_buyer = bool(t["is_buyer"])
        except (KeyError, TypeError, ValueError):
            continue

        total_vol += qty
        if is_buyer:
            agg_buy_vol += qty
        else:
            agg_sell_vol += qty

    if total_vol <= 0:
        return neutral

    agg_buy_pct = agg_buy_vol / total_vol
    agg_sell_pct = agg_sell_vol / total_vol
    passive_pct = max(0.0, 1.0 - agg_buy_pct - agg_sell_pct)
    net_aggression = agg_buy_pct - agg_sell_pct  # −1 to 1

    return {
        "aggressive_buy_pct": round(agg_buy_pct, 4),
        "aggressive_sell_pct": round(agg_sell_pct, 4),
        "passive_pct": round(passive_pct, 4),
        "net_aggression": round(max(-1.0, min(1.0, net_aggression)), 4),
        "sample_size": len(ticks),
    }


def track_whale_orders(
    trades_or_ticks: Optional[List[Dict[str, Any]]] = None,
    threshold_usd: float = 50_000,
) -> Dict[str, Any]:
    """Identify whale-size orders (single trade > *threshold_usd*).

    Parameters
    ----------
    trades_or_ticks:
        List of dicts with ``'price'``, ``'qty'``, ``'is_buyer'`` keys.
    threshold_usd:
        USD notional threshold for a trade to be classified as a whale order.

    Returns
    -------
    dict with ``whale_buy_count``, ``whale_sell_count``, ``whale_buy_volume_usd``,
    ``whale_sell_volume_usd``, ``net_whale_flow``, ``whale_imbalance`` (−1 to 1).
    """
    neutral: Dict[str, Any] = {
        "whale_buy_count": 0,
        "whale_sell_count": 0,
        "whale_buy_volume_usd": 0.0,
        "whale_sell_volume_usd": 0.0,
        "net_whale_flow": 0.0,
        "whale_imbalance": 0.0,
    }

    if not trades_or_ticks:
        return neutral

    whale_buy_count = 0
    whale_sell_count = 0
    whale_buy_vol = 0.0
    whale_sell_vol = 0.0

    for t in trades_or_ticks:
        try:
            price = float(t["price"])
            qty = float(t["qty"])
            is_buyer = bool(t["is_buyer"])
        except (KeyError, TypeError, ValueError):
            continue

        notional = price * qty
        if notional <= threshold_usd:
            continue

        if is_buyer:
            whale_buy_count += 1
            whale_buy_vol += notional
        else:
            whale_sell_count += 1
            whale_sell_vol += notional

    total_whale = whale_buy_vol + whale_sell_vol
    net_flow = whale_buy_vol - whale_sell_vol
    imbalance = (net_flow / total_whale) if total_whale > 0 else 0.0

    return {
        "whale_buy_count": whale_buy_count,
        "whale_sell_count": whale_sell_count,
        "whale_buy_volume_usd": round(whale_buy_vol, 2),
        "whale_sell_volume_usd": round(whale_sell_vol, 2),
        "net_whale_flow": round(net_flow, 2),
        "whale_imbalance": round(max(-1.0, min(1.0, imbalance)), 4),
    }


def compute_delta_divergence(
    closes: Optional[List[float]] = None,
    buy_volumes: Optional[List[float]] = None,
    sell_volumes: Optional[List[float]] = None,
    lookback: int = 20,
) -> Dict[str, Any]:
    """Detect delta divergence: price trending one way but volume delta trending opposite.

    Compares the linear trend of price and cumulative volume delta over the
    last *lookback* bars.  A divergence exists when the two trends move in
    opposite directions.

    Parameters
    ----------
    closes:
        List of close prices (oldest → newest).
    buy_volumes:
        List of per-bar buy volumes (same length as *closes*).
    sell_volumes:
        List of per-bar sell volumes (same length as *closes*).
    lookback:
        Number of bars to analyse.

    Returns
    -------
    dict with ``divergence`` (``"BULLISH"`` / ``"BEARISH"`` / ``"NONE"``),
    ``price_trend``, ``delta_trend``, ``strength`` (0–1).
    """
    neutral: Dict[str, Any] = {
        "divergence": "NONE",
        "price_trend": "NONE",
        "delta_trend": "NONE",
        "strength": 0.0,
    }

    if not closes or not buy_volumes or not sell_volumes:
        return neutral

    n = min(len(closes), len(buy_volumes), len(sell_volumes), lookback)
    if n < 4:
        return neutral

    c = np.array(closes[-n:], dtype=np.float64)
    bv = np.array(buy_volumes[-n:], dtype=np.float64)
    sv = np.array(sell_volumes[-n:], dtype=np.float64)

    deltas = bv - sv
    cum_delta = np.cumsum(deltas)

    x = np.arange(n, dtype=np.float64)
    # Linear regression slopes
    price_slope = float(np.polyfit(x, c, 1)[0])
    delta_slope = float(np.polyfit(x, cum_delta, 1)[0])

    # Normalise slopes for comparison
    price_range = float(c.max() - c.min())
    delta_range = float(cum_delta.max() - cum_delta.min())

    if price_range <= 0 or delta_range <= 0:
        return neutral

    norm_price = price_slope / price_range
    norm_delta = delta_slope / delta_range

    if norm_price > 0.05:
        price_trend = "UP"
    elif norm_price < -0.05:
        price_trend = "DOWN"
    else:
        price_trend = "FLAT"

    if norm_delta > 0.05:
        delta_trend = "UP"
    elif norm_delta < -0.05:
        delta_trend = "DOWN"
    else:
        delta_trend = "FLAT"

    divergence = "NONE"
    if price_trend == "DOWN" and delta_trend == "UP":
        divergence = "BULLISH"
    elif price_trend == "UP" and delta_trend == "DOWN":
        divergence = "BEARISH"

    # Strength = how far apart the normalised slopes are (max 1.0)
    strength = min(1.0, abs(norm_price - norm_delta))

    return {
        "divergence": divergence,
        "price_trend": price_trend,
        "delta_trend": delta_trend,
        "strength": round(strength, 4),
    }
