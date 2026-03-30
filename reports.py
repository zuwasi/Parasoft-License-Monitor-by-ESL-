"""Generate HTML reports with charts and CSV exports from license session data.

Produces a self-contained HTML dashboard (using Chart.js from CDN) and
multiple CSV exports covering sessions, period aggregations, product
summaries, and user summaries.
"""

from __future__ import annotations

import csv
import html
import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sessions import Session, aggregate_by_period, get_summary

__all__ = [
    "generate_html_report",
    "generate_csv_reports",
    "generate_all_reports",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_LOGO_PATH = Path(__file__).parent / "esl_logo.png"

CHART_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _esc(value: Any) -> str:
    """HTML-escape a value."""
    return html.escape(str(value))


def _js_str(value: Any) -> str:
    """Serialize *value* to a JSON string safe for embedding in <script>."""
    return json.dumps(value, default=str)


def _fmt_hours(h: float) -> str:
    return f"{h:,.2f}"


def _css() -> str:
    return """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;color:#222;background:#f4f5f7;line-height:1.5}
header{background:#1a1a2e;color:#fff;padding:24px 32px}
header h1{font-size:1.6rem;font-weight:600}
header .meta{opacity:.8;font-size:.85rem;margin-top:4px}
.container{max-width:1280px;margin:0 auto;padding:24px 16px}
.cards{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:32px}
.card{background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:20px 24px;flex:1 1 180px;min-width:160px}
.card .icon{font-size:1.6rem;margin-bottom:4px}
.card .value{font-size:1.5rem;font-weight:700;color:#1a1a2e}
.card .label{font-size:.8rem;color:#666;text-transform:uppercase;letter-spacing:.5px}
.toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:16px 20px}
.toolbar label{font-size:.85rem;font-weight:600;color:#1a1a2e}
.toolbar input[type=date]{padding:6px 10px;border:1px solid #ccc;border-radius:6px;font-size:.85rem}
.toolbar button{padding:8px 18px;border:none;border-radius:6px;font-size:.85rem;font-weight:600;cursor:pointer;transition:background .2s}
.btn-filter{background:#4e79a7;color:#fff}
.btn-filter:hover{background:#3b6291}
.btn-reset{background:#e0e0e0;color:#333}
.btn-reset:hover{background:#ccc}
.btn-csv{background:#59a14f;color:#fff}
.btn-csv:hover{background:#478a3f}
.btn-csv-sessions{background:#f28e2b;color:#fff}
.btn-csv-sessions:hover{background:#d97a1e}
.charts-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:24px;margin-bottom:32px}
.chart-box{background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:20px;position:relative;min-height:360px}
.chart-box h3{margin-bottom:12px;font-size:1rem;color:#1a1a2e}
.chart-box canvas{width:100%!important;height:300px!important}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);overflow:hidden;margin-bottom:32px}
thead{background:#1a1a2e;color:#fff;position:sticky;top:0}
th{padding:10px 14px;text-align:left;font-size:.8rem;text-transform:uppercase;letter-spacing:.5px;cursor:pointer;user-select:none;white-space:nowrap}
th:hover{background:#2a2a4e}
th .sort-arrow{margin-left:4px;font-size:.7rem}
td{padding:8px 14px;font-size:.85rem;border-bottom:1px solid #eee}
tr:nth-child(even){background:#fafbfc}
tr:hover{background:#eef1f6}
.about-box{background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:24px;margin-bottom:32px;border-left:4px solid #4e79a7}
.about-box h3{color:#1a1a2e;margin-bottom:8px;font-size:1.1rem}
.about-box p{font-size:.85rem;color:#555;margin-bottom:6px}
.about-box .demo-badge{display:inline-block;background:#e15759;color:#fff;padding:3px 12px;border-radius:12px;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
footer{text-align:center;padding:24px;font-size:.75rem;color:#999}
/* Disclaimer overlay */
#disclaimer-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);z-index:10000;display:flex;align-items:center;justify-content:center}
#disclaimer-box{background:#fff;border-radius:14px;max-width:640px;width:90%;padding:36px 32px;box-shadow:0 8px 32px rgba(0,0,0,.3);text-align:left}
#disclaimer-box h2{color:#1a1a2e;margin-bottom:12px;font-size:1.3rem}
#disclaimer-box p{font-size:.88rem;color:#444;margin-bottom:10px;line-height:1.6}
#disclaimer-box .warn{color:#e15759;font-weight:600}
#disclaimer-box label{display:flex;align-items:flex-start;gap:8px;margin:18px 0 20px;font-size:.88rem;cursor:pointer}
#disclaimer-box label input{margin-top:3px;width:18px;height:18px;accent-color:#4e79a7}
#disclaimer-box button{padding:10px 32px;border:none;border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;transition:background .2s}
#disclaimer-box button:disabled{background:#ccc;color:#888;cursor:not-allowed}
#disclaimer-box button:not(:disabled){background:#4e79a7;color:#fff}
#disclaimer-box button:not(:disabled):hover{background:#3b6291}
@media(max-width:900px){.charts-grid{grid-template-columns:1fr}}
@media print{header{background:#1a1a2e!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.chart-box{break-inside:avoid}body{background:#fff}#disclaimer-overlay{display:none!important}}
"""


def _sortable_js() -> str:
    """Inline JS for sortable table headers."""
    return """\
function sortTable(table,col,type){
  var tb=table.tBodies[0],rows=Array.from(tb.rows);
  var asc=table.dataset.sortCol==col&&table.dataset.sortDir==='asc'?false:true;
  table.dataset.sortCol=col;table.dataset.sortDir=asc?'asc':'desc';
  rows.sort(function(a,b){
    var x=a.cells[col].textContent.trim(),y=b.cells[col].textContent.trim();
    if(type==='num'){x=parseFloat(x.replace(/,/g,''))||0;y=parseFloat(y.replace(/,/g,''))||0;}
    if(x<y)return asc?-1:1;if(x>y)return asc?1:-1;return 0;
  });
  rows.forEach(function(r){tb.appendChild(r);});
  // update arrows
  table.querySelectorAll('th .sort-arrow').forEach(function(el){el.textContent='';});
  var arrow=table.querySelectorAll('th')[col].querySelector('.sort-arrow');
  if(arrow)arrow.textContent=asc?' ▲':' ▼';
}
"""


def _load_logo_b64() -> str:
    """Load the ESL logo as a base64 data URI. Returns empty string if not found."""
    if _LOGO_PATH.exists():
        import base64
        raw = _LOGO_PATH.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/png;base64,{b64}"
    return ""


def _period_data_for_js(period_data: list[dict]) -> list[dict]:
    """Prepare period data for JS embedding."""
    result = []
    for p in period_data:
        products_str = ", ".join(
            f"{k} ({v['sessions']})" for k, v in sorted(p.get("by_product", {}).items())
        )
        result.append({
            "label": p["period_label"],
            "sessions": p["total_sessions"],
            "hours": round(p["total_hours"], 2),
            "probes": p["total_probes"],
            "users": p["unique_users"],
            "hosts": p["unique_hosts"],
            "products": products_str,
        })
    return result


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------

def _build_html(
    sessions: list[Session],
    summary: dict,
    period_data: list[dict],
    period: str,
    report_name: str,
) -> str:
    """Build the full HTML string for the dashboard report."""

    logo_b64 = _load_logo_b64()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_range = summary.get("date_range", (None, None))
    range_str = "N/A"
    if date_range[0] and date_range[1]:
        range_str = f"{date_range[0].isoformat()} → {date_range[1].isoformat()}"

    all_products = sorted(summary.get("unique_products", []))
    all_platforms = sorted(summary.get("unique_platforms", []))
    active_days = 0
    if date_range[0] and date_range[1]:
        active_days = (date_range[1] - date_range[0]).days + 1

    # ---- Prepare chart data ----
    period_labels = [p["period_label"] for p in period_data]

    # Stacked sessions per product per period
    product_session_datasets = []
    for idx, prod in enumerate(all_products):
        data = []
        for p in period_data:
            data.append(p.get("by_product", {}).get(prod, {}).get("sessions", 0))
        product_session_datasets.append({
            "label": prod,
            "data": data,
            "backgroundColor": CHART_COLORS[idx % len(CHART_COLORS)],
        })

    # Stacked hours per product per period
    product_hours_datasets = []
    for idx, prod in enumerate(all_products):
        data = []
        for p in period_data:
            data.append(round(p.get("by_product", {}).get(prod, {}).get("hours", 0), 2))
        product_hours_datasets.append({
            "label": prod,
            "data": data,
            "backgroundColor": CHART_COLORS[idx % len(CHART_COLORS)],
        })

    # Platform doughnut (by session count)
    per_platform = summary.get("per_platform", {})
    platform_labels = sorted(per_platform.keys())
    platform_sessions = [per_platform[p]["sessions"] for p in platform_labels]
    platform_colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(platform_labels))]

    # Product doughnut (by hours)
    per_product = summary.get("per_product", {})
    product_labels = sorted(per_product.keys())
    product_hours_list = [round(per_product[p]["hours"], 2) for p in product_labels]
    product_donut_colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(product_labels))]

    # User bar chart (horizontal, hours)
    per_user = summary.get("per_user", {})
    user_labels = sorted(per_user.keys(), key=lambda u: per_user[u]["hours"], reverse=True)
    user_hours = [round(per_user[u]["hours"], 2) for u in user_labels]
    user_colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(user_labels))]

    # Daily trend line chart (only for daily period)
    daily_trend_labels: list[str] = []
    daily_trend_data: list[int] = []
    if period == "daily":
        daily_trend_labels = period_labels
        daily_trend_data = [p["total_sessions"] for p in period_data]

    # ---- Build table rows ----
    table_rows = ""
    for p in period_data:
        products_str = ", ".join(
            f"{k} ({v['sessions']})" for k, v in sorted(p.get("by_product", {}).items())
        )
        table_rows += (
            f"<tr>"
            f"<td>{_esc(p['period_label'])}</td>"
            f"<td>{p['total_sessions']:,}</td>"
            f"<td>{_fmt_hours(p['total_hours'])}</td>"
            f"<td>{p['total_probes']}</td>"
            f"<td>{p['unique_users']}</td>"
            f"<td>{p['unique_hosts']}</td>"
            f"<td>{_esc(products_str)}</td>"
            f"</tr>\n"
        )

    # ---- Column types for sort ----
    col_types = ["str", "num", "num", "num", "num", "num", "str"]
    th_cells = ""
    for i, (heading, ctype) in enumerate(zip(
        ["Period", "Sessions", "Hours", "Probes", "Users", "Hosts", "Products"],
        col_types,
    )):
        th_cells += (
            f'<th onclick="sortTable(this.closest(\'table\'),{i},\'{ctype}\')">'
            f'{heading}<span class="sort-arrow"></span></th>'
        )

    # ---- Build session rows for CSV export (embedded in JS) ----
    session_csv_data = []
    for s in sessions:
        session_csv_data.append({
            "start": s.start_time.isoformat() if s.start_time else "",
            "end": s.end_time.isoformat() if s.end_time else "",
            "dur": round(s.duration_minutes, 2),
            "user": s.login_user,
            "host": s.hostname,
            "ip": s.ip,
            "plat": s.platform,
            "prod": s.product,
            "feat": "; ".join(s.features),
            "probe": s.is_probe,
            "renew": s.renewals,
        })

    # ---- Assemble HTML ----
    date_from = date_range[0].isoformat() if date_range[0] else ""
    date_to = date_range[1].isoformat() if date_range[1] else ""

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(report_name)} - License Usage Report</title>
<style>{_css()}</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>

<!-- ============ DISCLAIMER OVERLAY ============ -->
<div id="disclaimer-overlay">
  <div id="disclaimer-box">
    <div style="text-align:center;margin-bottom:12px"><img src="{_esc(logo_b64)}" alt="ESL Logo" style="height:50px;width:auto"></div>
    <h2>Disclaimer - ESL License Monitor Demo</h2>
    <p>This software is provided by <strong>ESL (Engineering Software Lab)</strong> strictly as
    a <strong>demonstration tool</strong>.</p>
    <p class="warn">THIS IS NOT PRODUCTION SOFTWARE.</p>
    <p>ESL makes <strong>no warranties or representations</strong> of any kind, express or
    implied, regarding the accuracy, completeness, reliability, security, or fitness
    for any particular purpose of this software or any data it produces.</p>
    <p>By using this tool you acknowledge and agree that:</p>
    <ul style="font-size:.85rem;color:#444;margin:8px 0 8px 20px;line-height:1.7">
      <li>All output is <strong>approximate and may be inaccurate</strong>.</li>
      <li>ESL assumes <strong>no responsibility or liability</strong> for any decisions
          made based on the data shown.</li>
      <li>This tool has <strong>no security guarantees</strong> - do not use it in
          regulated or production environments.</li>
      <li>The software is provided <strong>"AS IS"</strong> without any obligation
          of support, maintenance, or updates.</li>
      <li>ESL shall not be held liable for any direct, indirect, incidental, or
          consequential damages arising from its use.</li>
    </ul>
    <label>
      <input type="checkbox" id="acceptCheck" onchange="document.getElementById('acceptBtn').disabled=!this.checked">
      I have read, understood, and accept the above disclaimer.
    </label>
    <button id="acceptBtn" disabled onclick="document.getElementById('disclaimer-overlay').style.display='none'">
      Enter Dashboard
    </button>
  </div>
</div>

<header>
  <h1>{_esc(report_name)} - License Usage Report</h1>
  <div class="meta">Generated {_esc(now_str)} &nbsp;|&nbsp; Data range: {_esc(range_str)} &nbsp;|&nbsp; Period: {_esc(period)}</div>
</header>

<div class="container">

<!-- About Box -->
<div class="about-box">
  <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
    <img src="{_esc(logo_b64)}" alt="ESL Logo" style="height:50px;width:auto">
    <div>
      <span class="demo-badge">DEMO - NOT FOR PRODUCTION</span>
      <h3 style="margin-top:4px">About - ESL License Monitor</h3>
    </div>
  </div>
  <p>Created by <strong>ESL (Engineering Software Lab)</strong> as a demonstration tool for
  monitoring Parasoft DTP license server usage. This dashboard parses
  <code>ls_access.log</code> files and visualises checkout/checkin sessions.</p>
  <p><strong>Disclaimer:</strong> This is demo software provided "AS IS". ESL makes no
  warranties regarding accuracy, security, reliability, or fitness for purpose.
  No responsibility is assumed for any use of the data shown. Not for production use.</p>
</div>

<!-- Toolbar: Date Filter + CSV Export -->
<div class="toolbar">
  <label for="dateFrom">From:</label>
  <input type="date" id="dateFrom" value="{date_from}">
  <label for="dateTo">To:</label>
  <input type="date" id="dateTo" value="{date_to}">
  <button class="btn-filter" onclick="filterByDate()">Filter</button>
  <button class="btn-reset" onclick="resetFilter()">Reset</button>
  <span style="flex:1"></span>
  <button class="btn-csv" onclick="exportTableCSV()">Export Table CSV</button>
  <button class="btn-csv-sessions" onclick="exportSessionsCSV()">Export Sessions CSV</button>
</div>

<!-- Summary Cards -->
<div class="cards">
  <div class="card"><div class="icon">&#128202;</div><div class="value" id="cardSessions">{summary['total_sessions']:,}</div><div class="label">Total Sessions</div></div>
  <div class="card"><div class="icon">&#9201;</div><div class="value" id="cardHours">{_fmt_hours(summary['total_hours'])}</div><div class="label">Total Hours</div></div>
  <div class="card"><div class="icon">&#128100;</div><div class="value" id="cardUsers">{len(summary['unique_users'])}</div><div class="label">Unique Users</div></div>
  <div class="card"><div class="icon">&#128230;</div><div class="value" id="cardProducts">{len(summary['unique_products'])}</div><div class="label">Unique Products</div></div>
  <div class="card"><div class="icon">&#128421;</div><div class="value" id="cardPlatforms">{len(summary['unique_platforms'])}</div><div class="label">Unique Platforms</div></div>
  <div class="card"><div class="icon">&#128197;</div><div class="value" id="cardDays">{active_days}</div><div class="label">Active Days</div></div>
</div>

<!-- Charts -->
<div class="charts-grid">

  <div class="chart-box">
    <h3>Sessions per Period (by Product)</h3>
    <canvas id="chartSessionsPeriod"></canvas>
  </div>

  <div class="chart-box">
    <h3>Hours per Period (by Product)</h3>
    <canvas id="chartHoursPeriod"></canvas>
  </div>

  <div class="chart-box">
    <h3>Platform Distribution (Sessions)</h3>
    <canvas id="chartPlatform"></canvas>
  </div>

  <div class="chart-box">
    <h3>Product Distribution (Hours)</h3>
    <canvas id="chartProduct"></canvas>
  </div>

  <div class="chart-box">
    <h3>Usage by User (Hours)</h3>
    <canvas id="chartUsers"></canvas>
  </div>

  {"<div class='chart-box'><h3>Daily Trend (Sessions)</h3><canvas id='chartDailyTrend'></canvas></div>" if period == "daily" else ""}

</div>

<!-- Detailed Table -->
<table id="detailTable">
<thead><tr>{th_cells}</tr></thead>
<tbody>
{table_rows}
</tbody>
</table>

</div><!-- /container -->

<footer>
  <img src="{_esc(logo_b64)}" alt="ESL" style="height:30px;width:auto;vertical-align:middle;margin-right:8px">
  ESL (Engineering Software Lab) - License Monitor Demo &nbsp;|&nbsp; Generated {_esc(now_str)}<br>
  <span style="color:#e15759;font-weight:600">DEMO SOFTWARE - PROVIDED "AS IS" - NO WARRANTY - NOT FOR PRODUCTION USE</span>
</footer>

<script>
{_sortable_js()}

// --- Embedded session data for CSV export ---
var allSessions = {_js_str(session_csv_data)};

// --- Table data for date filtering ---
var allPeriodData = {_js_str(_period_data_for_js(period_data))};

// --- CSV Export: visible table ---
function exportTableCSV() {{
    var table = document.getElementById('detailTable');
    var rows = table.querySelectorAll('tr');
    var csv = [];
    rows.forEach(function(row) {{
        var cols = row.querySelectorAll('th, td');
        var rowData = [];
        cols.forEach(function(col) {{
            var text = col.textContent.replace(/"/g, '""');
            rowData.push('"' + text + '"');
        }});
        csv.push(rowData.join(','));
    }});
    downloadCSV(csv.join('\\n'), 'license_report_{_esc(period)}_table.csv');
}}

// --- CSV Export: all sessions ---
function exportSessionsCSV() {{
    var headers = ['Start Time','End Time','Duration (min)','User','Hostname','IP','Platform','Product','Features','Is Probe','Renewals'];
    var csv = [headers.map(function(h){{ return '"'+h+'"'; }}).join(',')];
    var fromD = document.getElementById('dateFrom').value;
    var toD = document.getElementById('dateTo').value;
    allSessions.forEach(function(s) {{
        if (fromD && s.start < fromD) return;
        if (toD && s.start > toD + 'T23:59:59') return;
        csv.push([
            '"'+s.start+'"','"'+s.end+'"',s.dur,'"'+s.user+'"','"'+s.host+'"',
            '"'+s.ip+'"','"'+s.plat+'"','"'+s.prod+'"','"'+s.feat.replace(/"/g,'""')+'"',
            s.probe, s.renew
        ].join(','));
    }});
    downloadCSV(csv.join('\\n'), 'license_sessions_export.csv');
}}

function downloadCSV(csvContent, filename) {{
    var blob = new Blob([csvContent], {{type: 'text/csv;charset=utf-8;'}});
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}}

// --- Recalculate summary cards from filtered sessions ---
function updateCards(fromD, toD) {{
    var sessions = 0, hours = 0;
    var users = {{}}, products = {{}}, platforms = {{}}, days = {{}};
    allSessions.forEach(function(s) {{
        var d = s.start.substring(0, 10);
        if (fromD && d < fromD) return;
        if (toD && d > toD) return;
        sessions++;
        hours += s.dur / 60.0;
        users[s.user] = 1;
        products[s.prod] = 1;
        platforms[s.plat] = 1;
        days[d] = 1;
    }});
    document.getElementById('cardSessions').textContent = sessions.toLocaleString();
    document.getElementById('cardHours').textContent = hours.toFixed(2);
    document.getElementById('cardUsers').textContent = Object.keys(users).length;
    document.getElementById('cardProducts').textContent = Object.keys(products).length;
    document.getElementById('cardPlatforms').textContent = Object.keys(platforms).length;
    document.getElementById('cardDays').textContent = Object.keys(days).length;
}}

// --- Date filter ---
function filterByDate() {{
    var fromD = document.getElementById('dateFrom').value;
    var toD = document.getElementById('dateTo').value;
    var tbody = document.getElementById('detailTable').tBodies[0];
    var rows = tbody.querySelectorAll('tr');
    rows.forEach(function(row) {{
        var label = row.cells[0].textContent.trim();
        var show = true;
        if (fromD && label < fromD) show = false;
        if (toD && label > toD) show = false;
        row.style.display = show ? '' : 'none';
    }});
    updateCards(fromD, toD);
}}

function resetFilter() {{
    document.getElementById('dateFrom').value = '{date_from}';
    document.getElementById('dateTo').value = '{date_to}';
    var tbody = document.getElementById('detailTable').tBodies[0];
    tbody.querySelectorAll('tr').forEach(function(row) {{ row.style.display = ''; }});
    updateCards('', '');
}}

// --- Chart data ---
var periodLabels = {_js_str(period_labels)};
var sessionDatasets = {_js_str(product_session_datasets)};
var hoursDatasets = {_js_str(product_hours_datasets)};
var platformLabels = {_js_str(platform_labels)};
var platformSessions = {_js_str(platform_sessions)};
var platformColors = {_js_str(platform_colors)};
var productLabels = {_js_str(product_labels)};
var productHours = {_js_str(product_hours_list)};
var productDonutColors = {_js_str(product_donut_colors)};
var userLabels = {_js_str(user_labels)};
var userHours = {_js_str(user_hours)};
var userColors = {_js_str(user_colors)};

var commonOpts = {{responsive:true, maintainAspectRatio:false, plugins:{{legend:{{position:'bottom'}}}}}};

// Sessions per period (stacked bar)
new Chart(document.getElementById('chartSessionsPeriod'), {{
  type:'bar',
  data:{{labels:periodLabels, datasets:sessionDatasets}},
  options:Object.assign({{}}, commonOpts, {{scales:{{x:{{stacked:true}},y:{{stacked:true,beginAtZero:true,title:{{display:true,text:'Sessions'}}}}}}}})
}});

// Hours per period (stacked bar)
new Chart(document.getElementById('chartHoursPeriod'), {{
  type:'bar',
  data:{{labels:periodLabels, datasets:hoursDatasets}},
  options:Object.assign({{}}, commonOpts, {{scales:{{x:{{stacked:true}},y:{{stacked:true,beginAtZero:true,title:{{display:true,text:'Hours'}}}}}}}})
}});

// Platform doughnut
new Chart(document.getElementById('chartPlatform'), {{
  type:'doughnut',
  data:{{labels:platformLabels, datasets:[{{data:platformSessions, backgroundColor:platformColors}}]}},
  options:Object.assign({{}}, commonOpts)
}});

// Product doughnut
new Chart(document.getElementById('chartProduct'), {{
  type:'doughnut',
  data:{{labels:productLabels, datasets:[{{data:productHours, backgroundColor:productDonutColors}}]}},
  options:Object.assign({{}}, commonOpts)
}});

// Users horizontal bar
new Chart(document.getElementById('chartUsers'), {{
  type:'bar',
  data:{{labels:userLabels, datasets:[{{label:'Hours',data:userHours,backgroundColor:userColors}}]}},
  options:Object.assign({{}}, commonOpts, {{indexAxis:'y',scales:{{x:{{beginAtZero:true,title:{{display:true,text:'Hours'}}}}}}}})
}});

// Daily trend line (only for daily period)
{"" if period != "daily" else f"""
var dailyTrendLabels = {_js_str(daily_trend_labels)};
var dailyTrendData = {_js_str(daily_trend_data)};
new Chart(document.getElementById('chartDailyTrend'), {{
  type:'line',
  data:{{labels:dailyTrendLabels, datasets:[{{label:'Sessions',data:dailyTrendData,borderColor:'{CHART_COLORS[0]}',backgroundColor:'{CHART_COLORS[0]}22',fill:true,tension:0.3}}]}},
  options:Object.assign({{}}, commonOpts, {{scales:{{y:{{beginAtZero:true,title:{{display:true,text:'Sessions'}}}}}}}})
}});
"""}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_html_report(
    sessions: list[Session],
    summary: dict,
    period_data: list[dict],
    output_dir: Path | str,
    report_name: str = "license_report",
    period: str = "daily",
) -> Path:
    """Generate a self-contained HTML dashboard report.

    Parameters
    ----------
    sessions:
        List of Session objects.
    summary:
        Dict returned by ``get_summary()``.
    period_data:
        List of dicts returned by ``aggregate_by_period()``.
    output_dir:
        Directory to write the HTML file into.
    report_name:
        Prefix for the filename.
    period:
        Period granularity (``"daily"``, ``"weekly"``, ``"monthly"``, ``"yearly"``).

    Returns
    -------
    Path
        Path to the generated HTML file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    html_content = _build_html(sessions, summary, period_data, period, report_name)
    out_path = output_dir / f"{report_name}_{period}.html"
    out_path.write_text(html_content, encoding="utf-8")
    logger.info("HTML report written to %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, headers: list[str], rows: list[list]) -> Path:
    """Write a CSV file and return its path."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)
    logger.info("CSV written to %s (%d rows)", path, len(rows))
    return path


def _sessions_csv(
    sessions: list[Session],
    output_dir: Path,
    report_name: str,
) -> Path:
    """One row per session."""
    headers = [
        "start_time", "end_time", "duration_min", "user", "os_user",
        "hostname", "ip", "platform", "product", "features",
        "license_id", "is_probe", "renewals",
    ]
    rows = []
    for s in sessions:
        rows.append([
            s.start_time.isoformat() if s.start_time else "",
            s.end_time.isoformat() if s.end_time else "",
            round(s.duration_minutes, 4),
            s.login_user,
            s.os_user,
            s.hostname,
            s.ip,
            s.platform,
            s.product,
            "; ".join(s.features),
            s.license_id,
            s.is_probe,
            s.renewals,
        ])
    return _write_csv(output_dir / f"{report_name}_sessions.csv", headers, rows)


def _period_summary_csv(
    period_data: list[dict],
    summary: dict,
    output_dir: Path,
    report_name: str,
    period: str,
) -> Path:
    """Period aggregation CSV with per-product and per-platform columns."""
    all_products = sorted(summary.get("unique_products", []))
    all_platforms = sorted(summary.get("unique_platforms", []))

    headers = [
        "period_label", "total_sessions", "total_hours", "probes",
        "unique_users", "unique_hosts",
    ]
    for prod in all_products:
        headers.append(f"{prod}_sessions")
        headers.append(f"{prod}_hours")
    for plat in all_platforms:
        headers.append(f"{plat}_sessions")
        headers.append(f"{plat}_hours")

    rows = []
    for p in period_data:
        row: list[Any] = [
            p["period_label"],
            p["total_sessions"],
            round(p["total_hours"], 4),
            p["total_probes"],
            p["unique_users"],
            p["unique_hosts"],
        ]
        for prod in all_products:
            prod_data = p.get("by_product", {}).get(prod, {})
            row.append(prod_data.get("sessions", 0))
            row.append(round(prod_data.get("hours", 0), 4))
        for plat in all_platforms:
            plat_data = p.get("by_platform", {}).get(plat, {})
            row.append(plat_data.get("sessions", 0))
            row.append(round(plat_data.get("hours", 0), 4))
        rows.append(row)

    return _write_csv(
        output_dir / f"{report_name}_{period}_summary.csv", headers, rows,
    )


def _product_summary_csv(
    sessions: list[Session],
    output_dir: Path,
    report_name: str,
) -> Path:
    """One row per product."""
    products: dict[str, dict] = defaultdict(lambda: {
        "sessions": 0, "hours": 0.0, "users": set(), "platforms": set(),
    })
    for s in sessions:
        rec = products[s.product]
        rec["sessions"] += 1
        rec["hours"] += s.duration_minutes / 60.0
        rec["users"].add(s.login_user)
        rec["platforms"].add(s.platform)

    headers = ["product", "total_sessions", "total_hours", "unique_users", "platforms_used"]
    rows = []
    for prod in sorted(products):
        rec = products[prod]
        rows.append([
            prod,
            rec["sessions"],
            round(rec["hours"], 4),
            len(rec["users"]),
            "; ".join(sorted(rec["platforms"])),
        ])
    return _write_csv(output_dir / f"{report_name}_product_summary.csv", headers, rows)


def _user_summary_csv(
    sessions: list[Session],
    output_dir: Path,
    report_name: str,
) -> Path:
    """One row per user."""
    users: dict[str, dict] = defaultdict(lambda: {
        "sessions": 0, "hours": 0.0, "products": set(), "platforms": set(),
        "first_seen": None, "last_seen": None,
    })
    for s in sessions:
        rec = users[s.login_user]
        rec["sessions"] += 1
        rec["hours"] += s.duration_minutes / 60.0
        rec["products"].add(s.product)
        rec["platforms"].add(s.platform)
        if rec["first_seen"] is None or s.start_time < rec["first_seen"]:
            rec["first_seen"] = s.start_time
        if rec["last_seen"] is None or s.start_time > rec["last_seen"]:
            rec["last_seen"] = s.start_time

    headers = [
        "user", "total_sessions", "total_hours", "products_used",
        "platforms_used", "first_seen", "last_seen",
    ]
    rows = []
    for user in sorted(users):
        rec = users[user]
        rows.append([
            user,
            rec["sessions"],
            round(rec["hours"], 4),
            "; ".join(sorted(rec["products"])),
            "; ".join(sorted(rec["platforms"])),
            rec["first_seen"].isoformat() if rec["first_seen"] else "",
            rec["last_seen"].isoformat() if rec["last_seen"] else "",
        ])
    return _write_csv(output_dir / f"{report_name}_user_summary.csv", headers, rows)


def generate_csv_reports(
    sessions: list[Session],
    summary: dict,
    period_data: list[dict],
    output_dir: Path | str,
    report_name: str = "license_report",
    period: str = "daily",
) -> list[Path]:
    """Generate all CSV reports.

    Parameters
    ----------
    sessions:
        List of Session objects.
    summary:
        Dict returned by ``get_summary()``.
    period_data:
        List of dicts returned by ``aggregate_by_period()``.
    output_dir:
        Directory to write CSV files into.
    report_name:
        Prefix for filenames.
    period:
        Period granularity used for the period-summary CSV filename.

    Returns
    -------
    list[Path]
        Paths to all generated CSV files.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = [
        _sessions_csv(sessions, output_dir, report_name),
        _period_summary_csv(period_data, summary, output_dir, report_name, period),
        _product_summary_csv(sessions, output_dir, report_name),
        _user_summary_csv(sessions, output_dir, report_name),
    ]
    return paths


def generate_all_reports(
    sessions: list[Session],
    summary: dict,
    output_dir: Path | str,
    report_name: str = "license_report",
) -> dict:
    """Generate HTML and CSV reports for all period granularities.

    Produces daily, weekly, monthly, and yearly reports.

    Parameters
    ----------
    sessions:
        List of Session objects.
    summary:
        Dict returned by ``get_summary()``.
    output_dir:
        Directory for all output files.
    report_name:
        Prefix for filenames.

    Returns
    -------
    dict
        Mapping ``period -> {"html": Path, "csv": [Path, ...]}``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, Any]] = {}

    for period in ("daily", "weekly", "monthly", "yearly"):
        period_data = aggregate_by_period(sessions, period)

        html_path = generate_html_report(
            sessions, summary, period_data, output_dir, report_name, period,
        )
        csv_paths = generate_csv_reports(
            sessions, summary, period_data, output_dir, report_name, period,
        )
        results[period] = {"html": html_path, "csv": csv_paths}

    logger.info("All reports generated in %s", output_dir)
    return results
