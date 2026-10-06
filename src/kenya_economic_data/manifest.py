"""SQLite ingestion manifest separating scopes, batches, and attempts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io_utils import canonical_json, sha256_file


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class ReusableBatch:
    batch_id: str
    source: str
    scope_id: str
    content_sha256: str
    observation_sha256: str
    snapshot_refs: list[dict[str, Any]]
    accepted_path: Path
    rejected_path: Path
    reconciliation_path: Path
    status_path: Path
    counts: dict[str, Any]


@dataclass(frozen=True)
class WarehouseLoad:
    load_id: str
    batch_id: str
    project_id: str
    dataset_id: str
    table_id: str
    job_id: str
    artifact_sha256: str
    schema_sha256: str
    local_row_count: int
    warehouse_row_count: int
    table_bytes: int | None
    completed_at: str


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Manifest":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scopes (
                scope_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY,
                scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
                source TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                observation_sha256 TEXT NOT NULL,
                snapshot_refs_json TEXT NOT NULL,
                status TEXT NOT NULL,
                counts_json TEXT NOT NULL,
                accepted_path TEXT NOT NULL,
                rejected_path TEXT NOT NULL,
                reconciliation_path TEXT NOT NULL,
                status_path TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                UNIQUE(scope_id, content_sha256)
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                PRIMARY KEY(batch_id, kind, path)
            );
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY,
                scope_id TEXT NOT NULL REFERENCES scopes(scope_id),
                batch_id TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds REAL,
                error TEXT,
                details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS load_attempts (
                load_attempt_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                project_id TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                table_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                local_row_count INTEGER NOT NULL,
                warehouse_row_count INTEGER,
                artifact_sha256 TEXT NOT NULL,
                schema_sha256 TEXT NOT NULL,
                table_bytes INTEGER,
                error TEXT,
                details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS warehouse_loads (
                load_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                project_id TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                table_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                schema_sha256 TEXT NOT NULL,
                local_row_count INTEGER NOT NULL,
                warehouse_row_count INTEGER NOT NULL,
                table_bytes INTEGER,
                completed_at TEXT NOT NULL,
                UNIQUE(project_id, dataset_id, table_id),
                UNIQUE(batch_id, project_id, dataset_id)
            );
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                selected_batches_json TEXT NOT NULL,
                model_fingerprint TEXT NOT NULL,
                config_fingerprint TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS run_stages (
                run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id),
                stage_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                error TEXT,
                PRIMARY KEY(run_id, stage_name)
            );
            CREATE TABLE IF NOT EXISTS releases (
                release_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id),
                project_id TEXT NOT NULL,
                location TEXT NOT NULL,
                release_dataset TEXT NOT NULL,
                exchange_table TEXT NOT NULL,
                weather_table TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                published_at TEXT,
                previous_release_id TEXT,
                gate_evidence_json TEXT NOT NULL,
                counts_json TEXT NOT NULL,
                coverage_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS publication_attempts (
                publication_attempt_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id),
                release_id TEXT NOT NULL REFERENCES releases(release_id),
                previous_release_id TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                job_id TEXT,
                current_release_id TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS release_exports (
                release_id TEXT NOT NULL REFERENCES releases(release_id),
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT,
                status TEXT NOT NULL,
                completed_at TEXT,
                error TEXT,
                PRIMARY KEY(release_id, kind)
            );
            CREATE TABLE IF NOT EXISTS backfill_compositions (
                composition_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                baseline_batch_id TEXT NOT NULL,
                replacement_batch_id TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                output_path TEXT NOT NULL,
                output_sha256 TEXT NOT NULL,
                added_count INTEGER NOT NULL,
                replaced_count INTEGER NOT NULL,
                removed_count INTEGER NOT NULL,
                unchanged_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def ensure_scope(self, scope_id: str, source: str, scope: dict[str, Any]) -> None:
        scope_json = canonical_json(scope)
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO scopes(scope_id,source,scope_json,created_at) VALUES(?,?,?,?)",
                (scope_id, source, scope_json, utc_now()),
            )
        stored = self.connection.execute(
            "SELECT source,scope_json FROM scopes WHERE scope_id=?", (scope_id,)
        ).fetchone()
        if stored is None or stored["source"] != source or stored["scope_json"] != scope_json:
            raise RuntimeError(f"scope identity collision: {scope_id}")

    def start_attempt(self, scope_id: str, details: dict[str, Any] | None = None) -> str:
        attempt_id = f"attempt_{uuid.uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """INSERT INTO attempts
                   (attempt_id,scope_id,started_at,status,details_json)
                   VALUES(?,?,?,?,?)""",
                (attempt_id, scope_id, utc_now(), "running", canonical_json(details or {})),
            )
        return attempt_id

    def finish_attempt(
        self,
        attempt_id: str,
        *,
        status: str,
        elapsed_seconds: float,
        request_count: int,
        batch_id: str | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE attempts SET ended_at=?,status=?,elapsed_seconds=?,request_count=?,
                   batch_id=?,error=?,details_json=? WHERE attempt_id=?""",
                (
                    utc_now(), status, elapsed_seconds, request_count, batch_id,
                    error, canonical_json(details or {}), attempt_id,
                ),
            )

    def record_batch(
        self,
        batch: ReusableBatch,
        artifacts: list[tuple[str, Path, str]],
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO batches
                   (batch_id,scope_id,source,content_sha256,observation_sha256,
                    snapshot_refs_json,status,counts_json,accepted_path,rejected_path,
                    reconciliation_path,status_path,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(batch_id) DO UPDATE SET
                     observation_sha256=excluded.observation_sha256,
                     snapshot_refs_json=excluded.snapshot_refs_json,
                     status=excluded.status,
                     counts_json=excluded.counts_json,
                     accepted_path=excluded.accepted_path,
                     rejected_path=excluded.rejected_path,
                     reconciliation_path=excluded.reconciliation_path,
                     status_path=excluded.status_path,
                     completed_at=excluded.completed_at""",
                (
                    batch.batch_id, batch.scope_id, batch.source, batch.content_sha256,
                    batch.observation_sha256, canonical_json(batch.snapshot_refs),
                    "candidate-ready", canonical_json(batch.counts),
                    str(batch.accepted_path), str(batch.rejected_path),
                    str(batch.reconciliation_path), str(batch.status_path), utc_now(),
                ),
            )
            self.connection.execute("DELETE FROM artifacts WHERE batch_id=?", (batch.batch_id,))
            self.connection.executemany(
                "INSERT INTO artifacts(batch_id,kind,path,sha256) VALUES(?,?,?,?)",
                [(batch.batch_id, kind, str(path), checksum) for kind, path, checksum in artifacts],
            )

    def latest_candidate(self, scope_id: str) -> ReusableBatch | None:
        row = self.connection.execute(
            """SELECT * FROM batches WHERE scope_id=? AND status='candidate-ready'
               ORDER BY completed_at DESC LIMIT 1""",
            (scope_id,),
        ).fetchone()
        if row is None:
            return None
        return ReusableBatch(
            batch_id=row["batch_id"], source=row["source"], scope_id=row["scope_id"],
            content_sha256=row["content_sha256"], observation_sha256=row["observation_sha256"],
            snapshot_refs=json.loads(row["snapshot_refs_json"]),
            accepted_path=Path(row["accepted_path"]), rejected_path=Path(row["rejected_path"]),
            reconciliation_path=Path(row["reconciliation_path"]),
            status_path=Path(row["status_path"]), counts=json.loads(row["counts_json"]),
        )

    def candidate(self, batch_id: str) -> ReusableBatch | None:
        row = self.connection.execute(
            "SELECT * FROM batches WHERE batch_id=? AND status='candidate-ready'", (batch_id,)
        ).fetchone()
        return self._batch_from_row(row) if row is not None else None

    def latest_candidate_for_source(self, source: str) -> ReusableBatch | None:
        row = self.connection.execute(
            """SELECT * FROM batches WHERE source=? AND status='candidate-ready'
               ORDER BY completed_at DESC, batch_id DESC LIMIT 1""",
            (source,),
        ).fetchone()
        return self._batch_from_row(row) if row is not None else None

    @staticmethod
    def _batch_from_row(row: sqlite3.Row) -> ReusableBatch:
        return ReusableBatch(
            batch_id=row["batch_id"], source=row["source"], scope_id=row["scope_id"],
            content_sha256=row["content_sha256"], observation_sha256=row["observation_sha256"],
            snapshot_refs=json.loads(row["snapshot_refs_json"]),
            accepted_path=Path(row["accepted_path"]), rejected_path=Path(row["rejected_path"]),
            reconciliation_path=Path(row["reconciliation_path"]),
            status_path=Path(row["status_path"]), counts=json.loads(row["counts_json"]),
        )

    def start_load_attempt(
        self,
        *,
        batch_id: str,
        project_id: str,
        dataset_id: str,
        table_id: str,
        job_id: str,
        local_row_count: int,
        artifact_sha256: str,
        schema_sha256: str,
    ) -> str:
        attempt_id = f"load_attempt_{uuid.uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """INSERT INTO load_attempts
                   (load_attempt_id,batch_id,project_id,dataset_id,table_id,job_id,
                    started_at,status,local_row_count,artifact_sha256,schema_sha256,details_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    attempt_id, batch_id, project_id, dataset_id, table_id, job_id,
                    utc_now(), "running", local_row_count, artifact_sha256, schema_sha256,
                    canonical_json({}),
                ),
            )
        return attempt_id

    def finish_load_attempt(
        self,
        load_attempt_id: str,
        *,
        status: str,
        warehouse_row_count: int | None = None,
        table_bytes: int | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE load_attempts SET ended_at=?,status=?,warehouse_row_count=?,
                   table_bytes=?,error=?,details_json=? WHERE load_attempt_id=?""",
                (
                    utc_now(), status, warehouse_row_count, table_bytes, error,
                    canonical_json(details or {}), load_attempt_id,
                ),
            )

    def record_warehouse_load(self, load: WarehouseLoad) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO warehouse_loads
                   (load_id,batch_id,project_id,dataset_id,table_id,job_id,artifact_sha256,
                    schema_sha256,local_row_count,warehouse_row_count,table_bytes,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(load_id) DO UPDATE SET
                     job_id=excluded.job_id,
                     warehouse_row_count=excluded.warehouse_row_count,
                     table_bytes=excluded.table_bytes,
                     completed_at=excluded.completed_at""",
                (
                    load.load_id, load.batch_id, load.project_id, load.dataset_id,
                    load.table_id, load.job_id, load.artifact_sha256, load.schema_sha256,
                    load.local_row_count, load.warehouse_row_count, load.table_bytes,
                    load.completed_at,
                ),
            )

    def warehouse_load(self, load_id: str) -> WarehouseLoad | None:
        row = self.connection.execute(
            "SELECT * FROM warehouse_loads WHERE load_id=?", (load_id,)
        ).fetchone()
        return WarehouseLoad(**dict(row)) if row is not None else None

    def start_pipeline_run(
        self,
        *,
        run_id: str,
        scope: dict[str, Any],
        selected_batches: dict[str, str],
        model_fingerprint: str,
        config_fingerprint: str,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO pipeline_runs
                   (run_id,started_at,status,scope_json,selected_batches_json,
                    model_fingerprint,config_fingerprint)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(run_id) DO NOTHING""",
                (
                    run_id, utc_now(), "running", canonical_json(scope),
                    canonical_json(selected_batches), model_fingerprint,
                    config_fingerprint,
                ),
            )

    def finish_pipeline_run(self, run_id: str, *, status: str, error: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE pipeline_runs SET ended_at=?,status=?,error=? WHERE run_id=?",
                (utc_now(), status, error, run_id),
            )

    def start_stage(self, run_id: str, stage_name: str) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO run_stages
                   (run_id,stage_name,started_at,status,evidence_json)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(run_id,stage_name) DO UPDATE SET
                     started_at=excluded.started_at,ended_at=NULL,status='running',
                     evidence_json=excluded.evidence_json,error=NULL""",
                (run_id, stage_name, utc_now(), "running", canonical_json({})),
            )

    def finish_stage(
        self,
        run_id: str,
        stage_name: str,
        *,
        status: str,
        evidence: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE run_stages SET ended_at=?,status=?,evidence_json=?,error=?
                   WHERE run_id=? AND stage_name=?""",
                (utc_now(), status, canonical_json(evidence or {}), error, run_id, stage_name),
            )

    def stage(self, run_id: str, stage_name: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM run_stages WHERE run_id=? AND stage_name=?",
            (run_id, stage_name),
        ).fetchone()

    def record_release(
        self,
        *,
        release_id: str,
        run_id: str,
        project_id: str,
        location: str,
        release_dataset: str,
        exchange_table: str,
        weather_table: str,
        status: str,
        previous_release_id: str | None,
        gate_evidence: dict[str, Any],
        counts: dict[str, Any],
        coverage: dict[str, Any],
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO releases
                   (release_id,run_id,project_id,location,release_dataset,
                    exchange_table,weather_table,status,created_at,previous_release_id,
                    gate_evidence_json,counts_json,coverage_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(release_id) DO UPDATE SET
                     status=excluded.status,gate_evidence_json=excluded.gate_evidence_json,
                     counts_json=excluded.counts_json,coverage_json=excluded.coverage_json""",
                (
                    release_id, run_id, project_id, location, release_dataset,
                    exchange_table, weather_table, status, utc_now(), previous_release_id,
                    canonical_json(gate_evidence), canonical_json(counts),
                    canonical_json(coverage),
                ),
            )

    def start_publication_attempt(
        self, run_id: str, release_id: str, previous_release_id: str | None
    ) -> str:
        attempt_id = f"publication_attempt_{uuid.uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """INSERT INTO publication_attempts
                   (publication_attempt_id,run_id,release_id,previous_release_id,
                    started_at,status) VALUES(?,?,?,?,?,?)""",
                (attempt_id, run_id, release_id, previous_release_id, utc_now(), "running"),
            )
        return attempt_id

    def finish_publication_attempt(
        self,
        attempt_id: str,
        *,
        status: str,
        job_id: str | None = None,
        current_release_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE publication_attempts SET ended_at=?,status=?,job_id=?,
                   current_release_id=?,error=? WHERE publication_attempt_id=?""",
                (utc_now(), status, job_id, current_release_id, error, attempt_id),
            )
            if status in {"published", "published_recovered"} and current_release_id:
                self.connection.execute(
                    "UPDATE releases SET status='published',published_at=? WHERE release_id=?",
                    (utc_now(), current_release_id),
                )

    def latest_published_release(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM releases WHERE status='published' ORDER BY published_at DESC LIMIT 1"
        ).fetchone()

    def release(self, release_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM releases WHERE release_id=?", (release_id,)
        ).fetchone()

    def latest_pipeline_run(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

    def stages_for_run(self, run_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM run_stages WHERE run_id=? ORDER BY started_at", (run_id,)
        ).fetchall()

    def record_export(
        self,
        release_id: str,
        kind: str,
        path: Path,
        *,
        status: str,
        sha256: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO release_exports
                   (release_id,kind,path,sha256,status,completed_at,error)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(release_id,kind) DO UPDATE SET
                     path=excluded.path,sha256=excluded.sha256,status=excluded.status,
                     completed_at=excluded.completed_at,error=excluded.error""",
                (release_id, kind, str(path), sha256, status, utc_now(), error),
            )

    def record_backfill_composition(
        self,
        *,
        composition_id: str,
        source: str,
        baseline_batch_id: str,
        replacement_batch_id: str,
        scope: dict[str, Any],
        output_path: Path,
        output_sha256: str,
        counts: dict[str, int],
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT OR REPLACE INTO backfill_compositions
                   (composition_id,source,baseline_batch_id,replacement_batch_id,
                    scope_json,output_path,output_sha256,added_count,replaced_count,
                    removed_count,unchanged_count,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    composition_id, source, baseline_batch_id, replacement_batch_id,
                    canonical_json(scope), str(output_path), output_sha256,
                    counts["added"], counts["replaced"], counts["removed"],
                    counts["unchanged"], utc_now(),
                ),
            )

    def verify_batch(self, batch_id: str) -> tuple[bool, list[str]]:
        failures: list[str] = []
        rows = self.connection.execute(
            "SELECT kind,path,sha256 FROM artifacts WHERE batch_id=?", (batch_id,)
        ).fetchall()
        if not rows:
            return False, ["manifest has no artifacts"]
        for row in rows:
            path = Path(row["path"])
            if not path.is_file():
                failures.append(f"missing {row['kind']}: {path}")
            elif sha256_file(path) != row["sha256"]:
                failures.append(f"checksum mismatch {row['kind']}: {path}")
        return not failures, failures

    def attempts_for_scope(self, scope_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM attempts WHERE scope_id=? ORDER BY started_at", (scope_id,)
        ).fetchall()

