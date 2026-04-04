"""Kill Zone / Session Volume Profiling – Time-of-Day Modifier.

Returns a confidence multiplier or boolean flag based on the current UTC
timestamp, classifying market sessions into high-liquidity windows and
low-liquidity "dead zones".

Session windows (all times UTC)
---------------------------------
* **London open**      : 07:00–09:00
* **NY/London overlap**: 12:00–16:00  ← highest liquidity, best fills
* **NY session**       : 16:00–20:00
* **Asian session**    : 00:00–04:00  (lower liquidity, wider spreads)

Dead zones
-----------
* Asian mid-session    : 04:00–07:00  (very low volume)
* Pre-London           : 05:00–07:00  (part of above)
* Weekend (Sat 22:00 – Sun 21:00 UTC) – crypto still trades but CME/spot is quiet

Typical usage
-------------
.. code-block:: python

    from datetime import datetime, timezone
    from src.kill_zone import classify_session, check_kill_zone_gate

    result = classify_session()          # uses current UTC time
    print(result.session_name)           # "NY_LONDON_OVERLAP"
    print(result.confidence_multiplier)  # 1.0

    allowed, reason = check_kill_zone_gate()
    if not allowed:
        print(reason)  # "Kill zone: weekend dead zone – trading paused"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.utils import get_logger

log = get_logger("kill_zone")

# ---------------------------------------------------------------------------
# Session definitions  (all hours in UTC, inclusive start, exclusive end)
# ---------------------------------------------------------------------------

#: High-liquidity session windows: (start_hour, end_hour, name, multiplier)
_HIGH_LIQUIDITY_SESSIONS: list[tuple[int, int, str, float]] = [
    (7,  9,  "LONDON_OPEN",       0.95),
    (9,  12, "LONDON_SESSION",    0.90),  # core London — high liquidity
    (12, 16, "NY_LONDON_OVERLAP", 1.00),  # best session
    (16, 20, "NY_SESSION",        0.90),
    (0,  4,  "ASIAN_SESSION",     0.75),
]

#: Dead zone windows: (start_hour, end_hour, name, multiplier)
_DEAD_ZONE_SESSIONS: list[tuple[int, int, str, float]] = [
    (4,  7,  "ASIAN_DEAD_ZONE",   0.50),
    (20, 24, "POST_NY_LULL",      0.60),
]

#: Minimum confidence multiplier below which the kill zone gate fires.
KILL_ZONE_MINIMUM_MULTIPLIER: float = 0.50

#: Weekend detection: Saturday 22:00 UTC through Sunday 21:00 UTC
_WEEKEND_KILL_ZONE_SAT_START = 22  # Saturday hour (UTC) when weekend dead zone begins
_WEEKEND_KILL_ZONE_SUN_END = 21    # Sunday hour (UTC) when weekend dead zone ends


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionResult:
    """Time-of-day classification result."""

    session_name: str               # Human-readable session label
    confidence_multiplier: float    # 0.0 – 1.0; 1.0 = ideal trading conditions
    is_kill_zone: bool              # True when multiplier < KILL_ZONE_MINIMUM_MULTIPLIER
    is_weekend: bool                # True when inside the weekend dead zone
    utc_hour: int                   # Hour component of evaluated timestamp
    weekday: int                    # 0=Mon … 6=Sun
    reason: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_weekend_dead_zone(dt: datetime) -> bool:
    """Return True when *dt* falls within the weekend low-liquidity window."""
    weekday = dt.weekday()  # 5=Sat, 6=Sun
    hour = dt.hour

    # Saturday after 22:00 UTC
    if weekday == 5 and hour >= _WEEKEND_KILL_ZONE_SAT_START:
        return True
    # All of Sunday (weekday==6). Monday (weekday==0) is NOT included –
    # CME futures re-open Sunday ~21:00 UTC and spot liquidity returns.
    if weekday == 6:
        return True
    return False


def _match_session(
    hour: int,
    sessions: list[tuple[int, int, str, float]],
) -> Optional[tuple[str, float]]:
    """Return the first (name, multiplier) matching *hour*, or None."""
    for start, end, name, mult in sessions:
        if start <= hour < end:
            return name, mult
    return None


# ---------------------------------------------------------------------------
# Tier & weekday adjustment helpers  (Rec 10, Rec 11)
# ---------------------------------------------------------------------------


def _apply_tier_adjustment(
    multiplier: float,
    session_name: str,
    pair_tier: Optional[str],
) -> float:
    """Adjust session multiplier based on pair tier.

    MAJOR pairs get a boost during off-peak sessions (BTC/ETH trade 24/7).
    ALTCOIN pairs get a penalty (thin liquidity outside core sessions).
    """
    if pair_tier is None:
        return multiplier

    try:
        from config import PAIR_SESSION_ADJUSTMENTS
        adjustments = PAIR_SESSION_ADJUSTMENTS.get(pair_tier, {})
    except ImportError:
        return multiplier

    adj = adjustments.get(session_name, 0.0)
    return max(0.0, min(1.0, multiplier + adj))


def _apply_weekday_adjustment(
    multiplier: float,
    weekday: int,
    hour: int,
) -> float:
    """Apply Monday/Friday-specific confidence adjustments.

    * **Monday 00:00–04:00 UTC**: CME gap risk → small penalty.
    * **Friday 20:00+ UTC**: pre-weekend risk → small penalty.
    """
    # Monday early hours (CME gap risk)
    if weekday == 0 and hour < 4:
        multiplier = max(0.0, multiplier - 0.05)

    # Friday evening (pre-weekend wind-down)
    if weekday == 4 and hour >= 20:
        multiplier = max(0.0, multiplier - 0.03)

    return multiplier


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------


def classify_session(
    dt: Optional[datetime] = None,
    pair_tier: Optional[str] = None,
) -> SessionResult:
    """Classify the current (or provided) UTC datetime into a trading session.

    Parameters
    ----------
    dt:
        UTC datetime to classify.  When ``None``, uses ``datetime.now(UTC)``.
    pair_tier:
        Optional pair tier (``"MAJOR"``, ``"MIDCAP"``, ``"ALTCOIN"``).
        When provided, the confidence multiplier is adjusted using
        ``PAIR_SESSION_ADJUSTMENTS`` from config.

    Returns
    -------
    :class:`SessionResult`
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        # Assume UTC if no timezone is attached
        dt = dt.replace(tzinfo=timezone.utc)

    hour = dt.hour
    weekday = dt.weekday()

    # Weekend detection takes priority
    if _is_weekend_dead_zone(dt):
        mult = 0.40
        name = "WEEKEND_DEAD_ZONE"
        mult = _apply_tier_adjustment(mult, name, pair_tier)
        return SessionResult(
            session_name=name,
            confidence_multiplier=mult,
            is_kill_zone=True,
            is_weekend=True,
            utc_hour=hour,
            weekday=weekday,
            reason="Weekend dead zone – reduced liquidity, CME gap risk",
        )

    # Check high-liquidity sessions first
    high_match = _match_session(hour, _HIGH_LIQUIDITY_SESSIONS)
    if high_match:
        name, mult = high_match
        mult = _apply_tier_adjustment(mult, name, pair_tier)
        mult = _apply_weekday_adjustment(mult, weekday, hour)
        return SessionResult(
            session_name=name,
            confidence_multiplier=mult,
            is_kill_zone=mult < KILL_ZONE_MINIMUM_MULTIPLIER,
            is_weekend=False,
            utc_hour=hour,
            weekday=weekday,
        )

    # Check dead zones
    dead_match = _match_session(hour, _DEAD_ZONE_SESSIONS)
    if dead_match:
        name, mult = dead_match
        mult = _apply_tier_adjustment(mult, name, pair_tier)
        mult = _apply_weekday_adjustment(mult, weekday, hour)
        return SessionResult(
            session_name=name,
            confidence_multiplier=mult,
            is_kill_zone=mult < KILL_ZONE_MINIMUM_MULTIPLIER,
            is_weekend=False,
            utc_hour=hour,
            weekday=weekday,
            reason=f"{name}: low-volume period – tighter confirmation required",
        )

    # Fallback: unclassified hour (should not normally occur given full coverage)
    return SessionResult(
        session_name="UNCLASSIFIED",
        confidence_multiplier=0.70,
        is_kill_zone=False,
        is_weekend=False,
        utc_hour=hour,
        weekday=weekday,
    )


def check_kill_zone_gate(
    dt: Optional[datetime] = None,
    block_weekends: bool = True,
    minimum_multiplier: float = KILL_ZONE_MINIMUM_MULTIPLIER,
) -> tuple[bool, str]:
    """Pipeline hook: return ``(allowed, reason)`` for the kill-zone filter.

    Parameters
    ----------
    dt:
        UTC datetime to evaluate.  Defaults to ``datetime.now(UTC)``.
    block_weekends:
        When ``True`` (default), trades are blocked during the weekend dead zone.
    minimum_multiplier:
        Sessions with a confidence multiplier below this value are blocked.

    Returns
    -------
    ``(allowed, reason)``
    """
    result = classify_session(dt)

    if block_weekends and result.is_weekend:
        return False, f"Kill zone: {result.session_name} – {result.reason}"

    if result.confidence_multiplier < minimum_multiplier:
        return False, (
            f"Kill zone: {result.session_name} "
            f"(multiplier {result.confidence_multiplier:.0%} < {minimum_multiplier:.0%}) "
            f"– low-liquidity period"
        )

    return True, ""
