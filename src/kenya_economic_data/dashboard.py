"""Offline HTML dashboard generated only from trusted release exports."""

from __future__ import annotations

import csv
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.io import to_html

from .io_utils import atomic_replace, sha256_file


EXCHANGE_CSV = "exchange_summary.csv"
WEATHER_CSV = "weather_summary.csv"
EXCHANGE_METADATA = "exchange_summary.metadata.json"
WEATHER_METADATA = "weather_summary.metadata.json"
DASHBOARD_FILE = "results_dashboard.html"

COLORS = {
    "EUR": "#0f766e",
    "GBP": "#7c3aed",
    "USD": "#c2410c",
    "nairobi": "#2563eb",
    "mombasa": "#db2777",
    "kisumu": "#16a34a",
}


def generate_results_dashboard(
    report_dir: Path, *, output_path: Path | None = None
) -> dict[str, Any]:
    """Validate trusted exports and atomically render a standalone HTML report."""

    bundle = load_trusted_exports(report_dir)
    exchange = bundle["exchange_rows"]
    weather = bundle["weather_rows"]
    release_id = bundle["release_id"]
    coverage = bundle["coverage"]
    exchange_observations = sum(
        _integer(row, "publication_observation_count") for row in exchange
    )
    weather_observations = sum(_integer(row, "observed_day_count") for row in weather)

    exchange_figure = _exchange_figure(exchange)
    temperature_figure = _weather_figure(
        weather,
        value_field="mean_daily_temperature_c",
        y_title="Monthly mean temperature (°C)",
    )
    precipitation_figure = _weather_figure(
        weather,
        value_field="sum_daily_precipitation_mm",
        y_title="Monthly precipitation total (mm)",
        zero_base=True,
    )
    chart_html = [
        to_html(
            exchange_figure,
            include_plotlyjs=True,
            full_html=False,
            div_id="exchange-rate-chart",
            config={"displayModeBar": False, "responsive": True},
        ),
        to_html(
            temperature_figure,
            include_plotlyjs=False,
            full_html=False,
            div_id="weather-temperature-chart",
            config={"displayModeBar": False, "responsive": True},
        ),
        to_html(
            precipitation_figure,
            include_plotlyjs=False,
            full_html=False,
            div_id="weather-precipitation-chart",
            config={"displayModeBar": False, "responsive": True},
        ),
    ]
    export_time = _export_time(report_dir, release_id)
    document = _document(
        release_id=release_id,
        export_time=export_time,
        coverage=coverage,
        exchange_observations=exchange_observations,
        weather_observations=weather_observations,
        exchange_rows=exchange,
        weather_rows=weather,
        charts=chart_html,
    )
    destination = output_path or report_dir / DASHBOARD_FILE
    atomic_replace(destination, document.encode("utf-8"))
    return {
        "path": str(destination),
        "sha256": sha256_file(destination),
        "release_id": release_id,
        "exchange_observations": exchange_observations,
        "weather_observations": weather_observations,
        "exchange_monthly_rows": len(exchange),
        "weather_monthly_rows": len(weather),
        "export_time": export_time,
    }


def load_trusted_exports(report_dir: Path) -> dict[str, Any]:
    """Load and validate both trusted domain exports without touching raw data."""

    exchange_path = report_dir / EXCHANGE_CSV
    weather_path = report_dir / WEATHER_CSV
    exchange_metadata_path = report_dir / EXCHANGE_METADATA
    weather_metadata_path = report_dir / WEATHER_METADATA
    required = (
        exchange_path,
        weather_path,
        exchange_metadata_path,
        weather_metadata_path,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("trusted report export is incomplete: " + ", ".join(missing))

    exchange_rows = _csv_rows(exchange_path)
    weather_rows = _csv_rows(weather_path)
    if not exchange_rows or not weather_rows:
        raise RuntimeError("trusted report exports must contain both domains")
    exchange_metadata = json.loads(exchange_metadata_path.read_text(encoding="utf-8"))
    weather_metadata = json.loads(weather_metadata_path.read_text(encoding="utf-8"))

    release_values = [
        *(str(row.get("release_id", "")) for row in exchange_rows + weather_rows),
        str(exchange_metadata.get("release_id", "")),
        str(weather_metadata.get("release_id", "")),
    ]
    if any(not value for value in release_values):
        raise RuntimeError("trusted exports contain a missing release identity")
    release_ids = set(release_values)
    if len(release_ids) != 1:
        raise RuntimeError(
            "trusted exchange and weather exports have mismatched release identities: "
            + ", ".join(sorted(release_ids))
        )
    release_id = next(iter(release_ids))
    if report_dir.name.startswith("release_") and report_dir.name != release_id:
        raise RuntimeError(
            f"report directory identity {report_dir.name} does not match {release_id}"
        )
    if exchange_metadata.get("domain") != "exchange":
        raise RuntimeError("exchange metadata domain is invalid")
    if weather_metadata.get("domain") != "weather":
        raise RuntimeError("weather metadata domain is invalid")
    if any(row.get("domain") != "exchange" for row in exchange_rows):
        raise RuntimeError("exchange export contains another domain")
    if any(row.get("domain") != "weather" for row in weather_rows):
        raise RuntimeError("weather export contains another domain")
    exchange_coverage = exchange_metadata.get("coverage")
    weather_coverage = weather_metadata.get("coverage")
    if not isinstance(exchange_coverage, dict) or exchange_coverage != weather_coverage:
        raise RuntimeError("trusted export coverage metadata does not match")

    _unique_keys(exchange_rows, ("currency_code", "month_start"), "exchange")
    _unique_keys(weather_rows, ("location_id", "month_start"), "weather")
    for row in weather_rows:
        observed = _integer(row, "observed_day_count")
        expected = _integer(row, "expected_day_count")
        if observed > expected:
            raise RuntimeError(f"weather coverage exceeds expected days: {row}")

    return {
        "release_id": release_id,
        "coverage": exchange_coverage,
        "exchange_rows": exchange_rows,
        "weather_rows": weather_rows,
    }


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _unique_keys(
    rows: list[dict[str, str]], fields: tuple[str, ...], domain: str
) -> None:
    keys = [tuple(row.get(field, "") for field in fields) for row in rows]
    if any(not all(key) for key in keys) or len(keys) != len(set(keys)):
        raise RuntimeError(f"{domain} export contains missing or duplicate reporting keys")


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


def _exchange_figure(rows: list[dict[str, str]]) -> go.Figure:
    figure = go.Figure()
    for currency in sorted({row["currency_code"] for row in rows}):
        selected = sorted(
            (row for row in rows if row["currency_code"] == currency),
            key=lambda row: row["month_start"],
        )
        figure.add_trace(
            go.Scatter(
                x=[row["month_start"] for row in selected],
                y=[
                    _number(row, "mean_published_daily_mean_rate_kes_per_foreign_unit")
                    for row in selected
                ],
                name=currency,
                mode="lines+markers",
                line={"color": COLORS.get(currency), "width": 3},
                marker={"size": 8},
                connectgaps=False,
                hovertemplate=(
                    "%{x|%b %Y}<br>%{y:.3f} KES per 1 foreign unit<extra>"
                    + currency
                    + "</extra>"
                ),
            )
        )
    _style_figure(
        figure,
        y_title="KES per 1 unit of foreign currency",
        x_values=sorted({row["month_start"] for row in rows}),
    )
    return figure


def _weather_figure(
    rows: list[dict[str, str]], *, value_field: str, y_title: str,
    zero_base: bool = False,
) -> go.Figure:
    figure = go.Figure()
    all_months = sorted({row["month_start"] for row in rows})
    locations = sorted(
        {row["location_id"] for row in rows},
        key=lambda location: (
            min(row["month_start"] for row in rows if row["location_id"] == location),
            location,
        ),
    )
    for location in locations:
        by_month = {
            row["month_start"]: _number(row, value_field)
            for row in rows if row["location_id"] == location
        }
        figure.add_trace(
            go.Scatter(
                x=all_months,
                y=[by_month.get(month) for month in all_months],
                name=location.title(),
                mode="lines+markers",
                line={"color": COLORS.get(location), "width": 3},
                marker={"size": 8},
                connectgaps=False,
                hovertemplate="%{x|%b %Y}<br>%{y:.3f}<extra>"
                + location.title()
                + "</extra>",
            )
        )
    _style_figure(figure, y_title=y_title, x_values=all_months, zero_base=zero_base)
    return figure


def _style_figure(
    figure: go.Figure, *, y_title: str, x_values: list[str], zero_base: bool = False
) -> None:
    figure.update_layout(
        template="plotly_white",
        height=390,
        margin={"l": 72, "r": 28, "t": 24, "b": 58},
        font={"family": "Segoe UI, Arial, sans-serif", "size": 14, "color": "#24333f"},
        legend={"orientation": "h", "y": 1.12, "x": 0},
        hovermode="x unified",
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )
    figure.update_xaxes(
        title=None,
        tickmode="array",
        tickvals=x_values,
        ticktext=[datetime.fromisoformat(value).strftime("%b %Y") for value in x_values],
        showgrid=False,
    )
    figure.update_yaxes(
        title=y_title,
        rangemode="tozero" if zero_base else "normal",
        gridcolor="#dce3e8",
        zeroline=False,
    )


def _export_time(report_dir: Path, release_id: str) -> str:
    health_path = report_dir / "pipeline_health.json"
    if health_path.is_file():
        health = json.loads(health_path.read_text(encoding="utf-8"))
        published = health.get("latest_successful_published_release") or {}
        latest_attempt = health.get("latest_attempt") or {}
        if (
            published.get("release_id") == release_id
            and published.get("run_id") == latest_attempt.get("run_id")
        ):
            export_stages = [
                stage for stage in health.get("latest_attempt_stages", [])
                if stage.get("stage_name") == "export" and stage.get("status") == "completed"
            ]
            if export_stages and export_stages[-1].get("ended_at"):
                return str(export_stages[-1]["ended_at"])
    timestamp = max(
        (report_dir / EXCHANGE_CSV).stat().st_mtime,
        (report_dir / WEATHER_CSV).stat().st_mtime,
    )
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat(timespec="milliseconds")


def _document(
    *,
    release_id: str,
    export_time: str,
    coverage: dict[str, Any],
    exchange_observations: int,
    weather_observations: int,
    exchange_rows: list[dict[str, str]],
    weather_rows: list[dict[str, str]],
    charts: list[str],
) -> str:
    exchange_coverage = coverage["exchange"]
    location_coverage = coverage["weather_by_location"]
    location_lines = "".join(
        f"<li><strong>{html.escape(name)}</strong>: "
        f"{html.escape(values['start_date'])} to {html.escape(values['end_date'])} "
        f"({int(values['observation_count'])} days)</li>"
        for name, values in sorted(
            location_coverage.items(),
            key=lambda item: (item[1]["start_date"], item[0]),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kenya Economic Data Platform results</title>
  <style>
    :root {{ color-scheme: light; --ink:#17252f; --muted:#586976; --line:#dce3e8; --accent:#0f766e; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#f4f7f8; color:var(--ink); font-family:"Segoe UI",Arial,sans-serif; line-height:1.5; }}
    main {{ max-width:1120px; margin:0 auto; background:#fff; min-height:100vh; padding:52px 64px 72px; }}
    h1 {{ margin:0 0 10px; font-size:2.45rem; letter-spacing:-0.035em; }}
    h2 {{ margin:42px 0 8px; padding-top:22px; border-top:1px solid var(--line); font-size:1.55rem; }}
    h3 {{ margin:28px 0 4px; font-size:1.05rem; }}
    p {{ max-width:82ch; }}
    .eyebrow {{ color:var(--accent); font-weight:700; letter-spacing:.08em; text-transform:uppercase; font-size:.78rem; }}
    .lede {{ color:var(--muted); font-size:1.08rem; max-width:76ch; }}
    .facts {{ display:grid; grid-template-columns:repeat(3,1fr); gap:24px; margin:30px 0; padding:22px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }}
    .fact strong {{ display:block; font-size:1.8rem; }}
    .fact span, .meta, .note {{ color:var(--muted); }}
    .chart {{ margin:14px -12px 8px; }}
    ul {{ padding-left:20px; }}
    table {{ width:100%; border-collapse:collapse; margin:16px 0 28px; font-size:.9rem; }}
    th {{ text-align:left; color:#344955; background:#eef3f4; }}
    th, td {{ border-bottom:1px solid var(--line); padding:9px 10px; vertical-align:top; }}
    td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    code {{ overflow-wrap:anywhere; }}
    footer {{ margin-top:48px; padding-top:20px; border-top:1px solid var(--line); color:var(--muted); font-size:.86rem; }}
    @media (max-width:760px) {{ main {{ padding:32px 20px 48px; }} .facts {{ grid-template-columns:1fr; gap:12px; }} table {{ font-size:.8rem; }} }}
  </style>
</head>
<body><main>
  <div class="eyebrow">Verified historical reporting</div>
  <h1>Kenya Economic Data Platform results</h1>
  <p class="lede">Monthly exchange-rate and weather summaries from one trusted release. The domains remain separate and no economic index or causal relationship is implied.</p>
  <div class="facts">
    <div class="fact"><strong>{exchange_observations}</strong><span>exchange observations</span></div>
    <div class="fact"><strong>{weather_observations}</strong><span>weather observations</span></div>
    <div class="fact"><strong>{len(exchange_rows) + len(weather_rows)}</strong><span>monthly reporting rows</span></div>
  </div>
  <p class="meta"><strong>Release:</strong> <code>{html.escape(release_id)}</code><br>
  <strong>Trusted export completed:</strong> {html.escape(export_time)}<br>
  <strong>Sources:</strong> Central Bank of Kenya historical exchange rates and NASA POWER daily gridded estimates at representative points.</p>

  <h2>Historical coverage</h2>
  <p>Exchange rates cover {html.escape(exchange_coverage['start_date'])} to {html.escape(exchange_coverage['end_date'])} across {int(exchange_coverage['publication_dates'])} available publication days. Weather coverage differs by representative point:</p>
  <ul>{location_lines}</ul>
  <p class="note">Missing location-months remain missing. Mombasa and Kisumu begin in October; the charts do not replace September with zero or connect across absent periods.</p>

  <h2>Exchange rates</h2>
  <p>Each point is the arithmetic mean of available CBK published daily mean rates for the month. Values are labelled KES per 1 unit of foreign currency.</p>
  <div class="chart">{charts[0]}</div>
  {_exchange_table(exchange_rows)}

  <h2>Weather</h2>
  <p>NASA POWER values are gridded estimates at representative points, not station observations or measurements for an entire city.</p>
  <h3>Monthly mean temperature</h3>
  <div class="chart">{charts[1]}</div>
  <h3>Monthly precipitation totals</h3>
  <div class="chart">{charts[2]}</div>
  {_weather_table(weather_rows)}

  <footer>Generated locally from the trusted exchange and weather summary exports. Raw source files, candidate tables, fault-injected outputs and network resources are not used by this report.</footer>
</main></body></html>"""


def _exchange_table(rows: list[dict[str, str]]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{html.escape(row['month_start'])}</td>"
        f"<td>{html.escape(row['currency_code'])}</td>"
        f"<td class=\"num\">{_number(row, 'mean_published_daily_mean_rate_kes_per_foreign_unit'):.6f}</td>"
        f"<td>{html.escape(row['first_available_publication_date'])} to {html.escape(row['last_available_publication_date'])}</td>"
        f"<td class=\"num\">{_integer(row, 'publication_observation_count')}</td>"
        "</tr>"
        for row in sorted(rows, key=lambda item: (item["month_start"], item["currency_code"]))
    )
    return (
        "<table><thead><tr><th>Month</th><th>Currency</th>"
        "<th class=\"num\">Mean KES per 1 unit</th><th>Available dates</th>"
        "<th class=\"num\">Observations</th></tr></thead><tbody>"
        + body + "</tbody></table>"
    )


def _weather_table(rows: list[dict[str, str]]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{html.escape(row['month_start'])}</td>"
        f"<td>{html.escape(row['location_id'].title())}</td>"
        f"<td class=\"num\">{_number(row, 'mean_daily_temperature_c'):.3f}</td>"
        f"<td class=\"num\">{_number(row, 'sum_daily_precipitation_mm'):.2f}</td>"
        f"<td class=\"num\">{_integer(row, 'observed_day_count')} / {_integer(row, 'expected_day_count')}</td>"
        "</tr>"
        for row in sorted(rows, key=lambda item: (item["month_start"], item["location_id"]))
    )
    return (
        "<table><thead><tr><th>Month</th><th>Representative point</th>"
        "<th class=\"num\">Mean °C</th><th class=\"num\">Precipitation mm</th>"
        "<th class=\"num\">Observed / expected days</th></tr></thead><tbody>"
        + body + "</tbody></table>"
    )

