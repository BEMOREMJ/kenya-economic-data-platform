"""Immutable BigQuery local-file batch loading with manifest recovery."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from .io_utils import canonical_json, identity, sha256_bytes, sha256_file
from .manifest import Manifest, ReusableBatch, WarehouseLoad, utc_now
from .pipeline import sanitize_error


@dataclass(frozen=True)
class RemoteTable:
    row_count: int
    num_bytes: int | None
    schema_sha256: str
    labels: dict[str, str]


@dataclass(frozen=True)
class LoadJobResult:
    job_id: str
    output_rows: int | None
    input_file_bytes: int | None
    output_bytes: int | None


class WarehouseGateway(Protocol):
    def dataset_metadata(self, project_id: str, dataset_id: str) -> dict[str, Any]: ...
    def table_metadata(self, table_ref: str) -> RemoteTable | None: ...
    def load_csv(
        self, *, table_ref: str, path: Path, schema: list[dict[str, str]],
        job_id: str, labels: dict[str, str], description: str,
    ) -> LoadJobResult: ...


class BigQueryGateway:
    def __init__(self, project_id: str, location: str) -> None:
        self.project_id = project_id
        self.location = location
        self.client = bigquery.Client(project=project_id, location=location)

    def dataset_metadata(self, project_id: str, dataset_id: str) -> dict[str, Any]:
        dataset = self.client.get_dataset(f"{project_id}.{dataset_id}")
        return {
            "location": dataset.location,
            "labels": dataset.labels or {},
            "default_table_expiration_ms": dataset.default_table_expiration_ms,
        }

    def table_metadata(self, table_ref: str) -> RemoteTable | None:
        try:
            table = self.client.get_table(table_ref)
        except NotFound:
            return None
        schema = [
            {"name": field.name, "type": field.field_type, "mode": field.mode}
            for field in table.schema
        ]
        return RemoteTable(
            row_count=int(table.num_rows),
            num_bytes=int(table.num_bytes) if table.num_bytes is not None else None,
            schema_sha256=_schema_sha256(schema),
            labels=table.labels or {},
        )

    def load_csv(
        self, *, table_ref: str, path: Path, schema: list[dict[str, str]],
        job_id: str, labels: dict[str, str], description: str,
    ) -> LoadJobResult:
        config = bigquery.LoadJobConfig(
            schema=[
                bigquery.SchemaField(item["name"], item["type"], mode=item.get("mode", "NULLABLE"))
                for item in schema
            ],
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            write_disposition=bigquery.WriteDisposition.WRITE_EMPTY,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            labels=labels,
        )
        with path.open("rb") as stream:
            job = self.client.load_table_from_file(
                stream, table_ref, job_id=job_id, location=self.location, job_config=config,
            )
            job.result(timeout=120)
        table = self.client.get_table(table_ref)
        table.description = description
        table.labels = labels
        self.client.update_table(table, ["description", "labels"])
        properties = job._properties.get("statistics", {}).get("load", {})
        return LoadJobResult(
            job_id=job.job_id,
            output_rows=int(job.output_rows) if job.output_rows is not None else None,
            input_file_bytes=_optional_int(properties.get("inputFileBytes")),
            output_bytes=_optional_int(properties.get("outputBytes")),
        )


def load_candidate_batch(
    manifest: Manifest,
    gateway: WarehouseGateway,
    *,
    source: str,
    project_id: str,
    dataset_id: str,
    location: str,
    schema_path: Path,
    batch_id: str | None = None,
) -> dict[str, Any]:
    batch = manifest.candidate(batch_id) if batch_id else manifest.latest_candidate_for_source(source)
    if batch is None:
        selector = batch_id or f"latest {source}"
        raise RuntimeError(f"no candidate-ready batch found for {selector}")
    if batch.source != source:
        raise ValueError(f"batch {batch.batch_id} belongs to {batch.source}, not {source}")
    verified, failures = manifest.verify_batch(batch.batch_id)
    if not verified:
        raise RuntimeError("candidate artifact verification failed: " + "; ".join(failures))

    dataset = gateway.dataset_metadata(project_id, dataset_id)
    if str(dataset.get("location", "")).upper() != location.upper():
        raise RuntimeError(f"dataset location mismatch: expected {location}, got {dataset.get('location')}")
    labels = dataset.get("labels", {})
    if labels.get("kep_owner") != "kenya_economic_data_platform":
        raise RuntimeError(f"dataset ownership label missing or different: {dataset_id}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_sha256 = _schema_sha256(schema)
    artifact_sha256 = sha256_file(batch.accepted_path)
    local_row_count = _csv_row_count(batch.accepted_path)
    expected_count = int(batch.counts["accepted_observation_count"])
    if local_row_count != expected_count:
        raise RuntimeError(
            f"accepted artifact row mismatch: manifest={expected_count}, file={local_row_count}"
        )

    source_slug = "cbk" if source == "cbk" else "nasa_power"
    table_id = f"landing_{source_slug}__{batch.batch_id}"
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    dataset_token = sha256_bytes(dataset_id.encode("utf-8"))[:8]
    job_id = (
        f"kep_load_{source_slug}_{batch.batch_id.removeprefix('batch_')}_"
        f"{dataset_token}_{schema_sha256[:8]}"
    )
    load_id = identity(
        "load",
        {
            "batch_id": batch.batch_id,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "table_id": table_id,
            "artifact_sha256": artifact_sha256,
            "schema_sha256": schema_sha256,
        },
    )
    attempt_id = manifest.start_load_attempt(
        batch_id=batch.batch_id, project_id=project_id, dataset_id=dataset_id,
        table_id=table_id, job_id=job_id, local_row_count=local_row_count,
        artifact_sha256=artifact_sha256, schema_sha256=schema_sha256,
    )
    table_labels = {
        "kep_owner": "kenya_economic_data_platform",
        "kep_phase": "phase2_candidate",
        "kep_batch": batch.batch_id,
        "kep_artifact": artifact_sha256[:32],
        "kep_schema": schema_sha256[:32],
    }
    description = canonical_json(
        {
            "kind": "landing records derived from preserved source bytes",
            "source": source,
            "scope_id": batch.scope_id,
            "batch_id": batch.batch_id,
            "artifact_sha256": artifact_sha256,
            "schema_sha256": schema_sha256,
            "observation_sha256": batch.observation_sha256,
        }
    )
    try:
        remote = gateway.table_metadata(table_ref)
        outcome = "reused"
        job_stats: LoadJobResult | None = None
        if remote is None:
            outcome = "loaded"
            job_stats = gateway.load_csv(
                table_ref=table_ref, path=batch.accepted_path, schema=schema,
                job_id=job_id, labels=table_labels, description=description,
            )
            remote = gateway.table_metadata(table_ref)
        if remote is None:
            raise RuntimeError(f"load completed without a readable destination table: {table_ref}")
        differences = _table_differences(
            remote, row_count=local_row_count, schema_sha256=schema_sha256,
            labels=table_labels,
        )
        if differences:
            raise RuntimeError("existing destination verification failed: " + "; ".join(differences))
        load = WarehouseLoad(
            load_id=load_id, batch_id=batch.batch_id, project_id=project_id,
            dataset_id=dataset_id, table_id=table_id, job_id=job_id,
            artifact_sha256=artifact_sha256, schema_sha256=schema_sha256,
            local_row_count=local_row_count, warehouse_row_count=remote.row_count,
            table_bytes=remote.num_bytes, completed_at=utc_now(),
        )
        manifest.record_warehouse_load(load)
        details = {
            "outcome": outcome,
            "input_file_bytes": job_stats.input_file_bytes if job_stats else None,
            "output_bytes": job_stats.output_bytes if job_stats else remote.num_bytes,
        }
        manifest.finish_load_attempt(
            attempt_id, status=outcome, warehouse_row_count=remote.row_count,
            table_bytes=remote.num_bytes, details=details,
        )
        return {
            "source": source, "scope_id": batch.scope_id, "batch_id": batch.batch_id,
            "load_id": load_id, "load_attempt_id": attempt_id, "outcome": outcome,
            "project_id": project_id, "location": location, "dataset_id": dataset_id,
            "table_id": table_id, "job_id": job_id, "local_row_count": local_row_count,
            "warehouse_row_count": remote.row_count, "artifact_sha256": artifact_sha256,
            "schema_sha256": schema_sha256, "table_bytes": remote.num_bytes,
            **details,
        }
    except Exception as exc:
        manifest.finish_load_attempt(attempt_id, status="failed", error=sanitize_error(exc))
        raise


def _schema_sha256(schema: list[dict[str, str]]) -> str:
    normalized = [
        {
            "name": item["name"],
            "type": item["type"].upper(),
            "mode": item.get("mode", "NULLABLE").upper(),
        }
        for item in schema
    ]
    return sha256_bytes(canonical_json(normalized).encode("utf-8"))


def _csv_row_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def _table_differences(
    table: RemoteTable,
    *,
    row_count: int,
    schema_sha256: str,
    labels: dict[str, str],
) -> list[str]:
    differences: list[str] = []
    if table.row_count != row_count:
        differences.append(f"row_count expected {row_count}, got {table.row_count}")
    if table.schema_sha256 != schema_sha256:
        differences.append("schema fingerprint mismatch")
    for key, expected in labels.items():
        if table.labels.get(key) != expected:
            differences.append(f"label {key} mismatch")
    return differences


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
