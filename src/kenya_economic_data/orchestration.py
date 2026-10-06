"""Single-command Phase 3 orchestration and operational recovery."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import time
from contextlib import AbstractContextManager
from datetime import date
from pathlib import Path
from typing import Any

from .config import Settings
from .io_utils import (
    atomic_replace_json,
    atomic_write_json_once,
    atomic_write_once,
    canonical_json,
    identity,
    sha256_file,
)
from .manifest import Manifest
from .pipeline import extract_cbk, extract_nasa, sanitize_error
from .release import (
    ReleaseGateway,
    canonical_view_sql,
    freeze_release_tables,
    publish_canonical_view,
    release_fingerprint,
    reporting_rows,
)
from .warehouse import BigQueryGateway, load_candidate_batch


STAGES = (
    "preflight", "extract", "load", "candidate_tests", "reconciliation",
    "freeze_release", "publication", "export",
)


class PipelineLock(AbstractContextManager["PipelineLock"]):
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.acquired = False

    def __enter__(self) -> "PipelineLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_json({"run_id": self.run_id, "pid": os.getpid()}).encode("utf-8")
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            existing = self.path.read_text(encoding="utf-8", errors="replace")[:500]
            raise RuntimeError(f"pipeline lock already held: {existing}") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        self.acquired = True
        return self

    def __exit__(self, *_: object) -> None:
        if self.acquired and self.path.exists():
            current = self.path.read_text(encoding="utf-8", errors="replace")
            if self.run_id in current:
                self.path.unlink()


def operate(
    settings: Settings,
    *,
    project_id: str,
    location: str,
    candidate_dataset: str,
    trusted_dataset: str,
    start_date: date,
    end_date: date,
    location_names: tuple[str, ...],
    profiles_dir: Path,
    cbk_batch_id: str | None = None,
    nasa_batch_id: str | None = None,
) -> dict[str, Any]:
    root = settings.project_root
    manifest_path = root / "data" / "manifests" / "ingestion.sqlite3"
    model_paths = _model_paths(root)
    model_fingerprint = release_fingerprint(model_paths)
    config_fingerprint = release_fingerprint([
        root / "config" / "settings.example.toml",
        root / "config" / "profiles.example.yml",
        root / "schemas" / "cbk_exchange_rates.json",
        root / "schemas" / "nasa_weather.json",
        root / "src" / "kenya_economic_data" / "orchestration.py",
        root / "src" / "kenya_economic_data" / "release.py",
        root / "src" / "kenya_economic_data" / "warehouse.py",
    ])
    with Manifest(manifest_path) as manifest:
        cbk = (
            manifest.candidate(cbk_batch_id) if cbk_batch_id
            else manifest.latest_candidate_for_source("cbk")
        )
        nasa = (
            manifest.candidate(nasa_batch_id) if nasa_batch_id
            else manifest.latest_candidate_for_source("nasa_power")
        )
        if cbk is None or nasa is None:
            raise RuntimeError("both Phase 1 source candidates are required")
        if cbk.source != "cbk" or nasa.source != "nasa_power":
            raise RuntimeError("explicit batch source does not match its domain")
        input_profile = _input_profile(cbk.accepted_path, nasa.accepted_path)
        selected_batches = {"cbk": cbk.batch_id, "nasa_power": nasa.batch_id}
        scope = {
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "currencies": ["USD", "GBP", "EUR"],
            "locations": list(location_names), "candidate_dataset": candidate_dataset,
            "trusted_dataset": trusted_dataset, "project_id": project_id,
            "location": location,
        }
        run_id = identity("run", {
            "scope": scope, "selected_batches": selected_batches,
            "model_fingerprint": model_fingerprint,
            "config_fingerprint": config_fingerprint,
        })
        release_id = identity("release", {
            "scope": scope, "selected_batches": selected_batches,
            "model_fingerprint": model_fingerprint,
        })
        release_dataset = f"kep_release_{release_id.removeprefix('release_')}"

    lock_path = root / "data" / "manifests" / "pipeline.lock"
    with PipelineLock(lock_path, run_id):
        gateway = ReleaseGateway(project_id, location)
        warehouse = BigQueryGateway(project_id, location)
        with Manifest(manifest_path) as manifest:
            _reconcile_interrupted_publications(manifest, gateway, trusted_dataset)
            manifest.start_pipeline_run(
                run_id=run_id, scope=scope, selected_batches=selected_batches,
                model_fingerprint=model_fingerprint,
                config_fingerprint=config_fingerprint,
            )
            current_stage = "preflight"
            published = False
            stage_evidence: dict[str, Any] = {}
            try:
                manifest.start_stage(run_id, current_stage)
                if not _billing_disabled(project_id):
                    raise RuntimeError("cloud writes stopped: billing is enabled or unverified")
                _assert_candidate_namespace(
                    manifest, candidate_dataset=candidate_dataset,
                    selected_batches=selected_batches,
                    model_fingerprint=model_fingerprint,
                )
                candidate_meta = gateway.ensure_owned_dataset(candidate_dataset, "phase2_candidate")
                preflight = {
                    "billing_disabled": True,
                    "candidate_dataset": candidate_meta,
                    "global_project_changed": False,
                }
                manifest.finish_stage(run_id, current_stage, status="completed", evidence=preflight)
                stage_evidence[current_stage] = preflight

                current_stage = "extract"
                manifest.start_stage(run_id, current_stage)
                locations = [settings.locations[name] for name in location_names]
                extraction = {
                    "cbk": (
                        _selected_candidate_summary(manifest, cbk)
                        if cbk_batch_id or _is_composed(cbk) else
                        extract_cbk(
                            settings, manifest, start_date=start_date, end_date=end_date,
                            refresh=False,
                        )
                    ),
                    "nasa_power": (
                        _selected_candidate_summary(manifest, nasa)
                        if nasa_batch_id or _is_composed(nasa) else
                        extract_nasa(
                            settings, manifest, start_date=start_date, end_date=end_date,
                            locations=locations, refresh=False,
                        )
                    ),
                }
                observed_batches = {
                    source: result["batch_id"] for source, result in extraction.items()
                }
                if observed_batches != selected_batches:
                    raise RuntimeError(
                        f"selected batches changed during run: {observed_batches}"
                    )
                manifest.finish_stage(run_id, current_stage, status="reused", evidence=extraction)
                stage_evidence[current_stage] = extraction

                current_stage = "load"
                manifest.start_stage(run_id, current_stage)
                loads = {
                    "cbk": load_candidate_batch(
                        manifest, warehouse, source="cbk", project_id=project_id,
                        dataset_id=candidate_dataset, location=location,
                        schema_path=root / "schemas" / "cbk_exchange_rates.json",
                        batch_id=selected_batches["cbk"],
                    ),
                    "nasa_power": load_candidate_batch(
                        manifest, warehouse, source="nasa_power", project_id=project_id,
                        dataset_id=candidate_dataset, location=location,
                        schema_path=root / "schemas" / "nasa_weather.json",
                        batch_id=selected_batches["nasa_power"],
                    ),
                }
                manifest.finish_stage(run_id, current_stage, status="reused", evidence=loads)
                stage_evidence[current_stage] = loads

                current_stage = "candidate_tests"
                dbt_evidence = reusable_dbt_evidence(
                    manifest, root, model_paths=model_paths,
                    model_fingerprint=model_fingerprint,
                    candidate_dataset=candidate_dataset,
                    selected_batches=selected_batches,
                )
                manifest.start_stage(run_id, current_stage)
                required_relations = (
                    "stg_exchange_rates", "stg_weather", "fact_exchange_rate_daily",
                    "fact_weather_daily", "mart_exchange_rate_monthly",
                    "mart_weather_monthly",
                )
                if dbt_evidence is not None and not all(
                    gateway.table_exists(f"{project_id}.{candidate_dataset}.{relation}")
                    for relation in required_relations
                ):
                    dbt_evidence = None
                if dbt_evidence is None:
                    dbt_evidence = run_candidate_dbt_build(
                        root, profiles_dir=profiles_dir,
                        project_id=project_id, location=location,
                        candidate_dataset=candidate_dataset,
                        cbk_table=loads["cbk"]["table_id"],
                        nasa_table=loads["nasa_power"]["table_id"],
                        start_date=start_date, end_date=end_date,
                        cbk_expected_rows=int(loads["cbk"]["warehouse_row_count"]),
                        weather_expected_rows=int(loads["nasa_power"]["warehouse_row_count"]),
                        input_profile=input_profile,
                        model_paths=model_paths, model_fingerprint=model_fingerprint,
                    )
                manifest.finish_stage(
                    run_id, current_stage, status="reused", evidence=dbt_evidence
                )
                stage_evidence[current_stage] = dbt_evidence

                current_stage = "reconciliation"
                manifest.start_stage(run_id, current_stage)
                reconciliation = _warehouse_reconciliation(
                    gateway, candidate_dataset=candidate_dataset,
                    cbk_table=loads["cbk"]["table_id"],
                    nasa_table=loads["nasa_power"]["table_id"],
                    expected=input_profile["expected"],
                )
                manifest.finish_stage(
                    run_id, current_stage, status="completed", evidence=reconciliation
                )
                stage_evidence[current_stage] = reconciliation

                gate_evidence = {
                    "ingestion": {key: value["candidate_ready"] for key, value in extraction.items()},
                    "loads": {key: value["warehouse_row_count"] for key, value in loads.items()},
                    "dbt": dbt_evidence,
                    "reconciliation": reconciliation,
                    "model_fingerprint": model_fingerprint,
                    "config_fingerprint": config_fingerprint,
                    "expected": input_profile["expected"],
                }
                _assert_publication_gates(gate_evidence)

                current_stage = "freeze_release"
                manifest.start_stage(run_id, current_stage)
                release_dataset_meta = gateway.ensure_owned_dataset(
                    release_dataset, f"release_{release_id[-8:]}"
                )
                trusted_dataset_meta = gateway.ensure_owned_dataset(
                    trusted_dataset, "phase3_trusted_pointer"
                )
                frozen = freeze_release_tables(
                    gateway, candidate_dataset=candidate_dataset,
                    release_dataset=release_dataset, release_id=release_id,
                    cbk_batch_id=selected_batches["cbk"],
                    nasa_batch_id=selected_batches["nasa_power"],
                    expected=input_profile["expected"],
                )
                previous_release = gateway.current_release_id(trusted_dataset)
                coverage = input_profile["coverage"]
                counts = {
                    "exchange_observations": input_profile["expected"]["cbk"]["observations"],
                    "weather_observations": input_profile["expected"]["weather"]["observations"],
                    "exchange_monthly_rows": input_profile["expected"]["cbk"]["reporting_rows"],
                    "weather_monthly_rows": input_profile["expected"]["weather"]["reporting_rows"],
                }
                manifest.record_release(
                    release_id=release_id, run_id=run_id, project_id=project_id,
                    location=location, release_dataset=release_dataset,
                    exchange_table=frozen["exchange_table"],
                    weather_table=frozen["weather_table"], status="validated",
                    previous_release_id=previous_release, gate_evidence=gate_evidence,
                    counts=counts, coverage=coverage,
                )
                freeze_evidence = {
                    **frozen, "release_dataset": release_dataset_meta,
                    "trusted_dataset": trusted_dataset_meta,
                }
                manifest.finish_stage(
                    run_id, current_stage, status="completed", evidence=freeze_evidence
                )
                stage_evidence[current_stage] = freeze_evidence

                current_stage = "publication"
                manifest.start_stage(run_id, current_stage)
                publication_attempt = manifest.start_publication_attempt(
                    run_id, release_id, previous_release
                )
                try:
                    publication = publish_canonical_view(
                        gateway, trusted_dataset=trusted_dataset,
                        release_dataset=release_dataset, release_id=release_id,
                    )
                    switch = publication.get("switch_job") or {}
                    manifest.finish_publication_attempt(
                        publication_attempt, status="published",
                        job_id=switch.get("job_id"), current_release_id=release_id,
                    )
                except Exception as exc:
                    authoritative = gateway.current_release_id(trusted_dataset)
                    if authoritative == release_id:
                        manifest.finish_publication_attempt(
                            publication_attempt, status="published_recovered",
                            current_release_id=release_id,
                        )
                    else:
                        manifest.finish_publication_attempt(
                            publication_attempt, status="failed",
                            current_release_id=authoritative, error=sanitize_error(exc),
                        )
                        raise
                published = True
                manifest.finish_stage(
                    run_id, current_stage, status="completed", evidence=publication
                )
                stage_evidence[current_stage] = publication

                current_stage = "export"
                manifest.start_stage(run_id, current_stage)
                try:
                    exports = export_release_reports(
                        manifest, gateway, trusted_dataset=trusted_dataset,
                        release_id=release_id, output_root=root / "data" / "reports",
                        coverage=coverage,
                    )
                    manifest.finish_stage(
                        run_id, current_stage, status="completed", evidence=exports
                    )
                    stage_evidence[current_stage] = exports
                    manifest.finish_pipeline_run(run_id, status="completed")
                    health = health_report(
                        manifest, gateway, trusted_dataset=trusted_dataset
                    )
                    health_path = (
                        root / "data" / "reports" / release_id / "pipeline_health.json"
                    )
                    atomic_replace_json(health_path, health)
                    manifest.record_export(
                        release_id, "pipeline_health", health_path,
                        status="completed", sha256=sha256_file(health_path),
                    )
                    stage_evidence[current_stage]["pipeline_health"] = {
                        "path": str(health_path), "sha256": sha256_file(health_path)
                    }
                except Exception as exc:
                    manifest.finish_stage(
                        run_id, current_stage, status="failed",
                        error=sanitize_error(exc), evidence={"publication_succeeded": True},
                    )
                    manifest.finish_pipeline_run(
                        run_id, status="published_export_failed", error=sanitize_error(exc)
                    )
                    raise RuntimeError(
                        f"release {release_id} is published but local export failed: {sanitize_error(exc)}"
                    ) from exc
                return {
                    "run_id": run_id, "release_id": release_id,
                    "release_dataset": release_dataset,
                    "trusted_dataset": trusted_dataset,
                    "status": "completed", "selected_batches": selected_batches,
                    "stages": stage_evidence,
                }
            except Exception as exc:
                stage = manifest.stage(run_id, current_stage)
                if stage is not None and stage["status"] == "running":
                    manifest.finish_stage(
                        run_id, current_stage, status="failed", error=sanitize_error(exc)
                    )
                if not published:
                    manifest.finish_pipeline_run(run_id, status="failed", error=sanitize_error(exc))
                raise


def verify_retained_dbt_evidence(
    root: Path, *, model_paths: list[Path], model_fingerprint: str
) -> dict[str, Any]:
    run_results_path = root / "target" / "run_results.json"
    if not run_results_path.is_file():
        raise RuntimeError("retained dbt run_results.json is missing")
    if any(path.stat().st_mtime > run_results_path.stat().st_mtime + 1 for path in model_paths):
        raise RuntimeError("retained dbt evidence is stale for current model files")
    payload = json.loads(run_results_path.read_text(encoding="utf-8"))
    results = payload.get("results", [])
    failures = [item["unique_id"] for item in results if item.get("status") not in {"pass", "success"}]
    if failures:
        raise RuntimeError("retained dbt evidence contains failures: " + ", ".join(failures))
    ids = {item["unique_id"]: item.get("status") for item in results}
    required_fragments = (
        "assert_landing_and_fact_reconciliation",
        "assert_cbk_semantics_and_completeness",
        "assert_weather_semantics_and_completeness",
        "unique_combination_stg_exchange_rates",
        "unique_combination_stg_weather",
        "unique_combination_fact_exchange_rate_daily",
        "unique_combination_fact_weather_daily",
    )
    missing = [fragment for fragment in required_fragments if not any(fragment in key for key in ids)]
    if missing:
        raise RuntimeError("retained dbt evidence lacks critical tests: " + ", ".join(missing))
    return {
        "outcome": "reused",
        "generated_at": payload.get("metadata", {}).get("generated_at"),
        "run_results_sha256": sha256_file(run_results_path),
        "model_fingerprint": model_fingerprint,
        "result_count": len(results),
        "test_pass_count": sum(item.get("status") == "pass" for item in results),
        "model_success_count": sum(item.get("status") == "success" for item in results),
        "critical_tests": {fragment: "pass" for fragment in required_fragments},
    }


def reusable_dbt_evidence(
    manifest: Manifest,
    root: Path,
    *,
    model_paths: list[Path],
    model_fingerprint: str,
    candidate_dataset: str,
    selected_batches: dict[str, str],
) -> dict[str, Any] | None:
    rows = manifest.connection.execute(
        """SELECT s.evidence_json,r.run_id,r.scope_json,r.selected_batches_json
           FROM run_stages s JOIN pipeline_runs r ON r.run_id=s.run_id
           WHERE s.stage_name='candidate_tests' AND s.status IN ('completed','reused')
             AND r.model_fingerprint=? ORDER BY s.ended_at DESC""",
        (model_fingerprint,),
    ).fetchall()
    for row in rows:
        scope = json.loads(row["scope_json"])
        batches = json.loads(row["selected_batches_json"])
        evidence = json.loads(row["evidence_json"])
        if scope.get("candidate_dataset") != candidate_dataset or batches != selected_batches:
            continue
        current = verify_retained_dbt_evidence(
            root, model_paths=model_paths, model_fingerprint=model_fingerprint
        )
        if current["run_results_sha256"] != evidence.get("run_results_sha256"):
            continue
        current["source_run_id"] = row["run_id"]
        return current
    phase2_batches = {
        "cbk": "batch_1fbe96c779d3e2aa706b",
        "nasa_power": "batch_5d09562b5edc416d16eb",
    }
    if candidate_dataset == "kep_candidate_v1" and selected_batches == phase2_batches:
        evidence = verify_retained_dbt_evidence(
            root, model_paths=model_paths, model_fingerprint=model_fingerprint
        )
        evidence["bootstrap_source"] = "verified Phase 2 run_results and immutable batch selection"
        return evidence
    return None


def run_candidate_dbt_build(
    root: Path,
    *,
    profiles_dir: Path,
    project_id: str,
    location: str,
    candidate_dataset: str,
    cbk_table: str,
    nasa_table: str,
    start_date: date,
    end_date: date,
    cbk_expected_rows: int,
    weather_expected_rows: int,
    input_profile: dict[str, Any],
    model_paths: list[Path],
    model_fingerprint: str,
) -> dict[str, Any]:
    executable = Path(os.sys.executable).with_name("dbt.exe")
    if not executable.is_file():
        raise RuntimeError(f"dbt executable not found: {executable}")
    environment = dict(os.environ)
    environment.update({
        "KEP_GCP_PROJECT": project_id,
        "GOOGLE_CLOUD_PROJECT": project_id,
        "KEP_BQ_DATASET": candidate_dataset,
        "KEP_BQ_LOCATION": location,
        "KEP_CBK_TABLE": cbk_table,
        "KEP_NASA_TABLE": nasa_table,
    })
    variables = canonical_json({
        "scope_start_date": start_date.isoformat(),
        "scope_end_date": end_date.isoformat(),
        "cbk_scope_start_date": input_profile["coverage"]["exchange"]["start_date"],
        "cbk_scope_end_date": input_profile["coverage"]["exchange"]["end_date"],
        "weather_expected_ranges": input_profile["coverage"]["weather_by_location"],
        "cbk_expected_rows": cbk_expected_rows,
        "weather_expected_rows": weather_expected_rows,
        "cbk_expected_monthly_rows": input_profile["expected"]["cbk"]["reporting_rows"],
        "weather_expected_monthly_rows": input_profile["expected"]["weather"]["reporting_rows"],
    })
    completed = subprocess.run(
        [
            str(executable), "build", "--profiles-dir", str(profiles_dir),
            "--exclude", "tag:sandbox_probe", "--full-refresh",
            "--no-partial-parse", "--vars", variables,
        ],
        cwd=root, env=environment, check=False, capture_output=True,
        text=True, timeout=600,
    )
    if completed.returncode != 0:
        tail = "\n".join((completed.stdout + "\n" + completed.stderr).splitlines()[-30:])
        raise RuntimeError("candidate dbt build failed: " + tail[:4000])
    evidence = verify_retained_dbt_evidence(
        root, model_paths=model_paths, model_fingerprint=model_fingerprint
    )
    evidence["outcome"] = "completed"
    evidence["candidate_dataset"] = candidate_dataset
    return evidence


def _warehouse_reconciliation(
    gateway: ReleaseGateway, *, candidate_dataset: str, cbk_table: str, nasa_table: str,
    expected: dict[str, dict[str, int]],
) -> dict[str, Any]:
    project = gateway.project_id
    sql = f"""
    SELECT 'cbk' AS domain,
      (SELECT COUNT(*) FROM `{project}.{candidate_dataset}.{cbk_table}`) AS landing_rows,
      (SELECT COUNT(*) FROM `{project}.{candidate_dataset}.fact_exchange_rate_daily`) AS fact_rows,
      (SELECT SUM(publication_observation_count) FROM `{project}.{candidate_dataset}.mart_exchange_rate_monthly`) AS reported_observations,
      (SELECT COUNT(*) FROM `{project}.{candidate_dataset}.mart_exchange_rate_monthly`) AS reporting_rows
    UNION ALL
    SELECT 'weather',
      (SELECT COUNT(*) FROM `{project}.{candidate_dataset}.{nasa_table}`),
      (SELECT COUNT(*) FROM `{project}.{candidate_dataset}.fact_weather_daily`),
      (SELECT SUM(observed_day_count) FROM `{project}.{candidate_dataset}.mart_weather_monthly`),
      (SELECT COUNT(*) FROM `{project}.{candidate_dataset}.mart_weather_monthly`)
    ORDER BY domain
    """
    evidence = gateway.query(sql, job_prefix="kep_gate_reconciliation_")
    for row in evidence.rows:
        domain_expected = expected[str(row["domain"])]
        observations = domain_expected["observations"]
        reporting_rows = domain_expected["reporting_rows"]
        if not (
            int(row["landing_rows"]) == observations
            and int(row["fact_rows"]) == observations
            and int(row["reported_observations"]) == observations
            and int(row["reporting_rows"]) == reporting_rows
        ):
            raise RuntimeError(f"warehouse reconciliation failed: {row}")
    return {
        "job_id": evidence.job_id,
        "bytes_processed": evidence.bytes_processed,
        "bytes_billed": evidence.bytes_billed,
        "rows": evidence.rows,
    }


def _assert_publication_gates(evidence: dict[str, Any]) -> None:
    if not all(evidence["ingestion"].values()):
        raise RuntimeError("publication gate failed: ingestion candidate not ready")
    expected_loads = {
        "cbk": evidence["expected"]["cbk"]["observations"],
        "nasa_power": evidence["expected"]["weather"]["observations"],
    }
    if evidence["loads"] != expected_loads:
        raise RuntimeError(f"publication gate failed: load counts {evidence['loads']}")
    if evidence["dbt"]["test_pass_count"] != 39:
        raise RuntimeError("publication gate failed: critical dbt evidence is incomplete")
    if (
        not evidence.get("model_fingerprint")
        or evidence["dbt"].get("model_fingerprint") != evidence["model_fingerprint"]
    ):
        raise RuntimeError("publication gate failed: dbt model fingerprint mismatch")
    if len(evidence["reconciliation"]["rows"]) != 2:
        raise RuntimeError("publication gate failed: reconciliation evidence is incomplete")


def _assert_candidate_namespace(
    manifest: Manifest,
    *,
    candidate_dataset: str,
    selected_batches: dict[str, str],
    model_fingerprint: str,
) -> None:
    published = manifest.latest_published_release()
    if published is None:
        return
    run = manifest.connection.execute(
        "SELECT selected_batches_json,scope_json,model_fingerprint FROM pipeline_runs WHERE run_id=?",
        (published["run_id"],),
    ).fetchone()
    if run is None:
        raise RuntimeError("published release is missing its pipeline run evidence")
    previous_batches = json.loads(run["selected_batches_json"])
    previous_scope = json.loads(run["scope_json"])
    inputs_or_models_changed = (
        previous_batches != selected_batches or run["model_fingerprint"] != model_fingerprint
    )
    if inputs_or_models_changed and previous_scope.get("candidate_dataset") == candidate_dataset:
        raise RuntimeError(
            "changed inputs/models require a new candidate dataset; refusing to rebuild "
            f"published release candidate namespace {candidate_dataset}"
        )


def export_release_reports(
    manifest: Manifest,
    gateway: ReleaseGateway,
    *,
    trusted_dataset: str,
    release_id: str,
    output_root: Path,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    current = gateway.current_release_id(trusted_dataset)
    if current != release_id:
        raise RuntimeError(f"cannot export non-current release {release_id}; current is {current}")
    results = reporting_rows(
        gateway, trusted_dataset=trusted_dataset, release_id=release_id
    )
    output_dir = output_root / release_id
    evidence: dict[str, Any] = {}
    for domain, result in results.items():
        csv_path = output_dir / f"{domain}_summary.csv"
        metadata_path = output_dir / f"{domain}_summary.metadata.json"
        atomic_write_once(csv_path, _rows_csv(result.rows))
        stable_metadata = {
            "release_id": release_id,
            "domain": domain,
            "coverage": coverage,
            "definition": (
                "Arithmetic mean of available CBK published daily mean rates; KES per one foreign unit"
                if domain == "exchange"
                else "Mean daily T2M in C and sum of complete daily PRECTOTCORR in mm"
            ),
            "source_batch_ids": sorted({str(row["source_batch_id"]) for row in result.rows}),
        }
        if metadata_path.exists():
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            if any(existing.get(key) != value for key, value in stable_metadata.items()):
                raise RuntimeError(f"existing report metadata differs: {metadata_path}")
        else:
            atomic_write_json_once(metadata_path, stable_metadata)
        manifest.record_export(
            release_id, domain, csv_path, status="completed", sha256=sha256_file(csv_path)
        )
        evidence[domain] = {
            "path": str(csv_path), "metadata_path": str(metadata_path),
            "sha256": sha256_file(csv_path), "row_count": len(result.rows),
            "job_id": result.job_id, "bytes_processed": result.bytes_processed,
            "bytes_billed": result.bytes_billed,
        }
    return evidence


def health_report(
    manifest: Manifest, gateway: ReleaseGateway, *, trusted_dataset: str
) -> dict[str, Any]:
    latest_run = manifest.latest_pipeline_run()
    published = manifest.latest_published_release()
    current_release = gateway.current_release_id(trusted_dataset)
    stages = [] if latest_run is None else [dict(row) for row in manifest.stages_for_run(latest_run["run_id"])]
    report: dict[str, Any] = {
        "latest_attempt": dict(latest_run) if latest_run is not None else None,
        "latest_attempt_stages": stages,
        "latest_successful_published_release": dict(published) if published is not None else None,
        "warehouse_current_release_id": current_release,
        "publication_state": "never_published" if current_release is None else "published",
        "sources": {
            source: _source_health(manifest, source)
            for source in ("cbk", "nasa_power")
        },
        "query_volume": _stage_query_volume(stages),
    }
    if published is not None:
        exchange_ref = (
            f"{published['project_id']}.{published['release_dataset']}.{published['exchange_table']}"
        )
        weather_ref = (
            f"{published['project_id']}.{published['release_dataset']}.{published['weather_table']}"
        )
        resources = {
            "exchange": gateway.relation_metadata(exchange_ref),
            "weather": gateway.relation_metadata(weather_ref),
        }
        report["release_resources"] = resources
        if any(item["state"] != "available" for item in resources.values()):
            report["publication_state"] = "expired_requires_reconstruction"
    return report


def _source_health(manifest: Manifest, source: str) -> dict[str, Any]:
    batch = manifest.latest_candidate_for_source(source)
    if batch is None:
        return {"state": "never_extracted"}
    scope_row = manifest.connection.execute(
        "SELECT scope_json FROM scopes WHERE scope_id=?", (batch.scope_id,)
    ).fetchone()
    scope = json.loads(scope_row["scope_json"]) if scope_row is not None else {}
    reconciliation = json.loads(batch.reconciliation_path.read_text(encoding="utf-8"))
    retrieval_times: list[str] = []
    for reference in batch.snapshot_refs:
        metadata_path = reference.get("metadata_path")
        if metadata_path and Path(metadata_path).is_file():
            metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
            if metadata.get("retrieved_at"):
                retrieval_times.append(str(metadata["retrieved_at"]))
    return {
        "state": "candidate_ready",
        "batch_id": batch.batch_id,
        "scope_id": batch.scope_id,
        "retrieval_timestamps": sorted(retrieval_times),
        "retrieval_note": (
            None if retrieval_times else "retrieval timestamp unavailable for reused Phase 0 snapshot"
        ),
        "requested_start_date": scope.get("start_date"),
        "requested_end_date": scope.get("end_date"),
        "source_max_observation_date": reconciliation.get("source_max_observation_date"),
        "accepted_observation_count": batch.counts.get("accepted_observation_count"),
        "historical_freshness_policy": "observation age is not a live-feed failure gate",
    }


def _stage_query_volume(stages: list[dict[str, Any]]) -> dict[str, int]:
    processed = 0
    billed = 0

    def visit(value: Any) -> None:
        nonlocal processed, billed
        if isinstance(value, dict):
            if isinstance(value.get("bytes_processed"), int):
                processed += value["bytes_processed"]
            if isinstance(value.get("bytes_billed"), int):
                billed += value["bytes_billed"]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for stage in stages:
        try:
            visit(json.loads(stage["evidence_json"]))
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
    return {"recorded_bytes_processed": processed, "recorded_bytes_billed": billed}


def rollback_release(
    manifest: Manifest, gateway: ReleaseGateway, *, trusted_dataset: str
) -> dict[str, Any]:
    current_id = gateway.current_release_id(trusted_dataset)
    if current_id is None:
        raise RuntimeError("cannot rollback: never published")
    current = manifest.release(current_id)
    if current is None or not current["previous_release_id"]:
        raise RuntimeError("cannot rollback: no previous release is recorded")
    previous = manifest.release(current["previous_release_id"])
    if previous is None:
        raise RuntimeError("cannot rollback: previous release record is missing")
    for table in (previous["exchange_table"], previous["weather_table"]):
        metadata = gateway.relation_metadata(
            f"{previous['project_id']}.{previous['release_dataset']}.{table}"
        )
        if metadata["state"] != "available":
            raise RuntimeError("cannot rollback: previous release resource expired")
    attempt = manifest.start_publication_attempt(
        current["run_id"], previous["release_id"], current_id
    )
    evidence = gateway.query(
        canonical_view_sql(
            project_id=gateway.project_id, trusted_dataset=trusted_dataset,
            release_dataset=previous["release_dataset"],
        ),
        job_prefix=f"kep_rollback_{previous['release_id'][-8:]}_",
    )
    authoritative = gateway.current_release_id(trusted_dataset)
    if authoritative != previous["release_id"]:
        manifest.finish_publication_attempt(
            attempt, status="failed", job_id=evidence.job_id,
            current_release_id=authoritative, error="rollback verification failed",
        )
        raise RuntimeError("rollback verification failed")
    manifest.finish_publication_attempt(
        attempt, status="published", job_id=evidence.job_id,
        current_release_id=authoritative,
    )
    return {
        "from_release_id": current_id, "to_release_id": authoritative,
        "job_id": evidence.job_id, "bytes_processed": evidence.bytes_processed,
        "bytes_billed": evidence.bytes_billed,
    }


def _reconcile_interrupted_publications(
    manifest: Manifest, gateway: ReleaseGateway, trusted_dataset: str
) -> None:
    rows = manifest.connection.execute(
        "SELECT * FROM publication_attempts WHERE status='running' ORDER BY started_at"
    ).fetchall()
    if not rows:
        return
    current = gateway.current_release_id(trusted_dataset)
    for row in rows:
        if current == row["release_id"]:
            manifest.finish_publication_attempt(
                row["publication_attempt_id"], status="published_recovered",
                current_release_id=current,
            )
        else:
            manifest.finish_publication_attempt(
                row["publication_attempt_id"], status="interrupted",
                current_release_id=current,
                error="local run interrupted before verified publication",
            )


def _billing_disabled(project_id: str) -> bool:
    executable = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if executable is None:
        candidate = (
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Cloud SDK" /
            "google-cloud-sdk" / "bin" / "gcloud.cmd"
        )
        executable = str(candidate) if candidate.is_file() else None
    if executable is None:
        raise RuntimeError("gcloud executable not found for billing preflight")
    completed = subprocess.run(
        [executable, "billing", "projects", "describe", project_id,
         "--format=value(billingEnabled)"],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("billing preflight failed")
    return completed.stdout.strip().lower() == "false"


def _is_composed(batch: Any) -> bool:
    return any(reference.get("kind") == "composition_input" for reference in batch.snapshot_refs)


def _selected_candidate_summary(manifest: Manifest, batch: Any) -> dict[str, Any]:
    valid, failures = manifest.verify_batch(batch.batch_id)
    if not valid:
        raise RuntimeError(
            f"selected candidate verification failed for {batch.batch_id}: "
            + "; ".join(failures)
        )
    return {
        "source": batch.source,
        "scope_id": batch.scope_id,
        "batch_id": batch.batch_id,
        "attempt_id": None,
        "attempt_status": (
            "composed_effective_input_reused" if _is_composed(batch)
            else "explicit_verified_batch_reused"
        ),
        "candidate_ready": True,
        "content_sha256": batch.content_sha256,
        "observation_sha256": batch.observation_sha256,
        "accepted_path": str(batch.accepted_path),
        "reconciliation_path": str(batch.reconciliation_path),
        "request_count": 0,
        "counts": batch.counts,
    }


def _input_profile(cbk_path: Path, nasa_path: Path) -> dict[str, Any]:
    with cbk_path.open(encoding="utf-8", newline="") as stream:
        cbk_rows = list(csv.DictReader(stream))
    with nasa_path.open(encoding="utf-8", newline="") as stream:
        nasa_rows = list(csv.DictReader(stream))
    if not cbk_rows or not nasa_rows:
        raise RuntimeError("effective inputs must contain both reporting domains")

    cbk_keys = {(row["observation_date"], row["currency_code"]) for row in cbk_rows}
    nasa_keys = {(row["observation_date"], row["location_name"]) for row in nasa_rows}
    if len(cbk_keys) != len(cbk_rows) or len(nasa_keys) != len(nasa_rows):
        raise RuntimeError("effective input contains duplicate business keys")

    cbk_dates = sorted({row["observation_date"] for row in cbk_rows})
    weather_by_location: dict[str, dict[str, Any]] = {}
    for location_name in sorted({row["location_name"] for row in nasa_rows}):
        dates = sorted(
            row["observation_date"] for row in nasa_rows
            if row["location_name"] == location_name
        )
        weather_by_location[location_name] = {
            "start_date": dates[0], "end_date": dates[-1],
            "observation_count": len(dates),
        }
    cbk_months = {(day[:7], currency) for day, currency in cbk_keys}
    nasa_months = {(day[:7], location_name) for day, location_name in nasa_keys}
    all_starts = [cbk_dates[0], *[value["start_date"] for value in weather_by_location.values()]]
    all_ends = [cbk_dates[-1], *[value["end_date"] for value in weather_by_location.values()]]
    return {
        "expected": {
            "cbk": {"observations": len(cbk_rows), "reporting_rows": len(cbk_months)},
            "weather": {"observations": len(nasa_rows), "reporting_rows": len(nasa_months)},
        },
        "coverage": {
            "start_date": min(all_starts), "end_date": max(all_ends),
            "exchange": {
                "start_date": cbk_dates[0], "end_date": cbk_dates[-1],
                "publication_dates": len(cbk_dates),
            },
            "weather_by_location": weather_by_location,
        },
    }


def _model_paths(root: Path) -> list[Path]:
    paths = [root / "dbt_project.yml", root / "config" / "profiles.example.yml"]
    for directory in (root / "models", root / "macros", root / "tests" / "dbt"):
        paths.extend(path for path in directory.rglob("*") if path.is_file())
    return paths


def _rows_csv(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        raise RuntimeError("report query returned no rows")
    import io
    stream = io.StringIO(newline="")
    fields = list(rows[0])
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _text(value) for key, value in row.items()})
    return stream.getvalue().encode("utf-8")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
