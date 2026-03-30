"""Build license usage sessions by pairing GET_LICENSE / RELEASE_LICENSE events.

A session is a checkout/checkin cycle:
- A GET_LICENSE event starts a session.
- Subsequent GET_LICENSE events with the same (user, product, arch, ip) are
  heartbeat renewals — the same session continues.
- A RELEASE_LICENSE event with matching key closes the session.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

__all__ = [
    "Session",
    "build_sessions",
    "filter_sessions",
    "get_summary",
    "aggregate_by_period",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """A single license checkout/checkin cycle."""

    start_time: datetime
    end_time: Optional[datetime]
    duration_minutes: float
    login_user: str
    os_user: str
    hostname: str
    ip: str
    platform: str           # WIN32, LINUX2, etc.
    product: str            # C++Test, dotTEST, Jtest, etc.
    features: list[str]     # All features checked out
    license_id: str
    is_probe: bool = False       # Sub-second session
    is_unclosed: bool = False    # No RELEASE found
    renewals: int = 0           # Number of heartbeat renewals in this session


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _session_key(event: dict) -> tuple[str, str, str, str]:
    """Return the matching key for an event: (login_user, product, arch, ip)."""
    return (
        event.get("login_user", ""),
        event.get("product", ""),
        event.get("arch", ""),
        event.get("ip", ""),
    )


def _finalize_session(
    open_rec: dict,
    end_time: Optional[datetime],
    unclosed: bool,
    unclosed_timeout_min: int,
) -> Session:
    """Convert an open-session record into a finished Session object."""
    start: datetime = open_rec["start_time"]

    if end_time is None:
        # Use last heartbeat or start + timeout
        last_seen: datetime = open_rec.get("last_seen", start)
        end_time = max(last_seen, start + timedelta(minutes=unclosed_timeout_min))
        unclosed = True

    duration_sec = (end_time - start).total_seconds()
    duration_min = duration_sec / 60.0
    is_probe = duration_sec < 1.0

    return Session(
        start_time=start,
        end_time=end_time,
        duration_minutes=round(duration_min, 4),
        login_user=open_rec["login_user"],
        os_user=open_rec.get("os_user", ""),
        hostname=open_rec.get("hostname", ""),
        ip=open_rec.get("ip", ""),
        platform=open_rec.get("platform", ""),
        product=open_rec.get("product", ""),
        features=list(open_rec.get("features", [])),
        license_id=open_rec.get("license_id", ""),
        is_probe=is_probe,
        is_unclosed=unclosed,
        renewals=open_rec.get("renewals", 0),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sessions(
    events: list[dict],
    unclosed_timeout_min: int = 60,
) -> list[Session]:
    """Build sessions from parsed license events.

    Parameters
    ----------
    events:
        List of event dicts as returned by ``parser.parse_log()``.  Expected
        keys per event: ``timestamp``, ``event_type`` (``GET_LICENSE`` or
        ``RELEASE_LICENSE``), ``login_user``, ``product``, ``arch``, ``ip``,
        ``os_user``, ``hostname``, ``platform``, ``features``, ``license_id``.
    unclosed_timeout_min:
        If a checkout has no matching release, the session end is set to
        ``last_heartbeat + unclosed_timeout_min`` (default 60 min).

    Returns
    -------
    list[Session]
        Sessions sorted by ``start_time``.
    """
    # Keyed by (login_user, product, arch, ip)
    open_sessions: dict[tuple[str, str, str, str], dict] = {}
    finished: list[Session] = []

    for event in events:
        etype = event.get("event_type", "")
        key = _session_key(event)
        ts: datetime = event.get("timestamp")  # type: ignore[assignment]

        if ts is None:
            logger.warning("Event without timestamp, skipping: %s", event)
            continue

        if etype == "GET_LICENSE":
            if key in open_sessions:
                # Heartbeat renewal — same session continues
                rec = open_sessions[key]
                rec["renewals"] = rec.get("renewals", 0) + 1
                rec["last_seen"] = ts
                # Merge any new features
                existing_features: set[str] = set(rec.get("features", []))
                for f in event.get("features", []):
                    existing_features.add(f)
                rec["features"] = list(existing_features)
                logger.debug("Heartbeat renewal for %s (renewal #%d)", key, rec["renewals"])
            else:
                # New session
                open_sessions[key] = {
                    "start_time": ts,
                    "last_seen": ts,
                    "login_user": event.get("login_user", ""),
                    "os_user": event.get("os_user", ""),
                    "hostname": event.get("hostname", ""),
                    "ip": event.get("ip", ""),
                    "platform": event.get("platform", ""),
                    "product": event.get("product", ""),
                    "features": list(event.get("features", [])),
                    "license_id": event.get("license_id", ""),
                    "renewals": 0,
                }

        elif etype == "RELEASE_LICENSE":
            if key in open_sessions:
                session = _finalize_session(
                    open_sessions.pop(key),
                    end_time=ts,
                    unclosed=False,
                    unclosed_timeout_min=unclosed_timeout_min,
                )
                finished.append(session)
            else:
                # Orphaned release — no matching GET
                logger.debug("Orphaned RELEASE_LICENSE for %s at %s, skipping", key, ts)

    # Close any remaining open sessions as unclosed
    for key, rec in open_sessions.items():
        logger.debug("Unclosed session for %s, closing with timeout", key)
        session = _finalize_session(
            rec,
            end_time=None,
            unclosed=True,
            unclosed_timeout_min=unclosed_timeout_min,
        )
        finished.append(session)

    finished.sort(key=lambda s: s.start_time)
    return finished


def filter_sessions(
    sessions: list[Session],
    start_date: Optional[date | datetime] = None,
    end_date: Optional[date | datetime] = None,
    product: Optional[str] = None,
    platform: Optional[str] = None,
    user: Optional[str] = None,
    exclude_probes: bool = False,
) -> list[Session]:
    """Filter sessions by various criteria.

    All parameters are optional; unset parameters impose no filter.
    """
    result: list[Session] = []

    for s in sessions:
        if exclude_probes and s.is_probe:
            continue
        if start_date is not None:
            start_dt = (
                datetime.combine(start_date, datetime.min.time())
                if isinstance(start_date, date) and not isinstance(start_date, datetime)
                else start_date
            )
            if s.start_time < start_dt:
                continue
        if end_date is not None:
            end_dt = (
                datetime.combine(end_date, datetime.max.time())
                if isinstance(end_date, date) and not isinstance(end_date, datetime)
                else end_date
            )
            if s.start_time > end_dt:
                continue
        if product is not None and s.product != product:
            continue
        if platform is not None and s.platform != platform:
            continue
        if user is not None and s.login_user != user:
            continue

        result.append(s)

    return result


def get_summary(sessions: list[Session]) -> dict:
    """Return an aggregate summary dict for the given sessions."""
    per_product: dict[str, dict[str, float]] = defaultdict(lambda: {"sessions": 0, "hours": 0.0})
    per_platform: dict[str, dict[str, float]] = defaultdict(lambda: {"sessions": 0, "hours": 0.0})
    per_user: dict[str, dict[str, float]] = defaultdict(lambda: {"sessions": 0, "hours": 0.0})
    day_counts: dict[date, int] = defaultdict(int)

    total_hours = 0.0
    total_probes = 0
    users: set[str] = set()
    products: set[str] = set()
    platforms: set[str] = set()
    hosts: set[str] = set()
    ips: set[str] = set()
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    longest: Optional[Session] = None

    for s in sessions:
        hours = s.duration_minutes / 60.0
        total_hours += hours

        if s.is_probe:
            total_probes += 1

        users.add(s.login_user)
        products.add(s.product)
        platforms.add(s.platform)
        hosts.add(s.hostname)
        ips.add(s.ip)

        per_product[s.product]["sessions"] += 1
        per_product[s.product]["hours"] += hours
        per_platform[s.platform]["sessions"] += 1
        per_platform[s.platform]["hours"] += hours
        per_user[s.login_user]["sessions"] += 1
        per_user[s.login_user]["hours"] += hours

        s_date = s.start_time.date()
        day_counts[s_date] += 1

        if first_date is None or s_date < first_date:
            first_date = s_date
        if last_date is None or s_date > last_date:
            last_date = s_date

        if longest is None or s.duration_minutes > longest.duration_minutes:
            longest = s

    # Round hours in per-* dicts
    for d in (*per_product.values(), *per_platform.values(), *per_user.values()):
        d["hours"] = round(d["hours"], 4)
        d["sessions"] = int(d["sessions"])

    busiest_day: Optional[tuple[date, int]] = None
    if day_counts:
        bd = max(day_counts, key=day_counts.get)  # type: ignore[arg-type]
        busiest_day = (bd, day_counts[bd])

    return {
        "total_sessions": len(sessions),
        "total_hours": round(total_hours, 4),
        "total_probes": total_probes,
        "unique_users": sorted(users),
        "unique_products": sorted(products),
        "unique_platforms": sorted(platforms),
        "unique_hosts": sorted(hosts),
        "unique_ips": sorted(ips),
        "date_range": (first_date, last_date),
        "busiest_day": busiest_day,
        "longest_session": longest,
        "per_product": dict(per_product),
        "per_platform": dict(per_platform),
        "per_user": dict(per_user),
    }


def _iso_week_label(d: date) -> str:
    """Return ISO week label like '2026-W11'."""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _period_info(
    d: date,
    period: str,
) -> tuple[str, date, date]:
    """Return (label, period_start, period_end) for the given date and period type."""
    if period == "daily":
        return d.isoformat(), d, d

    if period == "weekly":
        iso_year, iso_week, iso_day = d.isocalendar()
        week_start = d - timedelta(days=iso_day - 1)  # Monday
        week_end = week_start + timedelta(days=6)      # Sunday
        return _iso_week_label(d), week_start, week_end

    if period == "monthly":
        month_start = d.replace(day=1)
        # Last day of month
        if d.month == 12:
            month_end = d.replace(day=31)
        else:
            month_end = d.replace(month=d.month + 1, day=1) - timedelta(days=1)
        label = f"{d.year}-{d.month:02d}"
        return label, month_start, month_end

    if period == "yearly":
        year_start = date(d.year, 1, 1)
        year_end = date(d.year, 12, 31)
        return str(d.year), year_start, year_end

    raise ValueError(f"Unknown period: {period!r}. Use 'daily', 'weekly', 'monthly', or 'yearly'.")


def aggregate_by_period(
    sessions: list[Session],
    period: str,
) -> list[dict]:
    """Aggregate sessions into time periods.

    Parameters
    ----------
    sessions:
        List of Session objects.
    period:
        One of ``"daily"``, ``"weekly"``, ``"monthly"``, ``"yearly"``.

    Returns
    -------
    list[dict]
        One dict per period, sorted chronologically.
    """
    buckets: dict[str, dict] = {}

    for s in sessions:
        s_date = s.start_time.date()
        label, p_start, p_end = _period_info(s_date, period)
        hours = s.duration_minutes / 60.0

        if label not in buckets:
            buckets[label] = {
                "period_label": label,
                "period_start": p_start,
                "period_end": p_end,
                "total_sessions": 0,
                "total_hours": 0.0,
                "total_probes": 0,
                "by_product": defaultdict(lambda: {"sessions": 0, "hours": 0.0}),
                "by_platform": defaultdict(lambda: {"sessions": 0, "hours": 0.0}),
                "by_user": defaultdict(lambda: {"sessions": 0, "hours": 0.0}),
                "_users": set(),
                "_hosts": set(),
            }

        b = buckets[label]
        b["total_sessions"] += 1
        b["total_hours"] += hours
        if s.is_probe:
            b["total_probes"] += 1

        b["by_product"][s.product]["sessions"] += 1
        b["by_product"][s.product]["hours"] += hours
        b["by_platform"][s.platform]["sessions"] += 1
        b["by_platform"][s.platform]["hours"] += hours
        b["by_user"][s.login_user]["sessions"] += 1
        b["by_user"][s.login_user]["hours"] += hours

        b["_users"].add(s.login_user)
        b["_hosts"].add(s.hostname)

    # Finalize
    result: list[dict] = []
    for label in sorted(buckets):
        b = buckets[label]
        b["total_hours"] = round(b["total_hours"], 4)
        b["unique_users"] = len(b.pop("_users"))
        b["unique_hosts"] = len(b.pop("_hosts"))

        # Convert defaultdicts and round hours
        for key in ("by_product", "by_platform", "by_user"):
            cleaned: dict[str, dict[str, float]] = {}
            for k, v in b[key].items():
                cleaned[k] = {"sessions": int(v["sessions"]), "hours": round(v["hours"], 4)}
            b[key] = cleaned

        result.append(b)

    return result
