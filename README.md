# Parasoft License Monitor

**By ESL (Engineering Software Lab) — DEMO SOFTWARE**

Parses Parasoft DTP License Server access logs (`ls_access.log*`) and generates graphical HTML dashboards and CSV exports with daily, weekly, monthly, and yearly breakdowns.

> **Disclaimer:** This is a demonstration tool provided "AS IS". ESL makes no warranties regarding accuracy, security, reliability, or fitness for purpose. Not for production use.

## Requirements

- Python 3.10+ (no external dependencies — uses only stdlib)

## Quick Start

```bash
# Auto-detect logs from DTP installation
python monitor.py --dtp-path "C:\Program Files\Parasoft\DTP"

# Direct path to logs directory
python monitor.py --logs-path "C:\ProgramData\Parasoft\DTP\logs"

# Linux
python monitor.py --logs-path /var/parasoft/dtp/logs
```

## Usage

```
python monitor.py --logs-path <LOGS_DIR> [OPTIONS]

Required (one of):
  --dtp-path PATH     Path to DTP installation (auto-detects logs)
  --logs-path PATH    Direct path to directory containing ls_access.log* files

Options:
  --output-dir DIR    Output directory (default: ./parasoft-license-reports)
  --period PERIOD     daily | weekly | monthly | yearly | all (default: all)
  --from-date DATE    Start date filter (YYYY-MM-DD)
  --to-date DATE      End date filter (YYYY-MM-DD)
  --product NAME      Filter by product (e.g. "C++Test", "dotTEST", "Jtest")
  --platform NAME     Filter by platform (e.g. "WIN32", "LINUX2")
  --user NAME         Filter by login username
  --exclude-probes    Exclude sub-second probe sessions
  --report-name NAME  Filename prefix (default: parasoft_license)
  -v, --verbose       Enable debug logging
```

## Examples

```bash
# March 2026 report, daily breakdown
python monitor.py --logs-path "C:\ProgramData\Parasoft\DTP\logs" \
  --from-date 2026-03-01 --to-date 2026-03-31 --period daily

# C++Test only, exclude probes
python monitor.py --logs-path "..." --product "C++Test" --exclude-probes

# All periods, custom output
python monitor.py --dtp-path "C:\Program Files\Parasoft\DTP" \
  --output-dir "D:\reports" --report-name "client_acme"
```

## Output Files

### CLI-generated CSV files

| File | Description |
|------|-------------|
| `*_daily.html` | Interactive HTML dashboard with Chart.js charts (daily view) |
| `*_weekly.html` | Weekly aggregation dashboard |
| `*_monthly.html` | Monthly aggregation dashboard |
| `*_yearly.html` | Yearly aggregation dashboard |
| `*_sessions.csv` | Every license checkout/checkin session (raw detail) |
| `*_daily_summary.csv` | Daily aggregation with per-product/platform columns |
| `*_product_summary.csv` | Per-product totals |
| `*_user_summary.csv` | Per-user totals with first/last seen dates |

## HTML Dashboard Features

### Disclaimer Gate
When the dashboard is opened, a **disclaimer overlay** blocks access until the user reads and accepts the terms by checking the "I accept" checkbox and clicking **Enter Dashboard**.

### About Section
A prominent "About" box at the top of the dashboard identifies the tool as an **ESL demo** and repeats the disclaimer that the software is provided "AS IS" with no warranties.

### Date Selector (Toolbar)
The toolbar at the top provides:
- **From / To date pickers** — select a date range to filter the summary table
- **Filter button** — applies the date range, hiding table rows outside the range
- **Reset button** — restores the original full date range

### CSV Export Buttons (Toolbar)

There are **two CSV export buttons** in the toolbar. They serve different purposes:

| Button | Color | What it exports |
|--------|-------|-----------------|
| **Export Table CSV** | Green | The **summary table** currently visible on screen — one row per period (day/week/month) with aggregated totals: session count, hours, probes, unique users, hosts, products. Respects the visible rows (if you filtered, only filtered rows export). |
| **Export Sessions CSV** | Orange | The **raw session detail** — one row per individual license checkout/checkin session, with: start time, end time, duration (minutes), user, hostname, IP, platform, product, all features checked out, probe flag, and heartbeat renewal count. Respects the From/To date picker filter. |

**When to use which:**
- Use **Export Table CSV** for management summaries and usage trend reports
- Use **Export Sessions CSV** for detailed audits, per-session analysis, or importing into Excel/Power BI for custom analysis

### Charts
- **Stacked bar charts**: Sessions and hours per period, broken down by product
- **Doughnut charts**: Platform distribution (by sessions) and product distribution (by hours)
- **User bar chart**: Hours per user (horizontal)
- **Daily trend line**: Session count trend (daily period only)

### Sortable Table
Click any column header to sort ascending/descending.

### Print-Friendly
Optimized for printing/PDF export via browser Print (`Ctrl+P`). The disclaimer overlay is hidden when printing.

## How It Works

1. **Parser** (`parser.py`): Reads `ls_access.log*` XML files, extracts `GET_LICENSE`, `GET_ENCODED_LICENSE`, `GET_ENCODED_MULTI_FEATURE_LICENSE` and their corresponding `RELEASE` events
2. **Session Builder** (`sessions.py`): Pairs checkout/checkin events into sessions, handles heartbeat renewals, detects sub-second probes, groups per-feature encoded entries under their parent product
3. **Reports** (`reports.py`): Aggregates sessions by period, generates Chart.js HTML dashboards with disclaimer gate, date filtering, CSV export, and About section
4. **CLI** (`monitor.py`): Orchestrates the pipeline with filtering and output options

## Supported License Event Types

| Log Event Type | Description |
|---|---|
| `GET_LICENSE` / `RELEASE_LICENSE` | Standard license checkout/checkin |
| `GET_ENCODED_LICENSE` / `RELEASE_ENCODED_LICENSE` | Encoded per-feature checkout (newer DTP) |
| `GET_ENCODED_MULTI_FEATURE_LICENSE` / `RELEASE_ENCODED_MULTI_FEATURE_LICENSE` | Multi-feature bundle checkout (newer DTP) |

## Supported Products

C++Test, dotTEST, Jtest, SOAtest, Selenic, Insure++ (auto-detected from feature names).

## Logo

Place `esl_logo.png` in the same directory as the Python files. It will be embedded (base64) into the HTML reports automatically — in the disclaimer popup, about section, and footer.
