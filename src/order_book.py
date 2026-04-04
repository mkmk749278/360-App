"""Order Book Imbalance (OBI) execution filter.

Provides utilities to calculate bid/ask depth imbalance and act as the
final execution gate before a trade signal goes live.  If the order book
is heavily stacked against the signal direction the trade is rejected to
avoid buying into a wall of sellers (or selling into a wall of buyers).

Usage
-----
::

    from src.order_book import check_order_book_execution

    allowed, reason = check_order_book_execution(
        direction="LONG",
        order_book={"bids": [...], "asks": [...]},
    )
    if not allowed:
        log.warning("Trade blocked: {}", reason)

Graceful fallback
-----------------
If ``order_book`` is ``None`` or contains insufficient data the filter
*fails open* – the trade is allowed through without crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from src.utils import get_logger

log = get_logger("order_book")

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

#: If the opposing side represents more than this fraction of total order book
#: volume, the signal is rejected.
#:
#: * For a LONG signal: if asks_pct > threshold → reject (too many sellers)
#: * For a SHORT signal: if bids_pct > threshold → reject (too many buyers)
OBI_REJECTION_THRESHOLD: float = 0.65  # 65%

#: Number of depth levels (from each side) to include in the calculation.
OBI_DEFAULT_LEVELS: int = 20


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Computed metrics from a single order book depth snapshot."""

    bid_volume: float       # USD-weighted total bid depth
    ask_volume: float       # USD-weighted total ask depth
    total_volume: float     # bid_volume + ask_volume
    bid_pct: float          # fraction of total that is bids  (0-1)
    ask_pct: float          # fraction of total that is asks  (0-1)
    imbalance_ratio: float  # dominant_vol / weak_vol  (≥ 1.0)
    dominant_side: str      # "bids" | "asks" | "balanced"


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------


def calculate_order_book_imbalance(
    bids: Sequence,
    asks: Sequence,
    levels: int = OBI_DEFAULT_LEVELS,
) -> Optional[OrderBookSnapshot]:
    """Compute bid/ask volume imbalance from raw order book depth data.

    Each entry in *bids* / *asks* must be a sequence ``[price, quantity]``
    where both values are numeric or string-encoded floats.

    Parameters
    ----------
    bids:
        Best bids list, ordered highest price first.  Each element is
        ``[price, qty]``.
    asks:
        Best asks list, ordered lowest price first.  Each element is
        ``[price, qty]``.
    levels:
        Maximum number of levels to consume from each side.

    Returns
    -------
    :class:`OrderBookSnapshot` or ``None`` when data is insufficient.
    """
    if not bids or not asks:
        return None

    try:
        bid_vol: float = sum(
            float(b[0]) * float(b[1]) for b in bids[:levels]
        )
        ask_vol: float = sum(
            float(a[0]) * float(a[1]) for a in asks[:levels]
        )
    except (IndexError, TypeError, ValueError) as exc:
        log.debug("OBI calculation error: {}", exc)
        return None

    total = bid_vol + ask_vol
    if total <= 0:
        return None

    bid_pct = bid_vol / total
    ask_pct = ask_vol / total

    weak = min(bid_vol, ask_vol)
    ratio = (max(bid_vol, ask_vol) / weak) if weak > 0 else 0.0

    if bid_vol > ask_vol:
        dominant = "bids"
    elif ask_vol > bid_vol:
        dominant = "asks"
    else:
        dominant = "balanced"

    return OrderBookSnapshot(
        bid_volume=bid_vol,
        ask_volume=ask_vol,
        total_volume=total,
        bid_pct=bid_pct,
        ask_pct=ask_pct,
        imbalance_ratio=round(ratio, 4),
        dominant_side=dominant,
    )


# ---------------------------------------------------------------------------
# Execution gate
# ---------------------------------------------------------------------------


def check_order_book_execution(
    direction: str,
    order_book: Optional[dict],
    rejection_threshold: float = OBI_REJECTION_THRESHOLD,
    levels: int = OBI_DEFAULT_LEVELS,
) -> Tuple[bool, str]:
    """Determine whether order book conditions support executing a signal.

    This is designed to be the **final execution filter** – called just
    before a signal is dispatched to the exchange.  It returns ``(True, "")``
    in all cases where data is missing so the system *fails open* rather
    than silently blocking trades due to data gaps.

    Parameters
    ----------
    direction:
        ``"LONG"`` or ``"SHORT"``.
    order_book:
        Dict with ``"bids"`` and ``"asks"`` keys containing depth lists.
        ``None`` or missing keys → fails open (returns ``True``).
    rejection_threshold:
        Fraction of total book volume.  If the opposing side exceeds this
        fraction the signal is rejected.  Default: ``0.65`` (65 %).
    levels:
        Number of depth levels to evaluate from each side.

    Returns
    -------
    ``(allowed, reason)`` where *allowed* is ``False`` only when the book
    clearly opposes the signal direction above the threshold.

    Examples
    --------
    >>> # Asks dominate 70 % of the book – LONG rejected
    >>> check_order_book_execution("LONG", {"bids": [...], "asks": [...]})
    (False, 'OBI: ask wall 70% > 65% threshold – LONG blocked')

    >>> # Data unavailable – trade allowed through
    >>> check_order_book_execution("LONG", None)
    (True, '')
    """
    if order_book is None:
        return True, ""

    bids: List = order_book.get("bids", [])
    asks: List = order_book.get("asks", [])

    snapshot = calculate_order_book_imbalance(bids, asks, levels)
    if snapshot is None:
        # Insufficient data – fail open
        return True, ""

    if direction == "LONG" and snapshot.ask_pct > rejection_threshold:
        return (
            False,
            (
                f"OBI: ask wall {snapshot.ask_pct:.0%} > "
                f"{rejection_threshold:.0%} threshold – LONG blocked"
            ),
        )

    if direction == "SHORT" and snapshot.bid_pct > rejection_threshold:
        return (
            False,
            (
                f"OBI: bid wall {snapshot.bid_pct:.0%} > "
                f"{rejection_threshold:.0%} threshold – SHORT blocked"
            ),
        )

    return True, ""


# ---------------------------------------------------------------------------
# Additional order-book analytics
# ---------------------------------------------------------------------------


def detect_order_book_walls(
    bids: Optional[Sequence] = None,
    asks: Optional[Sequence] = None,
    close_price: Optional[float] = None,
    wall_multiplier: float = 5.0,
) -> dict:
    """Detect large buy/sell walls in the order book.

    A "wall" is a price level whose quantity exceeds *wall_multiplier* × the
    average quantity across all levels on that side.

    Parameters
    ----------
    bids:
        Best bids list (highest price first), each ``[price, qty]``.
    asks:
        Best asks list (lowest price first), each ``[price, qty]``.
    close_price:
        Current close / last-trade price (used for distance calculations).
    wall_multiplier:
        A level must have this many × the average qty to be classified as a wall.

    Returns
    -------
    dict with ``bid_walls``, ``ask_walls`` (lists of wall dicts), and
    ``nearest_bid_wall``, ``nearest_ask_wall`` (price or ``None``).
    """
    result: dict = {
        "bid_walls": [],
        "ask_walls": [],
        "nearest_bid_wall": None,
        "nearest_ask_wall": None,
    }

    if not bids and not asks:
        return result
    if close_price is None or close_price <= 0:
        return result

    def _find_walls(levels: Sequence) -> List[dict]:
        if not levels:
            return []
        try:
            parsed = [(float(lv[0]), float(lv[1])) for lv in levels]
        except (IndexError, TypeError, ValueError):
            return []
        if not parsed:
            return []
        avg_qty = sum(q for _, q in parsed) / len(parsed)
        if avg_qty <= 0:
            return []
        threshold = avg_qty * wall_multiplier
        walls: List[dict] = []
        for price, qty in parsed:
            if qty >= threshold and close_price > 0:
                dist_pct = abs(price - close_price) / close_price * 100.0
                walls.append({
                    "price": price,
                    "qty": qty,
                    "distance_pct": round(dist_pct, 4),
                })
        return walls

    bid_walls = _find_walls(bids or [])
    ask_walls = _find_walls(asks or [])

    result["bid_walls"] = bid_walls
    result["ask_walls"] = ask_walls
    if bid_walls:
        result["nearest_bid_wall"] = max(w["price"] for w in bid_walls)
    if ask_walls:
        result["nearest_ask_wall"] = min(w["price"] for w in ask_walls)

    return result


def compute_depth_ratio(
    bids: Optional[Sequence] = None,
    asks: Optional[Sequence] = None,
    depth_levels: int = 5,
) -> dict:
    """Compute near-touch depth ratio (bid vs ask volume in top *N* levels).

    Parameters
    ----------
    bids:
        Best bids list (highest price first), each ``[price, qty]``.
    asks:
        Best asks list (lowest price first), each ``[price, qty]``.
    depth_levels:
        Number of levels from each side to include.

    Returns
    -------
    dict with ``bid_depth_usd``, ``ask_depth_usd``, ``depth_ratio`` (>1 = bid
    heavy), ``imbalance_pct``.
    """
    neutral: dict = {
        "bid_depth_usd": 0.0,
        "ask_depth_usd": 0.0,
        "depth_ratio": 1.0,
        "imbalance_pct": 0.0,
    }

    if not bids and not asks:
        return neutral

    try:
        bid_usd = sum(
            float(b[0]) * float(b[1]) for b in (bids or [])[:depth_levels]
        )
        ask_usd = sum(
            float(a[0]) * float(a[1]) for a in (asks or [])[:depth_levels]
        )
    except (IndexError, TypeError, ValueError):
        return neutral

    total = bid_usd + ask_usd
    if total <= 0:
        return neutral

    ratio = (bid_usd / ask_usd) if ask_usd > 0 else float("inf")
    imbalance_pct = (bid_usd - ask_usd) / total * 100.0

    return {
        "bid_depth_usd": round(bid_usd, 2),
        "ask_depth_usd": round(ask_usd, 2),
        "depth_ratio": round(ratio, 4),
        "imbalance_pct": round(imbalance_pct, 2),
    }


def detect_iceberg_orders(
    bids: Optional[Sequence] = None,
    asks: Optional[Sequence] = None,
    close_price: Optional[float] = None,
) -> dict:
    """Heuristic detection of potential iceberg orders.

    Icebergs are detected by looking for unusually frequent *same-size*
    quantities clustered at similar price levels within each side of the
    book.  A high count of identical quantities in a narrow price band
    suggests a single participant refilling a hidden order.

    Parameters
    ----------
    bids:
        Best bids list (highest price first), each ``[price, qty]``.
    asks:
        Best asks list (lowest price first), each ``[price, qty]``.
    close_price:
        Current close / last-trade price (used for proximity checks).

    Returns
    -------
    dict with ``detected``, ``side`` (``"BID"`` / ``"ASK"`` / ``"NONE"``),
    ``suspected_levels``, ``confidence`` (0–1).
    """
    neutral: dict = {
        "detected": False,
        "side": "NONE",
        "suspected_levels": 0,
        "confidence": 0.0,
    }

    if not bids and not asks:
        return neutral

    def _check_side(levels: Sequence) -> Tuple[int, float]:
        """Return (repeated_count, confidence) for one side."""
        if not levels or len(levels) < 3:
            return 0, 0.0
        try:
            parsed = [(float(lv[0]), float(lv[1])) for lv in levels]
        except (IndexError, TypeError, ValueError):
            return 0, 0.0

        # Group by rounded quantity (8 significant figures to handle floats)
        qty_counts: dict = {}
        for _, qty in parsed:
            rq = round(qty, 8)
            qty_counts[rq] = qty_counts.get(rq, 0) + 1

        # Iceberg heuristic: a quantity that appears ≥ 3 times
        max_count = max(qty_counts.values()) if qty_counts else 0
        if max_count < 3:
            return 0, 0.0

        confidence = min(1.0, (max_count - 2) / 5.0)  # 3 repeats → 0.2, 7+ → 1.0
        return max_count, confidence

    bid_count, bid_conf = _check_side(bids or [])
    ask_count, ask_conf = _check_side(asks or [])

    if bid_conf <= 0 and ask_conf <= 0:
        return neutral

    if bid_conf >= ask_conf:
        return {
            "detected": True,
            "side": "BID",
            "suspected_levels": bid_count,
            "confidence": round(bid_conf, 4),
        }
    return {
        "detected": True,
        "side": "ASK",
        "suspected_levels": ask_count,
        "confidence": round(ask_conf, 4),
    }
