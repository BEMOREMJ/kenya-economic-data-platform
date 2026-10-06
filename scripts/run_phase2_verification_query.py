"""Run the bounded Phase 2 verification query with an explicit byte cap."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from google.cloud import bigquery


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "elevated-legacy-457718-h2"
LOCATION = "US"
MAXIMUM_BYTES_BILLED = 1_073_741_824


def _json_value(value: object) -> object:
    if isinstance(value, (date, Decimal)):
        return str(value)
    return value


def main() -> None:
    sql = (ROOT / "queries" / "phase2_verification.sql").read_text(encoding="utf-8")
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    config = bigquery.QueryJobConfig(
        use_legacy_sql=False,
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
    )
    job = client.query(
        sql,
        job_id="kep_phase2_verification_v2",
        job_retry=None,
        location=LOCATION,
        job_config=config,
    )
    rows = [
        {key: _json_value(value) for key, value in dict(row.items()).items()}
        for row in job.result(timeout=120)
    ]
    print(json.dumps({
        "job_id": job.job_id,
        "maximum_bytes_billed": MAXIMUM_BYTES_BILLED,
        "total_bytes_processed": job.total_bytes_processed,
        "total_bytes_billed": job.total_bytes_billed,
        "rows": rows,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
