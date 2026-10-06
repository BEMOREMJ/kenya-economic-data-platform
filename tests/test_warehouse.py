from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from kenya_economic_data.io_utils import sha256_file
from kenya_economic_data.manifest import Manifest
from kenya_economic_data.pipeline import extract_cbk
from kenya_economic_data.warehouse import (
    LoadJobResult,
    RemoteTable,
    _schema_sha256,
    load_candidate_batch,
)

from .test_manifest_and_rerun import _settings


FIXTURES = Path(__file__).parent / "fixtures"


class FakeWarehouse:
    def __init__(self) -> None:
        self.tables: dict[str, RemoteTable] = {}
        self.load_calls = 0

    def dataset_metadata(self, project_id: str, dataset_id: str) -> dict[str, object]:
        return {
            "location": "US",
            "labels": {"kep_owner": "kenya_economic_data_platform"},
            "default_table_expiration_ms": 5_184_000_000,
        }

    def table_metadata(self, table_ref: str) -> RemoteTable | None:
        return self.tables.get(table_ref)

    def load_csv(
        self, *, table_ref: str, path: Path, schema: list[dict[str, str]],
        job_id: str, labels: dict[str, str], description: str,
    ) -> LoadJobResult:
        self.load_calls += 1
        row_count = sum(1 for _ in path.open(encoding="utf-8")) - 1
        self.tables[table_ref] = RemoteTable(
            row_count=row_count,
            num_bytes=path.stat().st_size,
            schema_sha256=_schema_sha256(schema),
            labels=labels,
        )
        return LoadJobResult(job_id, row_count, path.stat().st_size, path.stat().st_size)


def _schema(path: Path) -> None:
    path.write_text(
        json.dumps([
            {"name": "observation_date", "type": "DATE", "mode": "REQUIRED"},
            {"name": "currency_code", "type": "STRING", "mode": "REQUIRED"},
            {"name": "source_currency_label", "type": "STRING", "mode": "REQUIRED"},
            {"name": "rate_type", "type": "STRING", "mode": "REQUIRED"},
            {"name": "base_currency", "type": "STRING", "mode": "REQUIRED"},
            {"name": "quote_currency", "type": "STRING", "mode": "REQUIRED"},
            {"name": "unit_multiplier", "type": "INTEGER", "mode": "REQUIRED"},
            {"name": "mean_rate", "type": "NUMERIC", "mode": "REQUIRED"},
            {"name": "buy_rate", "type": "NUMERIC", "mode": "REQUIRED"},
            {"name": "sell_rate", "type": "NUMERIC", "mode": "REQUIRED"},
            {"name": "source", "type": "STRING", "mode": "REQUIRED"},
            {"name": "batch_id", "type": "STRING", "mode": "REQUIRED"},
            {"name": "source_snapshot_sha256", "type": "STRING", "mode": "REQUIRED"},
        ]),
        encoding="utf-8",
    )


def test_load_reuses_verified_existing_batch_table(tmp_path: Path) -> None:
    raw_path = FIXTURES / "synthetic_cbk_duplicates.csv"
    settings = _settings(tmp_path, raw_path)
    schema_path = tmp_path / "schema.json"
    _schema(schema_path)
    gateway = FakeWarehouse()
    with Manifest(tmp_path / "manifest.sqlite3") as manifest:
        candidate = extract_cbk(
            settings, manifest, start_date=date(2023, 10, 1),
            end_date=date(2023, 12, 31), refresh=False,
        )
        first = load_candidate_batch(
            manifest, gateway, source="cbk", project_id="example-project",
            dataset_id="kep_candidate_v1", location="US", schema_path=schema_path,
        )
        second = load_candidate_batch(
            manifest, gateway, source="cbk", project_id="example-project",
            dataset_id="kep_candidate_v1", location="US", schema_path=schema_path,
        )

    assert candidate["batch_id"] == first["batch_id"]
    assert first["outcome"] == "loaded"
    assert second["outcome"] == "reused"
    assert first["load_id"] == second["load_id"]
    assert gateway.load_calls == 1


def test_existing_table_mismatch_fails_and_is_not_completed(tmp_path: Path) -> None:
    raw_path = FIXTURES / "synthetic_cbk_duplicates.csv"
    settings = _settings(tmp_path, raw_path)
    schema_path = tmp_path / "schema.json"
    _schema(schema_path)
    gateway = FakeWarehouse()
    with Manifest(tmp_path / "manifest.sqlite3") as manifest:
        candidate = extract_cbk(
            settings, manifest, start_date=date(2023, 10, 1),
            end_date=date(2023, 12, 31), refresh=False,
        )
        table_ref = (
            "example-project.kep_candidate_v1."
            f"landing_cbk__{candidate['batch_id']}"
        )
        gateway.tables[table_ref] = RemoteTable(999, 1, "wrong", {})
        with pytest.raises(RuntimeError, match="destination verification failed"):
            load_candidate_batch(
                manifest, gateway, source="cbk", project_id="example-project",
                dataset_id="kep_candidate_v1", location="US", schema_path=schema_path,
            )
        row = manifest.connection.execute(
            "SELECT status FROM load_attempts ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        completed = manifest.connection.execute("SELECT count(*) FROM warehouse_loads").fetchone()[0]

    assert row["status"] == "failed"
    assert completed == 0
