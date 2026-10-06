"""Deterministic effective-input composition for targeted backfills."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_json_once, atomic_write_once, identity, sha256_file
from .manifest import Manifest, ReusableBatch


@dataclass(frozen=True)
class CompositionResult:
    composition_id: str
    source: str
    output_path: Path
    reconciliation_path: Path
    output_sha256: str
    counts: dict[str, int]


def compose_backfill(
    manifest: Manifest,
    *,
    source: str,
    baseline_batch_id: str,
    replacement_batch_id: str,
    start_date: date,
    end_date: date,
    selections: tuple[str, ...],
    output_root: Path,
) -> CompositionResult:
    if start_date > end_date:
        raise ValueError("backfill start date must be on or before end date")
    if not selections or len(selections) != len(set(selections)):
        raise ValueError("backfill selections must be non-empty and unique")
    baseline = manifest.candidate(baseline_batch_id)
    replacement = manifest.candidate(replacement_batch_id)
    if baseline is None or replacement is None:
        raise RuntimeError("baseline and replacement must both be candidate-ready batches")
    if baseline.source != source or replacement.source != source:
        raise ValueError("backfill source must match both input batches")
    for batch in (baseline, replacement):
        valid, failures = manifest.verify_batch(batch.batch_id)
        if not valid:
            raise RuntimeError(
                f"candidate artifact verification failed for {batch.batch_id}: "
                + "; ".join(failures)
            )

    baseline_rows, fields = _read_csv(baseline.accepted_path)
    replacement_rows, replacement_fields = _read_csv(replacement.accepted_path)
    if fields != replacement_fields:
        raise ValueError("baseline and replacement schemas differ")
    date_field, selection_field = _scope_fields(source)
    key_fields = (date_field, selection_field)
    baseline_by_key = _unique_rows(baseline_rows, key_fields, "baseline")
    replacement_by_key = _unique_rows(replacement_rows, key_fields, "replacement")

    def in_scope(row: dict[str, str]) -> bool:
        day = date.fromisoformat(row[date_field])
        return start_date <= day <= end_date and row[selection_field] in selections

    outside_replacement = sorted(key for key, row in replacement_by_key.items() if not in_scope(row))
    if outside_replacement:
        raise ValueError(
            "replacement contains observations outside declared scope: "
            + ", ".join("/".join(key) for key in outside_replacement[:5])
        )
    baseline_scope = {key: row for key, row in baseline_by_key.items() if in_scope(row)}
    baseline_outside = {key: row for key, row in baseline_by_key.items() if not in_scope(row)}

    baseline_keys = set(baseline_scope)
    replacement_keys = set(replacement_by_key)
    added = replacement_keys - baseline_keys
    removed = baseline_keys - replacement_keys
    common = baseline_keys & replacement_keys
    replaced = {
        key for key in common
        if _without_batch(baseline_scope[key]) != _without_batch(replacement_by_key[key])
    }
    equal_overlap = common - replaced
    scope = {
        "source": source,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "selections": sorted(selections),
        "precedence": "replacement batch is authoritative only inside the declared scope",
    }
    composition_id = identity(
        "composition",
        {
            "baseline_batch_id": baseline_batch_id,
            "replacement_batch_id": replacement_batch_id,
            "scope": scope,
            "baseline_sha256": sha256_file(baseline.accepted_path),
            "replacement_sha256": sha256_file(replacement.accepted_path),
        },
    )
    composed_by_key = {**baseline_outside, **replacement_by_key}
    composed: list[dict[str, str]] = []
    for key in sorted(composed_by_key):
        row = dict(composed_by_key[key])
        row["batch_id"] = composition_id
        composed.append(row)
    output_dir = output_root / composition_id
    output_path = output_dir / "accepted.csv"
    rejected_path = output_dir / "rejected.csv"
    reconciliation_path = output_dir / "reconciliation.json"
    status_path = output_dir / "candidate_status.json"
    atomic_write_once(output_path, _csv_bytes(composed, fields))
    atomic_write_once(rejected_path, b"reason\n")
    counts = {
        "baseline": len(baseline_rows),
        "replacement_input": len(replacement_rows),
        "added": len(added),
        "replaced": len(replaced),
        "removed": len(removed),
        "unchanged": len(baseline_outside) + len(equal_overlap),
        "output": len(composed),
    }
    reconciliation = {
        "composition_id": composition_id,
        "scope": scope,
        "baseline_batch_id": baseline_batch_id,
        "replacement_batch_id": replacement_batch_id,
        "counts": counts,
        "equation": {
            "formula": "output = unchanged + equal_overlap_excluded_from_replaced + replaced + added",
            "passed": len(composed) == counts["unchanged"] + counts["replaced"] + counts["added"],
        },
        "removed_keys": [list(key) for key in sorted(removed)],
        "added_keys": [list(key) for key in sorted(added)],
        "replaced_keys": [list(key) for key in sorted(replaced)],
        "warehouse_operation": "full reconstruction from explicit effective inputs; not incremental DML",
    }
    atomic_write_json_once(reconciliation_path, reconciliation)
    output_sha256 = sha256_file(output_path)
    atomic_write_json_once(status_path, {
        "candidate_ready": True,
        "source": source,
        "scope_id": identity("scope", scope),
        "batch_id": composition_id,
        "content_sha256": output_sha256,
        "observation_sha256": output_sha256,
        "counts": {"accepted_observation_count": len(composed), "rejected_artifact_row_count": 0},
        "composition": True,
    })
    scope_id = identity("scope", scope)
    manifest.ensure_scope(scope_id, source, scope)
    manifest.record_batch(
        ReusableBatch(
            batch_id=composition_id, source=source, scope_id=scope_id,
            content_sha256=output_sha256, observation_sha256=output_sha256,
            snapshot_refs=[
                {"kind": "composition_input", "role": "baseline", "batch_id": baseline_batch_id,
                 "path": str(baseline.accepted_path), "sha256": sha256_file(baseline.accepted_path)},
                {"kind": "composition_input", "role": "replacement", "batch_id": replacement_batch_id,
                 "path": str(replacement.accepted_path), "sha256": sha256_file(replacement.accepted_path)},
            ],
            accepted_path=output_path, rejected_path=rejected_path,
            reconciliation_path=reconciliation_path, status_path=status_path,
            counts={"accepted_observation_count": len(composed), "rejected_artifact_row_count": 0},
        ),
        [
            ("accepted", output_path, output_sha256),
            ("rejected", rejected_path, sha256_file(rejected_path)),
            ("reconciliation", reconciliation_path, sha256_file(reconciliation_path)),
            ("candidate_status", status_path, sha256_file(status_path)),
            ("baseline_input", baseline.accepted_path, sha256_file(baseline.accepted_path)),
            ("replacement_input", replacement.accepted_path, sha256_file(replacement.accepted_path)),
        ],
    )
    manifest.record_backfill_composition(
        composition_id=composition_id,
        source=source,
        baseline_batch_id=baseline_batch_id,
        replacement_batch_id=replacement_batch_id,
        scope=scope,
        output_path=output_path,
        output_sha256=output_sha256,
        counts=counts,
    )
    return CompositionResult(
        composition_id, source, output_path, reconciliation_path, output_sha256, counts
    )


def _scope_fields(source: str) -> tuple[str, str]:
    if source == "cbk":
        return "observation_date", "currency_code"
    if source == "nasa_power":
        return "observation_date", "location_name"
    raise ValueError(f"unsupported backfill source: {source}")


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader), list(reader.fieldnames)


def _unique_rows(
    rows: list[dict[str, str]], key_fields: tuple[str, str], label: str
) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key in result:
            raise ValueError(f"{label} contains duplicate business key: {'/'.join(key)}")
        result[key] = row
    return result


def _without_batch(row: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in row.items() if key != "batch_id"}


def _csv_bytes(rows: list[dict[str, str]], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")
