"""Parse Parasoft DTP License Server access logs (``ls_access.log*`` files).

The log files contain XML ``<log_entry>`` elements concatenated together (NOT
valid XML — there is no root element).  This module wraps the content in a
synthetic root so it can be parsed with :mod:`xml.etree.ElementTree`, extracts
``GET_LICENSE`` and ``RELEASE_LICENSE`` events, and returns a list of event
dicts consumable by :mod:`sessions`.
"""

from __future__ import annotations

import logging
import platform
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

__all__ = [
    "detect_logs_path",
    "find_log_files",
    "parse_log_file",
    "parse_all_logs",
]

logger = logging.getLogger(__name__)

_INTERESTING_TYPES = {
    "GET_LICENSE", "RELEASE_LICENSE",
    "GET_ENCODED_LICENSE", "RELEASE_ENCODED_LICENSE",
    "GET_ENCODED_MULTI_FEATURE_LICENSE", "RELEASE_ENCODED_MULTI_FEATURE_LICENSE",
    "GET_MULTI_FEATURE_LICENSE", "RELEASE_MULTI_FEATURE_LICENSE",
}
_TIME_FMT = "%Y-%m-%d %H:%M:%S.%f"
_DATE_SUFFIX_RE = re.compile(r"^ls_access\.log\.(\d{4}-\d{2}-\d{2})$")


# ---------------------------------------------------------------------------
# Log-directory detection
# ---------------------------------------------------------------------------

def detect_logs_path(dtp_path: str) -> Path:
    """Resolve the directory that contains ``ls_access.log*`` files.

    Strategy (first match wins):

    1. If *dtp_path* itself already contains ``ls_access.log``, return it.
    2. On Windows try ``C:\\ProgramData\\Parasoft\\DTP\\logs``.
    3. On Linux try ``/var/parasoft/dtp/logs``.
    4. Try ``{dtp_path}/../ProgramData/Parasoft/DTP/logs``.
    5. Raise :class:`FileNotFoundError` if nothing found.

    Parameters
    ----------
    dtp_path:
        Either the DTP install directory **or** the direct path to the logs
        directory (e.g. passed via ``--logs-path``).
    """
    base = Path(dtp_path)

    # 1. Direct path already contains logs
    if (base / "ls_access.log").exists():
        logger.debug("Found ls_access.log directly in %s", base)
        return base

    # 2. Platform-specific well-known locations
    if platform.system() == "Windows":
        well_known = Path(r"C:\ProgramData\Parasoft\DTP\logs")
        if (well_known / "ls_access.log").exists():
            logger.debug("Found ls_access.log in well-known Windows path %s", well_known)
            return well_known
    else:
        for linux_path in (
            Path("/var/parasoft/dtp/logs"),
            base.parent / "data" / "logs",
        ):
            if (linux_path / "ls_access.log").exists():
                logger.debug("Found ls_access.log in %s", linux_path)
                return linux_path

    # 3. Relative to supplied dtp_path
    relative = (base / ".." / "ProgramData" / "Parasoft" / "DTP" / "logs").resolve()
    if (relative / "ls_access.log").exists():
        logger.debug("Found ls_access.log in relative path %s", relative)
        return relative

    raise FileNotFoundError(
        f"Cannot locate ls_access.log from dtp_path={dtp_path!r}. "
        "Pass the logs directory explicitly with --logs-path."
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_log_files(logs_dir: Path) -> list[Path]:
    """Return all ``ls_access.log*`` files sorted chronologically.

    Rotated files (``ls_access.log.YYYY-MM-DD``) are sorted by their date
    suffix in ascending order.  The current ``ls_access.log`` (no date suffix)
    is placed **last** since it contains the most recent entries.
    """
    if not logs_dir.is_dir():
        raise FileNotFoundError(f"Logs directory does not exist: {logs_dir}")

    dated: list[tuple[str, Path]] = []
    current: Path | None = None

    for p in logs_dir.iterdir():
        if p.name == "ls_access.log":
            current = p
            continue
        m = _DATE_SUFFIX_RE.match(p.name)
        if m:
            dated.append((m.group(1), p))

    # Sort dated files chronologically
    dated.sort(key=lambda t: t[0])
    result = [p for _, p in dated]

    if current is not None:
        result.append(current)

    return result


# ---------------------------------------------------------------------------
# Single-file parsing
# ---------------------------------------------------------------------------

def _text(element: ET.Element | None) -> str:
    """Safely extract text from an element (returns '' on None)."""
    if element is None:
        return ""
    return (element.text or "").strip()


def _parse_entry(entry: ET.Element) -> dict | None:
    """Convert a single ``<log_entry>`` element into an event dict.

    Returns ``None`` if the entry type is not in :data:`_INTERESTING_TYPES` or
    if parsing fails.
    """
    entry_type = _text(entry.find("type"))
    if entry_type not in _INTERESTING_TYPES:
        return None

    # Timestamp
    time_str = _text(entry.find("time"))
    try:
        timestamp = datetime.strptime(time_str, _TIME_FMT)
    except (ValueError, TypeError):
        logger.warning("Unparseable timestamp %r, skipping entry", time_str)
        return None

    # Request block (may be absent for some event types)
    request = entry.find("request")

    hostname = _text(request.find("hostName")) if request is not None else ""
    arch = _text(request.find("archName")) if request is not None else ""
    tool_name_raw = _text(request.find("toolName")) if request is not None else ""

    # Parse toolName — features separated by |,|
    if tool_name_raw:
        features = [f.strip() for f in tool_name_raw.split("|,|") if f.strip()]
    else:
        features = []

    # Derive the primary product from feature names.
    # Individual encoded entries may have toolName="C++Test Coverage" — the
    # product is "C++Test".  Multi-feature entries list all features.
    # Known product prefixes (longest first so "C++Test" is not mistaken).
    _PRODUCT_PREFIXES = ("C++Test", "dotTEST", "Jtest", "SOAtest", "Selenic",
                         "Insure++", "C++test")
    product = ""
    if features:
        first = features[0]
        for prefix in _PRODUCT_PREFIXES:
            if first == prefix or first.startswith(prefix + " "):
                product = prefix
                break
        if not product:
            product = first  # fallback: use full name

    # License ID — located at request/tokens/token/license/id
    license_id = ""
    if request is not None:
        token = request.find("tokens/token")
        if token is not None:
            lic_id_el = token.find("license/id")
            license_id = _text(lic_id_el)

    # Status
    status_str = _text(entry.find("status"))
    try:
        status = int(status_str)
    except (ValueError, TypeError):
        status = -1

    # Normalize event types for session matching
    if "RELEASE" in entry_type:
        normalized_type = "RELEASE_LICENSE"
    else:
        normalized_type = "GET_LICENSE"

    return {
        "timestamp": timestamp,
        "event_type": normalized_type,
        "ip": _text(entry.find("ip")),
        "login_user": _text(entry.find("loginUserName")),
        "os_user": _text(entry.find("osUserName")),
        "hostname": hostname,
        "arch": arch,
        "platform": arch,
        "product": product,
        "features": features,
        "license_id": license_id,
        "status": status,
        "status_msg": _text(entry.find("statusmsg")),
    }


def parse_log_file(filepath: Path) -> list[dict]:
    """Parse a single ``ls_access.log*`` file and return event dicts.

    Only ``GET_LICENSE`` and ``RELEASE_LICENSE`` events are returned.
    Malformed entries are skipped with a logged warning.
    """
    events: list[dict] = []

    try:
        raw = filepath.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        logger.error("Cannot read log file: %s", filepath)
        return events

    # Wrap in a synthetic root to produce valid XML
    xml_text = f"<root>{raw}</root>"

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("XML parse error in %s: %s — attempting recovery", filepath, exc)
        # Recovery: try stripping stray characters outside <log_entry> blocks
        cleaned = re.sub(
            r"(?s)<log_entry\b.*?</log_entry>",
            lambda m: m.group(0),
            raw,
        )
        # Keep only <log_entry>…</log_entry> fragments
        fragments = re.findall(r"(?s)<log_entry\b.*?</log_entry>", raw)
        xml_text = "<root>" + "".join(fragments) + "</root>"
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc2:
            logger.error("Cannot recover XML in %s: %s", filepath, exc2)
            return events

    for entry in root.findall("log_entry"):
        try:
            event = _parse_entry(entry)
        except Exception:
            logger.warning("Malformed log_entry in %s, skipping", filepath, exc_info=True)
            continue
        if event is not None:
            events.append(event)

    logger.info("Parsed %d events from %s", len(events), filepath.name)
    return events


# ---------------------------------------------------------------------------
# Multi-file parsing
# ---------------------------------------------------------------------------

def parse_all_logs(
    logs_dir: Path,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """Parse all ``ls_access.log*`` files, optionally filtering by date range.

    Parameters
    ----------
    logs_dir:
        Directory containing the log files.
    start_date:
        If provided, skip rotated files whose date suffix is before this date.
    end_date:
        If provided, skip rotated files whose date suffix is after this date.

    Returns
    -------
    list[dict]
        All matching events sorted by ``timestamp``.
    """
    all_files = find_log_files(logs_dir)
    events: list[dict] = []

    for filepath in all_files:
        m = _DATE_SUFFIX_RE.match(filepath.name)
        if m:
            file_date = date.fromisoformat(m.group(1))
            if start_date is not None and file_date < start_date:
                logger.debug("Skipping %s (before start_date %s)", filepath.name, start_date)
                continue
            if end_date is not None and file_date > end_date:
                logger.debug("Skipping %s (after end_date %s)", filepath.name, end_date)
                continue
        # Current ls_access.log (no date suffix) is always included

        events.extend(parse_log_file(filepath))

    events.sort(key=lambda e: e["timestamp"])
    return events
