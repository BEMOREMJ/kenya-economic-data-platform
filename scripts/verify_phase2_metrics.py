"""Independent local reference calculations for two Phase 2 monthly rows."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from kenya_economic_data.manifest import Manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "ingestion.sqlite3"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    with Manifest(MANIFEST) as manifest:
        cbk_batch = manifest.latest_candidate_for_source("cbk")
        weather_batch = manifest.latest_candidate_for_source("nasa_power")
    if cbk_batch is None or weather_batch is None:
        raise RuntimeError("both Phase 2 candidate batches are required")

    cbk = [
        row for row in _rows(cbk_batch.accepted_path)
        if row["currency_code"] == "USD" and row["observation_date"].startswith("2023-10-")
    ]
    weather = [
        row for row in _rows(weather_batch.accepted_path)
        if row["location_name"] == "Nairobi" and row["observation_date"].startswith("2023-10-")
    ]
    cbk_values = [Decimal(row["mean_rate"]) for row in cbk]
    temperatures = [Decimal(row["t2m_c"]) for row in weather]
    precipitation = [Decimal(row["prectotcorr_mm_day"]) for row in weather]
    result = {
        "method": "Python csv.DictReader plus decimal.Decimal; independent of dbt SQL",
        "tolerances": {
            "decimal_rate_absolute": "0.000000001",
            "weather_float_absolute": "0.000001",
            "counts_and_dates": "exact",
        },
        "exchange": {
            "selection": "USD / 2023-10",
            "batch_id": cbk_batch.batch_id,
            "count": len(cbk),
            "mean_rate": str(sum(cbk_values) / Decimal(len(cbk_values))),
            "first_date": min(row["observation_date"] for row in cbk),
            "last_date": max(row["observation_date"] for row in cbk),
        },
        "weather": {
            "selection": "Nairobi / 2023-10",
            "batch_id": weather_batch.batch_id,
            "observed_day_count": len(weather),
            "expected_day_count": 31,
            "mean_temperature_c": str(sum(temperatures) / Decimal(len(temperatures))),
            "sum_precipitation_mm": str(sum(precipitation)),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
