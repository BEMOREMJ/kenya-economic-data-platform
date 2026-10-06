"""Print sanitized structural facts about ignored Phase 0 source samples."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from kenya_economic_data.source_contracts import parse_cbk_date


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "raw" / "phase_0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_cbk(path: Path) -> None:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        raw_rows = list(csv.reader(stream))

    malformed_rows = [
        {"source_row_number": index, "field_count": len(row), "fields": row}
        for index, row in enumerate(raw_rows, start=1)
        if len(row) != 5
    ]
    rows = [
        (parse_cbk_date(row[0]), row[1], *map(float, row[2:]))
        for row in raw_rows
        if len(row) == 5
    ]
    keys = Counter((row[0], row[1]) for row in rows)
    window = [
        row
        for row in rows
        if date(2023, 10, 1) <= row[0] <= date(2023, 12, 31)
        and row[1] in {"US DOLLAR", "STG POUND", "EURO"}
    ]
    duplicate_rows = sum(count - 1 for count in keys.values() if count > 1)

    print("CBK")
    print(f"  source_records={len(raw_rows)}")
    print(f"  five_field_records={len(rows)}")
    print(f"  non_five_field_records={len(malformed_rows)}")
    for malformed in malformed_rows:
        print(
            "  malformed_record="
            f"row:{malformed['source_row_number']},"
            f"field_count:{malformed['field_count']},"
            f"fields:{malformed['fields']!r}"
        )
    print(f"  unique_date_currency_keys={len(keys)}")
    print(f"  duplicate_rows={duplicate_rows}")
    plausible_rows = [row for row in rows if row[0] <= date(2024, 1, 4)]
    future_rows = [row for row in rows if row[0] > date(2024, 1, 4)]
    print(
        "  usable_coverage="
        f"{min(row[0] for row in plausible_rows)}..{max(row[0] for row in plausible_rows)}"
    )
    print(f"  rejected_future_rows={len(future_rows)}")
    print(f"  currencies={len({row[1] for row in rows})}")
    print(f"  proposed_window_rows={len(window)}")
    print(f"  proposed_window_unique_rows={len({(row[0], row[1]) for row in window})}")
    for row in sorted(window)[:3]:
        print(f"  sample={row}")
    print(f"  sha256={sha256(path)}")


def inspect_nasa(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    header = payload["header"]
    parameters = payload["properties"]["parameter"]
    print("NASA POWER")
    print(f"  api_version={header['api']['version']}")
    print(f"  source={','.join(header['sources'])}")
    print(f"  time_standard={header['time_standard']}")
    print(f"  fill_value={header['fill_value']}")
    print(f"  coordinates={payload['geometry']['coordinates'][:2]}")
    for name, values in parameters.items():
        units = payload["parameters"][name]["units"]
        first_day = min(values)
        print(f"  sample={first_day},{name},{values[first_day]},{units}")
    print(f"  sha256={sha256(path)}")


if __name__ == "__main__":
    inspect_cbk(SAMPLE_DIR / "cbk_historical_retry.csv")
    inspect_nasa(SAMPLE_DIR / "nasa_nairobi_20240101_20240107.json")

