from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kenya_economic_data.dashboard import generate_results_dashboard, load_trusted_exports
from kenya_economic_data import orchestration


FIELDS = [
    "release_id", "source_batch_id", "domain", "month_start", "currency_code",
    "location_id", "mean_published_daily_mean_rate_kes_per_foreign_unit",
    "first_available_publication_date", "last_available_publication_date",
    "publication_observation_count", "mean_daily_temperature_c",
    "sum_daily_precipitation_mm", "observed_day_count", "expected_day_count",
    "metric_definition",
]


def _write_exports(root: Path, *, weather_release: str = "release_test") -> Path:
    report_dir = root / "release_test"
    report_dir.mkdir()
    exchange = [
        {
            "release_id": "release_test", "source_batch_id": "batch_fx",
            "domain": "exchange", "month_start": "2023-10-01",
            "currency_code": "USD",
            "mean_published_daily_mean_rate_kes_per_foreign_unit": "149.25",
            "first_available_publication_date": "2023-10-02",
            "last_available_publication_date": "2023-10-31",
            "publication_observation_count": "20",
        }
    ]
    weather = [
        {
            "release_id": weather_release, "source_batch_id": "batch_weather",
            "domain": "weather", "month_start": "2023-09-01",
            "location_id": "nairobi", "mean_daily_temperature_c": "21.658",
            "sum_daily_precipitation_mm": "14.77", "observed_day_count": "30",
            "expected_day_count": "30",
        },
        {
            "release_id": weather_release, "source_batch_id": "batch_weather",
            "domain": "weather", "month_start": "2023-10-01",
            "location_id": "mombasa", "mean_daily_temperature_c": "25.9",
            "sum_daily_precipitation_mm": "116.27", "observed_day_count": "31",
            "expected_day_count": "31",
        },
    ]
    _write_csv(report_dir / "exchange_summary.csv", exchange)
    _write_csv(report_dir / "weather_summary.csv", weather)
    coverage = {
        "start_date": "2023-09-01", "end_date": "2023-10-31",
        "exchange": {
            "start_date": "2023-10-02", "end_date": "2023-10-31",
            "publication_dates": 20,
        },
        "weather_by_location": {
            "Nairobi": {
                "start_date": "2023-09-01", "end_date": "2023-09-30",
                "observation_count": 30,
            },
            "Mombasa": {
                "start_date": "2023-10-01", "end_date": "2023-10-31",
                "observation_count": 31,
            },
        },
    }
    (report_dir / "exchange_summary.metadata.json").write_text(
        json.dumps({"release_id": "release_test", "domain": "exchange", "coverage": coverage}),
        encoding="utf-8",
    )
    (report_dir / "weather_summary.metadata.json").write_text(
        json.dumps({"release_id": weather_release, "domain": "weather", "coverage": coverage}),
        encoding="utf-8",
    )
    return report_dir


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _complete_row(**values: str) -> dict[str, str]:
    return {field: values.get(field, "") for field in FIELDS}


def test_dashboard_is_standalone_and_uses_export_counts(tmp_path: Path) -> None:
    report_dir = _write_exports(tmp_path)

    result = generate_results_dashboard(report_dir)

    dashboard = Path(result["path"])
    text = dashboard.read_text(encoding="utf-8")
    assert result["release_id"] == "release_test"
    assert result["exchange_observations"] == 20
    assert result["weather_observations"] == 61
    assert "KES per 1 unit of foreign currency" in text
    assert "NASA POWER values are gridded estimates" in text
    assert "20</strong><span>exchange observations" in text
    assert "61</strong><span>weather observations" in text
    assert "plotly.js" in text.lower()
    assert "<script src=" not in text.lower()
    assert "<link rel=" not in text.lower()
    repeated = generate_results_dashboard(report_dir)
    assert repeated["sha256"] == result["sha256"]


def test_missing_weather_month_is_null_not_zero(tmp_path: Path) -> None:
    report_dir = _write_exports(tmp_path)
    generate_results_dashboard(report_dir)

    text = (report_dir / "results_dashboard.html").read_text(encoding="utf-8")

    assert '"name":"Mombasa"' in text
    assert '"y":[null,25.9]' in text
    assert '"connectgaps":false' in text


def test_mismatched_release_id_is_refused(tmp_path: Path) -> None:
    report_dir = _write_exports(tmp_path, weather_release="release_other")

    with pytest.raises(RuntimeError, match="mismatched release identities"):
        load_trusted_exports(report_dir)


def test_missing_release_id_is_refused(tmp_path: Path) -> None:
    report_dir = _write_exports(tmp_path, weather_release="")

    with pytest.raises(RuntimeError, match="missing release identity"):
        load_trusted_exports(report_dir)


def test_trusted_export_path_also_generates_dashboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_id = "release_test"
    exchange = _complete_row(
        release_id=release_id, source_batch_id="batch_fx", domain="exchange",
        month_start="2023-10-01", currency_code="USD",
        mean_published_daily_mean_rate_kes_per_foreign_unit="149.25",
        first_available_publication_date="2023-10-02",
        last_available_publication_date="2023-10-31",
        publication_observation_count="20",
    )
    weather = _complete_row(
        release_id=release_id, source_batch_id="batch_weather", domain="weather",
        month_start="2023-10-01", location_id="nairobi",
        mean_daily_temperature_c="21.7", sum_daily_precipitation_mm="45.84",
        observed_day_count="31", expected_day_count="31",
    )
    monkeypatch.setattr(
        orchestration,
        "reporting_rows",
        lambda *_args, **_kwargs: {
            "exchange": SimpleNamespace(
                rows=[exchange], job_id="exchange_job", bytes_processed=1,
                bytes_billed=10,
            ),
            "weather": SimpleNamespace(
                rows=[weather], job_id="weather_job", bytes_processed=1,
                bytes_billed=10,
            ),
        },
    )
    gateway = SimpleNamespace(current_release_id=lambda _dataset: release_id)
    manifest = Mock()
    coverage = {
        "start_date": "2023-10-01", "end_date": "2023-10-31",
        "exchange": {
            "start_date": "2023-10-02", "end_date": "2023-10-31",
            "publication_dates": 20,
        },
        "weather_by_location": {
            "Nairobi": {
                "start_date": "2023-10-01", "end_date": "2023-10-31",
                "observation_count": 31,
            }
        },
    }

    result = orchestration.export_release_reports(
        manifest, gateway, trusted_dataset="kep_trusted_v1",
        release_id=release_id, output_root=tmp_path, coverage=coverage,
    )

    assert result["dashboard"]["release_id"] == release_id
    assert (tmp_path / release_id / "results_dashboard.html").is_file()
    assert any(call.args[1] == "dashboard" for call in manifest.record_export.call_args_list)

