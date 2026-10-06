from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from kenya_economic_data.public_dashboard import (
    generate_public_weather_dashboard,
    load_trusted_weather_export,
)


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
    exchange = [{
        "release_id": "release_test", "source_batch_id": "batch_fx",
        "domain": "exchange", "month_start": "2023-10-01",
        "currency_code": "USD",
        "mean_published_daily_mean_rate_kes_per_foreign_unit": "149.25",
        "publication_observation_count": "20",
    }]
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
    for filename, rows in (
        ("exchange_summary.csv", exchange),
        ("weather_summary.csv", weather),
    ):
        with (report_dir / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    weather_coverage = {
        "Nairobi": {
            "start_date": "2023-09-01", "end_date": "2023-09-30",
            "observation_count": 30,
        },
        "Mombasa": {
            "start_date": "2023-10-01", "end_date": "2023-10-31",
            "observation_count": 31,
        },
    }
    (report_dir / "weather_summary.metadata.json").write_text(
        json.dumps({
            "release_id": weather_release, "domain": "weather",
            "coverage": {"weather_by_location": weather_coverage},
        }),
        encoding="utf-8",
    )
    (report_dir / "exchange_summary.metadata.json").write_text(
        json.dumps({"release_id": "release_test", "domain": "exchange"}),
        encoding="utf-8",
    )
    return report_dir


def test_public_dashboard_is_weather_only_and_offline(tmp_path: Path) -> None:
    report_dir = _write_exports(tmp_path)
    (report_dir / "exchange_summary.csv").unlink()
    (report_dir / "exchange_summary.metadata.json").unlink()
    output = tmp_path / "site" / "index.html"

    result = generate_public_weather_dashboard(report_dir, output_path=output)

    text = output.read_text(encoding="utf-8")
    assert result["release_id"] == "release_test"
    assert result["weather_observations"] == 61
    assert result["weather_monthly_rows"] == 2
    assert "Historical reporting snapshot" in text
    assert "NASA Earthdata data-use policy" in text
    assert "21.658000" in text
    assert "116.270000" in text
    assert '"name":"Mombasa"' in text
    assert '"y":[null,25.9]' in text
    assert '"connectgaps":false' in text
    assert "<script src=" not in text.lower()
    assert "<link rel=" not in text.lower()
    for forbidden in (
        "CBK",
        "149.25",
        "batch_fx",
        "exchange_summary.csv",
        "currency_code",
        "mean_published_daily_mean_rate_kes_per_foreign_unit",
    ):
        assert forbidden not in text


def test_public_dashboard_refuses_mismatched_directory_release(tmp_path: Path) -> None:
    report_dir = _write_exports(tmp_path, weather_release="release_other")

    with pytest.raises(RuntimeError, match="directory identity .* does not match"):
        load_trusted_weather_export(report_dir)


def test_public_dashboard_is_deterministic(tmp_path: Path) -> None:
    report_dir = _write_exports(tmp_path)
    output = tmp_path / "site" / "index.html"

    first = generate_public_weather_dashboard(report_dir, output_path=output)
    second = generate_public_weather_dashboard(report_dir, output_path=output)

    assert second["sha256"] == first["sha256"]
