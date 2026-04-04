"""Cross-Asset Correlation – BTC/ETH "Sneeze" Filter.

If a major asset (BTC or ETH) is in a high-volatility or dumping regime,
altcoin LONG signals are paused or rejected to prevent getting caught in
a market-wide flush.

Typical usage
-------------
.. code-block:: python

    from src.cross_asset import AssetState, check_cross_asset_gate

    btc_state = AssetState(symbol="BTCUSDT", trend="DUMPING", volatility="HIGH")
    eth_state = AssetState(symbol="ETHUSDT", trend="NEUTRAL", volatility="NORMAL")

    allowed, reason = check_cross_asset_gate(
        signal_direction="LONG",
        signal_symbol="SOLUSDT",
        asset_states=[btc_state, eth_state],
    )
    # (False, "Cross-asset: BTCUSDT is DUMPING – altcoin LONG paused")

Design notes
------------
* ``AssetState`` is a lightweight dataclass that accepts data from any source
  (live regime detector, backtesting, mock data).
* The ``trend`` field maps naturally to the output of :mod:`src.regime` or
  any external macro classifier.
* Fails open when no asset states are provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.utils import get_logger

log = get_logger("cross_asset")

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Trend labels that trigger the altcoin long pause.
BEARISH_TREND_LABELS: frozenset[str] = frozenset({
    "DUMPING",
    "HIGH_VOLATILITY_DOWN",
    "DOWNTREND",
    "BEAR",
    "BEARISH",
    "CRASH",
})

#: Trend labels that indicate a strong bullish move — trigger altcoin short pause.
BULLISH_TREND_LABELS: frozenset[str] = frozenset({
    "PUMPING",
    "HIGH_VOLATILITY_UP",
    "UPTREND",
    "BULL",
    "BULLISH",
})

#: Volatility labels that trigger a downgrade of altcoin long confidence.
HIGH_VOLATILITY_LABELS: frozenset[str] = frozenset({
    "HIGH",
    "EXTREME",
    "HIGH_VOLATILITY",
    "HIGH_VOLATILITY_DOWN",
    "HIGH_VOLATILITY_UP",
    "VOLATILE",
})

# ---------------------------------------------------------------------------
# Graduated correlation thresholds for cross-asset gating  (Rec 7)
# ---------------------------------------------------------------------------
_CORR_VERY_LOW: float = 0.2   # Below this: pair is independent, no penalty
_CORR_LOW: float = 0.5        # Below this: minor penalty suggested
_CORR_HIGH: float = 0.8       # At or above this: hard block

#: Symbols treated as "major" assets that can affect altcoins.
#: Extend this set as needed (e.g. add "BNBUSDT" for BNB-chain tokens).
DEFAULT_MAJOR_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AssetState:
    """Current market state of a single asset.

    Attributes
    ----------
    symbol:
        Trading pair symbol (e.g. ``"BTCUSDT"``).
    trend:
        Trend label string.  Expected values include: ``"BULLISH"``,
        ``"BEARISH"``, ``"DUMPING"``, ``"NEUTRAL"``, ``"RANGING"``,
        ``"HIGH_VOLATILITY_DOWN"``, ``"HIGH_VOLATILITY_UP"``, etc.
        Case-insensitive comparison is used internally.
    volatility:
        Volatility label string.  Expected values: ``"NORMAL"``, ``"HIGH"``,
        ``"EXTREME"``.  ``None`` means unknown.
    price_change_pct:
        Optional recent percentage price change (e.g. ``-0.05`` for −5 %).
        Used for additional context; not currently used in gate logic.
    """

    symbol: str
    trend: str = "NEUTRAL"
    volatility: Optional[str] = None
    price_change_pct: Optional[float] = None
    extra: dict = field(default_factory=dict)

    def is_bearish(self) -> bool:
        """Return True when the trend is classified as bearish/dumping."""
        return self.trend.upper() in BEARISH_TREND_LABELS

    def is_high_volatility(self) -> bool:
        """Return True when volatility is high or extreme."""
        if self.volatility is None:
            return False
        return self.volatility.upper() in HIGH_VOLATILITY_LABELS


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------


def check_cross_asset_gate(
    signal_direction: str,
    signal_symbol: str,
    asset_states: Sequence[AssetState],
    major_symbols: Optional[frozenset[str]] = None,
    btc_correlation: Optional[float] = None,
) -> tuple[bool, str]:
    """Block or penalise altcoin signals when major assets are dumping/pumping.

    When *btc_correlation* is provided the gate is **graduated** (Rec 7):

    * correlation ≥ 0.8 → hard block (same as before)
    * 0.5 ≤ corr < 0.8  → soft block with penalty suggestion in *reason*
    * correlation < 0.5  → pass through (pair is loosely correlated)

    When *btc_correlation* is ``None`` the original binary behaviour is
    preserved for backwards compatibility.

    Parameters
    ----------
    signal_direction:
        ``"LONG"`` or ``"SHORT"``.
    signal_symbol:
        Symbol generating the signal (e.g. ``"SOLUSDT"``).  If the signal
        symbol is itself a major asset (e.g. ``"BTCUSDT"``), the filter is
        skipped because the signal *is* the major asset.
    asset_states:
        List of :class:`AssetState` objects for the major reference assets.
        Pass an empty list to fail open.
    major_symbols:
        Set of symbols considered "major".  Defaults to
        :data:`DEFAULT_MAJOR_SYMBOLS` (BTC, ETH).
    btc_correlation:
        Optional rolling Pearson correlation vs BTC.  When provided enables
        graduated gating.

    Returns
    -------
    ``(allowed, reason)``
    """
    if not asset_states:
        return True, ""

    direction = signal_direction.upper()

    _major = major_symbols if major_symbols is not None else DEFAULT_MAJOR_SYMBOLS

    # If the signal itself is a major asset, skip the correlation filter
    if signal_symbol.upper() in _major:
        return True, ""

    if direction == "LONG":
        for state in asset_states:
            if state.symbol.upper() not in _major:
                continue

            is_negative = state.is_bearish() or (
                state.is_high_volatility()
                and state.trend.upper() not in {"BULLISH", "RANGING", "NEUTRAL"}
            )
            if not is_negative:
                continue

            # Graduated gating when correlation is known
            if btc_correlation is not None:
                abs_corr = abs(btc_correlation)
                if abs_corr < _CORR_VERY_LOW:
                    # Very low correlation – pair is independent
                    continue
                if abs_corr < _CORR_LOW:
                    # Low-medium correlation – allow with penalty note
                    return (
                        True,
                        (
                            f"Cross-asset: {state.symbol} is {state.trend.upper()} "
                            f"(corr={btc_correlation:.2f}) – minor penalty suggested"
                        ),
                    )
                if abs_corr < _CORR_HIGH:
                    # Medium-high correlation – allow with strong penalty note
                    return (
                        True,
                        (
                            f"Cross-asset: {state.symbol} is {state.trend.upper()} "
                            f"(corr={btc_correlation:.2f}) – confidence penalty applied"
                        ),
                    )

            # High correlation (≥ 0.8) or unknown correlation → block
            if state.is_bearish():
                return (
                    False,
                    (
                        f"Cross-asset: {state.symbol} is {state.trend.upper()} "
                        f"– altcoin LONG paused"
                    ),
                )

            if state.is_high_volatility() and state.trend.upper() not in {"BULLISH", "RANGING", "NEUTRAL"}:
                return (
                    False,
                    (
                        f"Cross-asset: {state.symbol} has {state.volatility} volatility "
                        f"in {state.trend.upper()} regime – altcoin LONG paused"
                    ),
                )

    elif direction == "SHORT":
        for state in asset_states:
            if state.symbol.upper() not in _major:
                continue
            if state.trend.upper() in BULLISH_TREND_LABELS:
                # Graduated gating for SHORTs as well
                if btc_correlation is not None and abs(btc_correlation) < _CORR_LOW:
                    continue
                return (
                    False,
                    (
                        f"Cross-asset: {state.symbol} is {state.trend.upper()} "
                        f"– altcoin SHORT paused"
                    ),
                )

    return True, ""


def get_dominant_market_state(
    asset_states: Sequence[AssetState],
    major_symbols: Optional[frozenset[str]] = None,
) -> str:
    """Summarise the overall market tone from major asset states.

    Returns one of: ``"RISK_ON"``, ``"RISK_OFF"``, ``"VOLATILE"``, or
    ``"NEUTRAL"``.

    Parameters
    ----------
    asset_states:
        States for the reference assets.
    major_symbols:
        Set of symbols to consider.  Defaults to BTC + ETH.

    Returns
    -------
    Market tone label string.
    """
    _major = major_symbols if major_symbols is not None else DEFAULT_MAJOR_SYMBOLS

    relevant = [s for s in asset_states if s.symbol.upper() in _major]
    if not relevant:
        return "NEUTRAL"

    bearish_count = sum(1 for s in relevant if s.is_bearish())
    volatile_count = sum(1 for s in relevant if s.is_high_volatility())
    bullish_count = sum(
        1 for s in relevant
        if s.trend.upper() in {"BULLISH", "UPTREND", "BULL", "PUMPING", "HIGH_VOLATILITY_UP"}
    )

    total = len(relevant)

    if bearish_count >= total // 2 + 1:
        return "RISK_OFF"
    if volatile_count >= total // 2 + 1:
        return "VOLATILE"
    if bullish_count >= total // 2 + 1:
        return "RISK_ON"
    return "NEUTRAL"
