"""Static weather-only dashboard generated from a trusted release export."""

from __future__ import annotations

import calendar
import csv
import html
import json
from datetime import date
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.io import to_html

from .io_utils import atomic_replace, sha256_file


WEATHER_CSV = "weather_summary.csv"
WEATHER_METADATA = "weather_summary.metadata.json"
NASA_DAILY_API = "https://power.larc.nasa.gov/docs/services/api/temporal/daily/"
NASA_METHOD = "https://power.larc.nasa.gov/docs/methodology/data/sources/"
NASA_POLICY = (
    "https://www.earthdata.nasa.gov/engage/open-data-services-software/"
    "data-use-policy"
)

LOCATION_COLORS = {
    "nairobi": "#146c72",
    "mombasa": "#dc6b38",
    "kisumu": "#635b9e",
}


def generate_public_weather_dashboard(
    report_dir: Path, *, output_path: Path = Path("site/index.html")
) -> dict[str, Any]:
    """Render a standalone public page without reading the exchange export."""

    bundle = load_trusted_weather_export(report_dir)
    rows = bundle["weather_rows"]
    release_id = bundle["release_id"]
    coverage = bundle["coverage"]
    months = _month_range(bundle["start_date"], bundle["end_date"])
    weather_observations = sum(_integer(row, "observed_day_count") for row in rows)

    temperature = _weather_figure(
        rows,
        months=months,
        value_field="mean_daily_temperature_c",
        y_title="Monthly mean temperature (°C)",
    )
    precipitation = _weather_figure(
        rows,
        months=months,
        value_field="sum_daily_precipitation_mm",
        y_title="Monthly precipitation total (mm)",
        zero_base=True,
    )
    charts = (
        to_html(
            temperature,
            include_plotlyjs=True,
            full_html=False,
            div_id="public-temperature-chart",
            config={"displayModeBar": False, "responsive": True},
        ),
        to_html(
            precipitation,
            include_plotlyjs=False,
            full_html=False,
            div_id="public-precipitation-chart",
            config={"displayModeBar": False, "responsive": True},
        ),
    )
    document = _document(
        release_id=release_id,
        start_date=bundle["start_date"],
        end_date=bundle["end_date"],
        coverage=coverage,
        months=months,
        rows=rows,
        weather_observations=weather_observations,
        charts=charts,
    )
    document = "\n".join(line.rstrip() for line in document.splitlines()) + "\n"
    atomic_replace(output_path, document.encode("utf-8"))
    return {
        "path": str(output_path),
        "sha256": sha256_file(output_path),
        "release_id": release_id,
        "weather_observations": weather_observations,
        "weather_monthly_rows": len(rows),
        "start_date": bundle["start_date"],
        "end_date": bundle["end_date"],
    }


def load_trusted_weather_export(report_dir: Path) -> dict[str, Any]:
    """Load and validate only the public-safe weather summary and metadata."""

    weather_path = report_dir / WEATHER_CSV
    metadata_path = report_dir / WEATHER_METADATA
    missing = [str(path) for path in (weather_path, metadata_path) if not path.is_file()]
    if missing:
        raise RuntimeError("trusted weather export is incomplete: " + ", ".join(missing))

    with weather_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = [dict(row) for row in csv.DictReader(stream)]
    if not rows:
        raise RuntimeError("trusted weather export is empty")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    release_values = [
        *(str(row.get("release_id", "")) for row in rows),
        str(metadata.get("release_id", "")),
    ]
    if any(not value for value in release_values):
        raise RuntimeError("trusted weather export contains a missing release identity")
    release_ids = set(release_values)
    if len(release_ids) != 1:
        raise RuntimeError(
            "trusted weather export has mismatched release identities: "
            + ", ".join(sorted(release_ids))
        )
    release_id = next(iter(release_ids))
    if report_dir.name.startswith("release_") and report_dir.name != release_id:
        raise RuntimeError(
            f"report directory identity {report_dir.name} does not match {release_id}"
        )
    if metadata.get("domain") != "weather":
        raise RuntimeError("weather metadata domain is invalid")
    if any(row.get("domain") != "weather" for row in rows):
        raise RuntimeError("weather export contains another domain")

    keys = [(row.get("location_id", ""), row.get("month_start", "")) for row in rows]
    if any(not all(key) for key in keys) or len(keys) != len(set(keys)):
        raise RuntimeError("weather export contains missing or duplicate reporting keys")

    coverage = (metadata.get("coverage") or {}).get("weather_by_location")
    if not isinstance(coverage, dict) or not coverage:
        raise RuntimeError("weather coverage metadata is missing")
    normalized_coverage = {str(name).lower(): values for name, values in coverage.items()}
    row_locations = {row["location_id"].lower() for row in rows}
    if set(normalized_coverage) != row_locations:
        raise RuntimeError("weather rows and location coverage do not match")

    for row in rows:
        month = _iso_date(row["month_start"], "month_start")
        if month.day != 1:
            raise RuntimeError("weather month_start must be the first day of a month")
        observed = _integer(row, "observed_day_count")
        expected = _integer(row, "expected_day_count")
        if observed > expected or expected != calendar.monthrange(month.year, month.month)[1]:
            raise RuntimeError(f"weather coverage is invalid: {row}")
        _number(row, "mean_daily_temperature_c")
        _number(row, "sum_daily_precipitation_mm")

    for location, values in normalized_coverage.items():
        selected = [row for row in rows if row["location_id"].lower() == location]
        observed = sum(_integer(row, "observed_day_count") for row in selected)
        if int(values.get("observation_count", -1)) != observed:
            raise RuntimeError(f"weather coverage count does not match for {location}")
        first_month = min(_iso_date(row["month_start"], "month_start") for row in selected)
        last_month = max(_iso_date(row["month_start"], "month_start") for row in selected)
        last_date = date(
            last_month.year,
            last_month.month,
            calendar.monthrange(last_month.year, last_month.month)[1],
        )
        if values.get("start_date") != first_month.isoformat() or values.get(
            "end_date"
        ) != last_date.isoformat():
            raise RuntimeError(f"weather coverage dates do not match for {location}")

    start_date = min(str(values["start_date"]) for values in normalized_coverage.values())
    end_date = max(str(values["end_date"]) for values in normalized_coverage.values())
    return {
        "release_id": release_id,
        "weather_rows": rows,
        "coverage": normalized_coverage,
        "start_date": start_date,
        "end_date": end_date,
    }


def _integer(row: dict[str, str], field: str) -> int:
    try:
        return int(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid integer field {field}: {row.get(field)!r}") from exc


def _number(row: dict[str, str], field: str) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid numeric field {field}: {row.get(field)!r}") from exc


def _iso_date(raw: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid {label}: {raw!r}") from exc
    if parsed.isoformat() != raw:
        raise RuntimeError(f"invalid {label}: {raw!r}")
    return parsed


def _month_range(start: str, end: str) -> list[str]:
    cursor = _iso_date(start, "coverage start").replace(day=1)
    finish = _iso_date(end, "coverage end").replace(day=1)
    months: list[str] = []
    while cursor <= finish:
        months.append(cursor.isoformat())
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return months


def _location_order(locations: set[str]) -> list[str]:
    preferred = {"nairobi": 0, "mombasa": 1, "kisumu": 2}
    return sorted(locations, key=lambda item: (preferred.get(item, 99), item))


def _weather_figure(
    rows: list[dict[str, str]],
    *,
    months: list[str],
    value_field: str,
    y_title: str,
    zero_base: bool = False,
) -> go.Figure:
    figure = go.Figure()
    for location in _location_order({row["location_id"].lower() for row in rows}):
        by_month = {
            row["month_start"]: _number(row, value_field)
            for row in rows
            if row["location_id"].lower() == location
        }
        figure.add_trace(
            go.Scatter(
                x=months,
                y=[by_month.get(month) for month in months],
                name=location.title(),
                mode="lines+markers",
                line={"color": LOCATION_COLORS.get(location, "#4f6975"), "width": 3},
                marker={"size": 8},
                connectgaps=False,
                hovertemplate=(
                    "%{x|%b %Y}<br>%{y:.3f}<extra>" + location.title() + "</extra>"
                ),
            )
        )
    figure.update_layout(
        template="plotly_white",
        height=340,
        margin={"l": 62, "r": 20, "t": 30, "b": 50},
        font={"family": "Segoe UI, Arial, sans-serif", "size": 13, "color": "#20313a"},
        legend={"orientation": "h", "y": 1.17, "x": 0},
        hovermode="x unified",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )
    figure.update_xaxes(
        tickmode="array",
        tickvals=months,
        ticktext=[_iso_date(value, "month").strftime("%b") for value in months],
        showgrid=False,
        fixedrange=True,
    )
    figure.update_yaxes(
        title=y_title,
        rangemode="tozero" if zero_base else "normal",
        gridcolor="#dfe7e7",
        zeroline=False,
        fixedrange=True,
    )
    return figure


def _coverage_cards(coverage: dict[str, Any]) -> str:
    cards = []
    for location in _location_order(set(coverage)):
        values = coverage[location]
        cards.append(
            '<article class="coverage-card">'
            f'<span class="dot dot-{html.escape(location)}"></span>'
            f"<h3>{html.escape(location.title())}</h3>"
            f"<strong>{int(values['observation_count'])} days</strong>"
            f"<p>{html.escape(str(values['start_date']))}<br>to "
            f"{html.escape(str(values['end_date']))}</p></article>"
        )
    return "".join(cards)


def _coverage_matrix(rows: list[dict[str, str]], months: list[str]) -> str:
    by_key = {(row["location_id"].lower(), row["month_start"]): row for row in rows}
    headings = "".join(
        f"<th>{_iso_date(month, 'month').strftime('%b')}</th>" for month in months
    )
    body = []
    locations = _location_order({row["location_id"].lower() for row in rows})
    for location in locations:
        cells = []
        for month in months:
            row = by_key.get((location, month))
            if row is None:
                cells.append('<td class="missing" aria-label="No data">—</td>')
            else:
                cells.append(
                    '<td class="complete">'
                    f"{_integer(row, 'observed_day_count')} / "
                    f"{_integer(row, 'expected_day_count')}</td>"
                )
        body.append(
            f"<tr><th>{html.escape(location.title())}</th>{''.join(cells)}</tr>"
        )
    return (
        '<div class="table-wrap"><table class="coverage-table">'
        f"<thead><tr><th>Location</th>{headings}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _exact_table(rows: list[dict[str, str]]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{html.escape(row['month_start'][:7])}</td>"
        f"<td>{html.escape(row['location_id'].title())}</td>"
        f"<td class=\"num\">{_number(row, 'mean_daily_temperature_c'):.6f}</td>"
        f"<td class=\"num\">{_number(row, 'sum_daily_precipitation_mm'):.6f}</td>"
        f"<td class=\"num\">{_integer(row, 'observed_day_count')} / "
        f"{_integer(row, 'expected_day_count')}</td>"
        "</tr>"
        for row in sorted(rows, key=lambda item: (item["month_start"], item["location_id"]))
    )
    return (
        '<div class="table-wrap"><table class="exact-table"><thead><tr>'
        "<th>Month</th><th>Representative point</th>"
        '<th class="num">Mean °C</th><th class="num">Precipitation mm</th>'
        '<th class="num">Observed / expected days</th>'
        f"</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _document(
    *,
    release_id: str,
    start_date: str,
    end_date: str,
    coverage: dict[str, Any],
    months: list[str],
    rows: list[dict[str, str]],
    weather_observations: int,
    charts: tuple[str, str],
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Verified historical NASA POWER weather reporting for three Kenyan representative points.">
  <title>Kenya weather historical reporting snapshot</title>
  <style>
    :root {{ color-scheme:light; --ink:#183038; --muted:#607078; --paper:#fff; --wash:#edf4f2; --line:#dbe6e3; --teal:#146c72; --orange:#dc6b38; --violet:#635b9e; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:auto; }}
    body {{ margin:0; color:var(--ink); background:#e7efed; font-family:"Segoe UI",Arial,sans-serif; line-height:1.5; }}
    main {{ width:100%; max-width:1220px; margin:0 auto; overflow:hidden; background:var(--paper); min-height:100vh; box-shadow:0 0 42px rgba(31,56,60,.10); }}
    header {{ position:relative; overflow:hidden; padding:54px 64px 42px; color:#fff; background:linear-gradient(118deg,#123f46 0%,#176d70 68%,#2d827e 100%); }}
    header:after {{ content:""; position:absolute; width:330px; height:330px; border:1px solid rgba(255,255,255,.17); border-radius:50%; right:-100px; top:-155px; box-shadow:0 0 0 56px rgba(255,255,255,.045),0 0 0 112px rgba(255,255,255,.03); }}
    .eyebrow {{ display:inline-block; margin-bottom:17px; padding:5px 10px; border:1px solid rgba(255,255,255,.38); border-radius:999px; font-size:.75rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase; }}
    h1 {{ position:relative; z-index:1; max-width:720px; margin:0 0 13px; font-size:clamp(2.15rem,4vw,3.6rem); line-height:1.02; letter-spacing:-.045em; }}
    .lede {{ position:relative; z-index:1; max-width:750px; margin:0; color:#dbedeb; font-size:1.06rem; }}
    .release {{ position:relative; z-index:1; margin-top:22px; color:#bcd9d6; font-size:.84rem; }}
    .release code {{ color:#fff; }}
    .content {{ width:100%; min-width:0; padding:0 64px 66px; }}
    .facts {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin:-1px 0 34px; }}
    .fact {{ padding:21px 22px; border:1px solid var(--line); border-top:0; background:#fff; }}
    .fact strong {{ display:block; color:var(--teal); font-size:1.7rem; line-height:1.1; }}
    .fact span {{ color:var(--muted); font-size:.88rem; }}
    section {{ scroll-margin-top:16px; }}
    h2 {{ margin:40px 0 8px; font-size:1.55rem; letter-spacing:-.02em; }}
    h3 {{ margin:4px 0 2px; font-size:1rem; }}
    .section-intro {{ max-width:78ch; margin:0 0 18px; color:var(--muted); }}
    .chart-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    .panel {{ min-width:0; border:1px solid var(--line); border-radius:12px; background:#fff; overflow:hidden; }}
    .panel-title {{ padding:17px 20px 0; }}
    .panel-title span {{ color:var(--muted); font-size:.82rem; }}
    .chart,.js-plotly-plot,.plot-container {{ min-width:0; max-width:100%; }}
    .chart {{ min-height:340px; }}
    .coverage-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:20px 0; }}
    .coverage-card {{ position:relative; padding:18px 20px 17px 37px; border:1px solid var(--line); border-radius:10px; background:var(--wash); }}
    .coverage-card h3 {{ margin:0; }}
    .coverage-card strong {{ display:block; margin:3px 0; font-size:1.15rem; }}
    .coverage-card p {{ margin:0; color:var(--muted); font-size:.83rem; }}
    .dot {{ position:absolute; left:17px; top:23px; width:9px; height:9px; border-radius:50%; background:#4f6975; }}
    .dot-nairobi {{ background:var(--teal); }} .dot-mombasa {{ background:var(--orange); }} .dot-kisumu {{ background:var(--violet); }}
    .table-wrap {{ width:100%; overflow-x:auto; border:1px solid var(--line); border-radius:10px; }}
    table {{ width:100%; border-collapse:collapse; font-size:.88rem; }}
    th {{ text-align:left; background:#f1f6f5; color:#35515a; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }}
    tbody tr:last-child th,tbody tr:last-child td {{ border-bottom:0; }}
    td.num,th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .coverage-table td {{ text-align:center; font-variant-numeric:tabular-nums; }}
    .coverage-table .complete {{ color:#0d625c; background:#eff9f5; font-weight:650; }}
    .coverage-table .missing {{ color:#8b989c; background:#fafbfb; }}
    .exact-table {{ min-width:760px; }}
    .note {{ margin-top:24px; padding:20px 22px; border-left:4px solid var(--orange); background:#fff6ef; }}
    .note h3 {{ margin:0 0 5px; }} .note p {{ margin:0; color:#655d57; }}
    footer {{ margin-top:44px; padding-top:23px; border-top:1px solid var(--line); color:var(--muted); font-size:.86rem; }}
    footer a {{ color:var(--teal); }} footer p {{ margin:7px 0; }}
    @media (max-width:820px) {{ header {{ padding:39px 24px 34px; }} .content {{ padding:0 20px 45px; }} .facts,.chart-grid,.coverage-grid {{ grid-template-columns:1fr; }} .fact {{ border-top:1px solid var(--line); }} .facts {{ margin:20px 0 30px; }} h1 {{ font-size:2.35rem; }} .chart {{ min-height:320px; }} }}
  </style>
</head>
<body><main>
  <header>
    <div class="eyebrow">Historical reporting snapshot</div>
    <h1>Kenya weather,<br>month by month</h1>
    <p class="lede">A verified view of monthly temperature, precipitation and completeness at representative points for Nairobi, Mombasa and Kisumu. This public preview shows the weather domain; the platform also implements a separate exchange-rate pipeline.</p>
    <p class="release"><strong>Trusted release</strong> · <code>{html.escape(release_id)}</code></p>
  </header>
  <div class="content">
    <div class="facts" aria-label="Snapshot facts">
      <div class="fact"><strong>{weather_observations}</strong><span>complete daily weather observations</span></div>
      <div class="fact"><strong>{len(rows)}</strong><span>reported location-months</span></div>
      <div class="fact"><strong>Sep–Dec 2023</strong><span>historical reporting window</span></div>
    </div>

    <section id="weather-details">
      <h2>Monthly conditions</h2>
      <p class="section-intro">Lines stop where a location-month is absent. Missing September values for Mombasa and Kisumu remain null—they are not displayed as zero and are not connected across the gap.</p>
      <div class="chart-grid">
        <article class="panel"><div class="panel-title"><h3>Mean temperature</h3><span>Monthly mean of complete daily T2M values</span></div><div class="chart">{charts[0]}</div></article>
        <article class="panel"><div class="panel-title"><h3>Precipitation</h3><span>Monthly sum of complete daily PRECTOTCORR values</span></div><div class="chart">{charts[1]}</div></article>
      </div>
    </section>

    <section id="coverage">
      <h2>Coverage by representative point</h2>
      <p class="section-intro">Nairobi covers September–December 2023. Mombasa and Kisumu begin in October. Every reported month contains all expected calendar days.</p>
      <div class="coverage-grid">{_coverage_cards(coverage)}</div>
      {_coverage_matrix(rows, months)}
    </section>

    <section id="exact-values">
      <h2>Exact reported values</h2>
      <p class="section-intro">The same trusted monthly metrics used in the charts are shown to six decimal places for inspection.</p>
      {_exact_table(rows)}
    </section>

    <aside class="note">
      <h3>How to read this snapshot</h3>
      <p>NASA POWER meteorology is model/assimilation output. These are gridded estimates selected by representative coordinates—not weather-station observations and not measurements for an entire city. Grid resolution is approximately 0.5° latitude by 0.625° longitude.</p>
    </aside>

    <footer>
      <p><strong>Historical dates:</strong> {html.escape(start_date)} to {html.escape(end_date)} · <strong>Release:</strong> <code>{html.escape(release_id)}</code></p>
      <p><strong>Source:</strong> NASA POWER Daily API, T2M (°C) and PRECTOTCORR (mm/day), with MERRA-2/GEOS-IT provenance. <a href="{NASA_DAILY_API}">Daily API documentation</a> · <a href="{NASA_METHOD}">methodology and data sources</a> · <a href="{NASA_POLICY}">NASA Earthdata data-use policy</a>.</p>
      <p>Plotly is bundled in this file. The dashboard requires no CDN, API request, credential or network connection to display.</p>
    </footer>
  </div>
</main>
<script>
  window.addEventListener("load", function () {{
    if (window.location.hash) {{
      window.setTimeout(function () {{
        var target = document.querySelector(window.location.hash);
        if (target) target.scrollIntoView({{behavior:"auto", block:"start"}});
      }}, 300);
    }}
  }});
</script>
</body></html>"""
