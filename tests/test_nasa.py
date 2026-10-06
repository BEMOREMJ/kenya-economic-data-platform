from datetime import date
from pathlib import Path

from kenya_economic_data.config import Location
from kenya_economic_data.nasa import process_nasa_location


def test_nasa_fill_value_becomes_missing_and_blocks_candidate() -> None:
    raw = (Path(__file__).parent / "fixtures" / "synthetic_nasa_fill.json").read_bytes()
    result = process_nasa_location(
        raw,
        location=Location("Nairobi", -1.2921, 36.8219),
        start_date=date(2023, 10, 1),
        end_date=date(2023, 10, 2),
        missing_value=-999.0,
        batch_id="synthetic_batch",
        snapshot_sha256="0" * 64,
    )

    assert result.blocked
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert result.reconciliation["missing_measurement_field_count"] == 1
    assert result.rejected[0]["raw_t2m"] == -999.0
    assert "missing_T2M" in result.rejected[0]["reason"]
    assert result.reconciliation["equation"]["passed"]

