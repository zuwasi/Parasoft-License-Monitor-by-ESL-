"""Parasoft License Monitor - CLI entry point.

Parses Parasoft DTP ls_access.log files, builds license usage sessions,
and generates HTML/CSV reports broken down by period.

Usage examples::

    python monitor.py --dtp-path "C:\\Program Files\\Parasoft\\DTP"
    python monitor.py --logs-path "C:\\ProgramData\\Parasoft\\DTP\\logs"
    python monitor.py --logs-path "..." --period daily --output-dir ./reports
    python monitor.py --logs-path "..." --from-date 2026-01-01 --to-date 2026-03-29
    python monitor.py --logs-path "..." --product "C++Test" --exclude-probes
    python monitor.py --remote "http://dtp-server:9271" --token abc123
    python monitor.py --remote "https://10.0.1.5:9271" --token xyz --no-verify-ssl
    python monitor.py --servers-file servers.json --no-verify-ssl
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import re
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Import sibling modules
#
# ``parser.py`` shadows Python's built-in ``parser`` module, so we load it
# explicitly by file path to avoid the conflict.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent

_parser_spec = importlib.util.spec_from_file_location("log_parser", _HERE / "parser.py")
log_parser = importlib.util.module_from_spec(_parser_spec)
_parser_spec.loader.exec_module(log_parser)

sys.path.insert(0, str(_HERE))
import sessions as sessions_mod  # noqa: E402
import reports  # noqa: E402

logger = logging.getLogger("parasoft_license_monitor")

PERIODS = ("daily", "weekly", "monthly", "yearly")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitor",
        description="Parasoft License Monitor — analyse DTP ls_access.log files and generate usage reports.",
    )

    paths = parser.add_mutually_exclusive_group(required=True)
    paths.add_argument(
        "--dtp-path",
        type=str,
        help="Path to the DTP installation directory (auto-detects logs location).",
    )
    paths.add_argument(
        "--logs-path",
        type=str,
        help="Direct path to the directory containing ls_access.log* files.",
    )
    paths.add_argument(
        "--remote",
        type=str,
        help='Remote agent URL (e.g. "http://dtp-server:9271" or "https://10.0.1.5:9271").',
    )
    paths.add_argument(
        "--servers-file",
        type=str,
        help="Path to JSON file listing multiple remote servers.",
    )

    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Authentication token for remote agent.",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        default=False,
        help="Skip SSL certificate verification for remote agents.",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="./parasoft-license-reports",
        help="Output directory for generated reports (default: ./parasoft-license-reports).",
    )
    parser.add_argument(
        "--period",
        type=str,
        choices=["daily", "weekly", "monthly", "yearly", "all"],
        default="all",
        help="Report period granularity (default: all).",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Start date filter in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        default=None,
        help="End date filter in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--product",
        type=str,
        default=None,
        help='Filter by product name (e.g. "C++Test", "dotTEST").',
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help='Filter by platform (e.g. "WIN32", "LINUX2").',
    )
    parser.add_argument(
        "--user",
        type=str,
        default=None,
        help="Filter by login username.",
    )
    parser.add_argument(
        "--exclude-probes",
        action="store_true",
        default=False,
        help="Exclude sub-second probe sessions from reports.",
    )
    parser.add_argument(
        "--report-name",
        type=str,
        default="parasoft_license",
        help='Prefix for output filenames (default: "parasoft_license").',
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose (DEBUG) logging.",
    )

    return parser


def _parse_date(value: str, label: str) -> date:
    """Parse a YYYY-MM-DD string into a :class:`datetime.date`."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        print(f"Error: Invalid {label} date '{value}'. Expected format: YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def _print_summary(summary: dict, generated_files: list[str]) -> None:
    """Print a boxed summary to the console."""
    date_range = summary.get("date_range", (None, None))
    first = date_range[0].isoformat() if date_range[0] else "N/A"
    last = date_range[1].isoformat() if date_range[1] else "N/A"
    total_sessions = summary.get("total_sessions", 0)
    total_hours = summary.get("total_hours", 0.0)
    unique_users = summary.get("unique_users", [])
    unique_products = summary.get("unique_products", [])
    unique_platforms = summary.get("unique_platforms", [])

    W = 56  # inner width

    def _line(text: str) -> str:
        return f"| {text:<{W - 2}} |"

    border = "+" + "-" * W + "+"
    title = "Parasoft License Monitor - Report Summary"

    print()
    print(border)
    print(f"|{title:^{W}}|")
    print(border)
    print(_line(f"Data Range: {first} to {last}"))
    print(_line(f"Total Sessions: {total_sessions}"))
    print(_line(f"Total Usage: {total_hours:.1f} hours"))
    print(_line(f"Unique Users: {len(unique_users)}"))
    print(_line(f"Products: {', '.join(unique_products) if unique_products else 'N/A'}"))
    print(_line(f"Platforms: {', '.join(unique_platforms) if unique_platforms else 'N/A'}"))
    print(border)
    print(_line("Reports generated:"))
    for fpath in generated_files:
        ext = Path(fpath).suffix.lstrip(".").upper()
        print(_line(f"  {ext}: {fpath}"))
    print(border)
    print()


# ---------------------------------------------------------------------------
# Remote agent helpers
# ---------------------------------------------------------------------------

def _format_bytes(n: int) -> str:
    """Format a byte count as a human-readable string."""
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def fetch_remote_logs(
    base_url: str,
    token: str,
    start_date: date | None = None,
    end_date: date | None = None,
    verify_ssl: bool = True,
    server_name: str | None = None,
) -> Path:
    """Fetch log files from a remote ESL agent and return a temp directory containing them."""
    display_name = server_name or base_url

    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx = None

    def _get(endpoint: str) -> urllib.request.Request:
        url = f"{base_url.rstrip('/')}{endpoint}"
        req = urllib.request.Request(url)
        if token:
            req.add_header("X-Auth-Token", token)
        return urllib.request.urlopen(req, context=ctx)

    print(f"Connecting to {display_name} ({base_url})...")

    try:
        with _get("/api/info") as resp:
            info = json.loads(resp.read().decode())
            hostname = info.get("hostname", "?")
            logger.info("Connected to agent on %s (%s)", hostname, base_url)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print(f"  Error: Authentication failed for {base_url} — check your token.", file=sys.stderr)
            sys.exit(1)
        raise
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLError):
            print(
                f"  Error: SSL verification failed for {base_url}.\n"
                f"  Use --no-verify-ssl to skip certificate verification.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"  Error: Cannot reach remote agent at {base_url}: {reason}", file=sys.stderr)
        sys.exit(1)

    with _get("/api/logs") as resp:
        file_list = json.loads(resp.read().decode())

    files = file_list.get("files", [])
    print(f"  Server: {hostname}, {len(files)} log files")

    temp_dir = Path(tempfile.mkdtemp(prefix="esl_license_"))
    downloaded = 0
    total_bytes = 0
    date_suffix_re = re.compile(r"^ls_access\.log\.(\d{4}-\d{2}-\d{2})$")

    for f in files:
        fname = f["name"]
        m = date_suffix_re.match(fname)
        if m:
            file_date = date.fromisoformat(m.group(1))
            if start_date is not None and file_date < start_date:
                logger.debug("Skipping %s (before start_date)", fname)
                continue
            if end_date is not None and file_date > end_date:
                logger.debug("Skipping %s (after end_date)", fname)
                continue

        size = f.get("size", 0)
        print(f"  Downloading {fname} ({_format_bytes(size)})...")
        with _get(f"/api/logs/{fname}") as resp:
            content = resp.read()
            (temp_dir / fname).write_bytes(content)
            downloaded += 1
            total_bytes += len(content)

    print(f"  Downloaded {downloaded} files ({_format_bytes(total_bytes)} total)")
    return temp_dir


def _load_servers_file(path: str) -> list[dict]:
    """Load and validate a servers JSON file."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: Cannot read servers file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)

    servers = data.get("servers", [])
    if not servers:
        print(f"Error: No servers defined in '{path}'.", file=sys.stderr)
        sys.exit(1)

    for i, s in enumerate(servers):
        if "url" not in s:
            print(f"Error: Server entry #{i + 1} in '{path}' is missing 'url'.", file=sys.stderr)
            sys.exit(1)
    return servers


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _build_parser().parse_args()

    # -- Logging -----------------------------------------------------------
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # -- Parse date filters ------------------------------------------------
    start_date = _parse_date(args.from_date, "--from-date") if args.from_date else None
    end_date = _parse_date(args.to_date, "--to-date") if args.to_date else None

    # -- Resolve logs directory --------------------------------------------
    temp_dirs: list[Path] = []
    verify_ssl = not args.no_verify_ssl
    logs_dirs: list[tuple[Path, str | None]] = []  # (path, server_name)

    if args.remote:
        if not args.token:
            print("Error: --token is required when using --remote", file=sys.stderr)
            sys.exit(1)
        td = fetch_remote_logs(args.remote, args.token, start_date, end_date, verify_ssl)
        temp_dirs.append(td)
        logs_dirs.append((td, None))

    elif args.servers_file:
        servers = _load_servers_file(args.servers_file)
        for srv in servers:
            url = srv["url"]
            tok = srv.get("token") or args.token
            name = srv.get("name")
            if not tok:
                print(f"Error: No token for server '{name or url}'. "
                      f"Provide per-server tokens in the JSON or use --token.", file=sys.stderr)
                sys.exit(1)
            td = fetch_remote_logs(url, tok, start_date, end_date, verify_ssl, server_name=name)
            temp_dirs.append(td)
            logs_dirs.append((td, name or url))

    elif args.logs_path:
        logs_dirs.append((Path(args.logs_path), None))

    else:
        logger.info("Auto-detecting logs path from DTP installation: %s", args.dtp_path)
        logs_dirs.append((Path(log_parser.detect_logs_path(args.dtp_path)), None))

    try:
        # -- Validate & parse all log directories -----------------------------
        events: list[dict] = []

        for logs_dir, server_name in logs_dirs:
            if not logs_dir.is_dir():
                print(f"Error: Logs directory does not exist: {logs_dir}", file=sys.stderr)
                sys.exit(1)

            logger.info("Using logs directory: %s", logs_dir)

            log_files = log_parser.find_log_files(logs_dir)
            if not log_files:
                print(f"Error: No log files found in {logs_dir}", file=sys.stderr)
                sys.exit(1)

            logger.info("Found %d log file(s)", len(log_files))
            for f in log_files:
                logger.debug("  %s", f)

            logger.info("Parsing log files…")
            dir_events = log_parser.parse_all_logs(logs_dir, start_date=start_date, end_date=end_date)

            if server_name:
                for ev in dir_events:
                    ev["server"] = server_name

            events.extend(dir_events)

        events.sort(key=lambda e: e["timestamp"])
        logger.info("Parsed %d events total", len(events))

        if not events:
            print("Warning: No events found in the log files.", file=sys.stderr)
            sys.exit(0)

        # -- Build sessions ----------------------------------------------------
        logger.info("Building sessions…")
        all_sessions = sessions_mod.build_sessions(events)
        logger.info("Built %d session(s)", len(all_sessions))

        # -- Filter sessions ---------------------------------------------------
        filtered = sessions_mod.filter_sessions(
            all_sessions,
            start_date=start_date,
            end_date=end_date,
            product=args.product,
            platform=args.platform,
            user=args.user,
            exclude_probes=args.exclude_probes,
        )
        logger.info("After filtering: %d session(s)", len(filtered))

        if not filtered:
            print("Warning: No sessions match the specified filters.", file=sys.stderr)
            sys.exit(0)

        # -- Summary -----------------------------------------------------------
        summary = sessions_mod.get_summary(filtered)

        # -- Output directory --------------------------------------------------
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # -- Determine periods to generate -------------------------------------
        if args.period == "all":
            periods_to_generate = list(PERIODS)
        else:
            periods_to_generate = [args.period]

        # -- Generate reports --------------------------------------------------
        generated_files: list[str] = []
        prefix = args.report_name

        for period in periods_to_generate:
            logger.info("Generating %s report…", period)
            aggregated = sessions_mod.aggregate_by_period(filtered, period)

            html_path = reports.generate_html_report(
                sessions=filtered,
                summary=summary,
                period_data=aggregated,
                output_dir=output_dir,
                report_name=prefix,
                period=period,
            )
            generated_files.append(str(html_path))

            csv_paths = reports.generate_csv_reports(
                sessions=filtered,
                summary=summary,
                period_data=aggregated,
                output_dir=output_dir,
                report_name=prefix,
                period=period,
            )
            for cp in csv_paths:
                generated_files.append(str(cp))

        # -- Console summary ---------------------------------------------------
        _print_summary(summary, generated_files)

    finally:
        # -- Clean up temp directories -----------------------------------------
        import shutil
        for td in temp_dirs:
            try:
                shutil.rmtree(td, ignore_errors=True)
                logger.debug("Cleaned up temp directory: %s", td)
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(1)
