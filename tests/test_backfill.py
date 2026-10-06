from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from kenya_economic_data.backfill import compose_backfill
from kenya_economic_data.io_utils import sha256_file
from kenya_economic_data.manifest import Manifest, ReusableBatch


FIELDS = ["observation_date", "currency_code", "mean_rate", "batch_id"]


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows(rows)


def _record(manifest: Manifest, root: Path, batch_id: str, rows: list[list[str]]) -> None:
    accepted = root / batch_id / "accepted.csv"
    _write(accepted, rows)
    rejected = root / batch_id / "rejected.csv"
    reconciliation = root / batch_id / "reconciliation.json"
    status = root / batch_id / "status.json"
    rejected.write_text("reason\n", encoding="utf-8")
    reconciliation.write_text("{}\n", encoding="utf-8")
    status.write_text("{}\n", encoding="utf-8")
    manifest.ensure_scope("scope_test", "cbk", {"test": True})
    batch = ReusableBatch(
        batch_id=batch_id, source="cbk", scope_id="scope_test",
        content_sha256=batch_id.ljust(64, "0")[:64],
        observation_sha256=batch_id.ljust(64, "1")[:64], snapshot_refs=[],
        accepted_path=accepted, rejected_path=rejected,
        reconciliation_path=reconciliation, status_path=status,
        counts={"accepted_observation_count": len(rows)},
    )
    manifest.record_batch(batch, [
        ("accepted", accepted, sha256_file(accepted)),
        ("rejected", rejected, sha256_file(rejected)),
        ("reconciliation", reconciliation, sha256_file(reconciliation)),
        ("candidate_status", status, sha256_file(status)),
    ])


def test_scoped_backfill_preserves_outside_and_records_changes(tmp_path: Path) -> None:
    with Manifest(tmp_path / "manifest.sqlite3") as manifest:
        _record(manifest, tmp_path, "batch_baseline", [
            ["2023-10-01", "USD", "100", "batch_baseline"],
            ["2023-10-02", "USD", "101", "batch_baseline"],
            ["2023-10-02", "EUR", "150", "batch_baseline"],
            ["2023-10-03", "USD", "102", "batch_baseline"],
        ])
        _record(manifest, tmp_path, "batch_replacement", [
            ["2023-10-02", "USD", "111", "batch_replacement"],
            ["2023-10-04", "USD", "112", "batch_replacement"],
        ])
        result = compose_backfill(
            manifest, source="cbk", baseline_batch_id="batch_baseline",
            replacement_batch_id="batch_replacement",
            start_date=date(2023, 10, 2), end_date=date(2023, 10, 4),
            selections=("USD",), output_root=tmp_path / "compositions",
        )
    reconciliation = json.loads(result.reconciliation_path.read_text(encoding="utf-8"))
    output = list(csv.DictReader(result.output_path.open(encoding="utf-8")))

    assert result.counts == {
        "baseline": 4, "replacement_input": 2, "added": 1,
        "replaced": 1, "removed": 1, "unchanged": 2, "output": 4,
    }
    assert reconciliation["equation"]["passed"]
    assert {(row["observation_date"], row["currency_code"], row["mean_rate"]) for row in output} == {
        ("2023-10-01", "USD", "100"),
        ("2023-10-02", "USD", "111"),
        ("2023-10-02", "EUR", "150"),
        ("2023-10-04", "USD", "112"),
    }


def test_backfill_rejects_replacement_outside_declared_scope(tmp_path: Path) -> None:
    with Manifest(tmp_path / "manifest.sqlite3") as manifest:
        _record(manifest, tmp_path, "batch_baseline", [
            ["2023-10-01", "USD", "100", "batch_baseline"],
        ])
        _record(manifest, tmp_path, "batch_replacement", [
            ["2023-11-01", "USD", "101", "batch_replacement"],
        ])
        with pytest.raises(ValueError, match="outside declared scope"):
            compose_backfill(
                manifest, source="cbk", baseline_batch_id="batch_baseline",
                replacement_batch_id="batch_replacement",
                start_date=date(2023, 10, 1), end_date=date(2023, 10, 31),
                selections=("USD",), output_root=tmp_path / "compositions",
            )
