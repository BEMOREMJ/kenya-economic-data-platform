"""Run the isolated Phase 4 missing-weather-observation acceptance test."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kenya_economic_data.io_utils import canonical_json, identity, sha256_bytes
from kenya_economic_data.manifest import Manifest
from kenya_economic_data.orchestration import _assert_publication_gates, _input_profile
from kenya_economic_data.release import ReleaseGateway, release_fingerprint


PROJECT = "elevated-legacy-457718-h2"
LOCATION = "US"
TRUSTED_DATASET = "kep_trusted_v1"
SOURCE_DATASET = "kep_candidate_backfill_202309_nairobi_v1"
FAULT_DATASET = "kep_acceptance_fault_missing_nairobi_20230915_v1"
CBK_TABLE = "landing_cbk_fault_verified_copy"
NASA_TABLE = "landing_nasa_fault_missing_nairobi_20230915"
EXPECTED_RELEASE = "release_00e432b9ddf0abe27a84"
FAULT_KEY = {"observation_date": "2023-09-15", "location_name": "Nairobi"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "data" / "manifests" / "ingestion.sqlite3"
    profile = _input_profile(
        root / "data" / "processed" / "cbk" / "scope_bea223740d6a057c46bc"
        / "batch_1fbe96c779d3e2aa706b" / "accepted.csv",
        root / "data" / "processed" / "compositions"
        / "composition_a42482249b647d68ddaa" / "accepted.csv",
    )
    model_paths = [root / "dbt_project.yml", root / "config" / "profiles.example.yml"]
    for directory in (root / "models", root / "macros", root / "tests" / "dbt"):
        model_paths.extend(path for path in directory.rglob("*") if path.is_file())
    model_fingerprint = release_fingerprint(model_paths)
    run_id = identity("run", {
        "acceptance": "phase4_missing_required_weather_observation",
        "fault_dataset": FAULT_DATASET,
        "fault_key": FAULT_KEY,
        "model_fingerprint": model_fingerprint,
    })
    gateway = ReleaseGateway(PROJECT, LOCATION)
    before_release = gateway.current_release_id(TRUSTED_DATASET)
    if before_release != EXPECTED_RELEASE:
        raise RuntimeError(
            f"canonical release mismatch before fault injection: {before_release}"
        )
    before_content = _canonical_content(gateway)

    with Manifest(manifest_path) as manifest:
        manifest.start_pipeline_run(
            run_id=run_id,
            scope={
                "acceptance_only": True,
                "fault_injection": FAULT_KEY,
                "candidate_dataset": FAULT_DATASET,
                "trusted_dataset": TRUSTED_DATASET,
            },
            selected_batches={
                "cbk": "verified_copy:batch_1fbe96c779d3e2aa706b",
                "nasa_power": "fault_copy:composition_a42482249b647d68ddaa",
            },
            model_fingerprint=model_fingerprint,
            config_fingerprint=sha256_bytes(b"phase4-isolated-fault-v1"),
        )
        manifest.start_stage(run_id, "preflight")
        dataset = gateway.ensure_owned_dataset(FAULT_DATASET, "phase4_fault_injection")
        if gateway.table_exists(f"{PROJECT}.{FAULT_DATASET}.{CBK_TABLE}"):
            raise RuntimeError("fault-injection CBK table already exists; refusing mutation")
        if gateway.table_exists(f"{PROJECT}.{FAULT_DATASET}.{NASA_TABLE}"):
            raise RuntimeError("fault-injection NASA table already exists; refusing mutation")
        cbk_job = gateway.query(
            f"CREATE TABLE `{PROJECT}.{FAULT_DATASET}.{CBK_TABLE}` "
            "OPTIONS(description='Phase 4 acceptance-only verified CBK copy') AS "
            f"SELECT * FROM `{PROJECT}.{SOURCE_DATASET}.landing_cbk__batch_1fbe96c779d3e2aa706b`",
            job_prefix="kep_p4_fault_copy_cbk_",
        )
        nasa_job = gateway.query(
            f"CREATE TABLE `{PROJECT}.{FAULT_DATASET}.{NASA_TABLE}` "
            "OPTIONS(description='Phase 4 acceptance-only copy missing Nairobi 2023-09-15') AS "
            f"SELECT * FROM `{PROJECT}.{SOURCE_DATASET}.landing_nasa_power__composition_a42482249b647d68ddaa` "
            "WHERE NOT (observation_date=DATE '2023-09-15' AND location_name='Nairobi')",
            job_prefix="kep_p4_fault_copy_nasa_",
        )
        manifest.finish_stage(run_id, "preflight", status="completed", evidence={
            "dataset": dataset,
            "fault_key": FAULT_KEY,
            "jobs": [_job(cbk_job), _job(nasa_job)],
        })

        manifest.start_stage(run_id, "candidate_tests")
        environment = dict(os.environ)
        environment.update({
            "KEP_GCP_PROJECT": PROJECT,
            "GOOGLE_CLOUD_PROJECT": PROJECT,
            "KEP_BQ_DATASET": FAULT_DATASET,
            "KEP_BQ_LOCATION": LOCATION,
            "KEP_CBK_TABLE": CBK_TABLE,
            "KEP_NASA_TABLE": NASA_TABLE,
        })
        variables = canonical_json({
            "scope_start_date": profile["coverage"]["start_date"],
            "scope_end_date": profile["coverage"]["end_date"],
            "cbk_scope_start_date": profile["coverage"]["exchange"]["start_date"],
            "cbk_scope_end_date": profile["coverage"]["exchange"]["end_date"],
            "weather_expected_ranges": profile["coverage"]["weather_by_location"],
            "cbk_expected_rows": profile["expected"]["cbk"]["observations"],
            "weather_expected_rows": profile["expected"]["weather"]["observations"],
            "cbk_expected_monthly_rows": profile["expected"]["cbk"]["reporting_rows"],
            "weather_expected_monthly_rows": profile["expected"]["weather"]["reporting_rows"],
        })
        executable = Path(sys.executable).with_name("dbt.exe")
        completed = subprocess.run(
            [
                str(executable), "build", "--profiles-dir", str(root / "config"),
                "--exclude", "tag:sandbox_probe", "--full-refresh",
                "--no-partial-parse", "--vars", variables,
            ],
            cwd=root, env=environment, check=False, capture_output=True,
            text=True, timeout=600,
        )
        results_path = root / "target" / "run_results.json"
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        failures = [
            {
                "unique_id": result.get("unique_id"),
                "status": result.get("status"),
                "message": result.get("message"),
            }
            for result in payload.get("results", [])
            if result.get("status") not in {"pass", "success"}
        ]
        test_pass_count = sum(
            result.get("status") == "pass" for result in payload.get("results", [])
        )
        gate_error = None
        try:
            _assert_publication_gates({
                "ingestion": {"cbk": True, "nasa_power": True},
                "loads": {"cbk": 177, "nasa_power": 305},
                "expected": profile["expected"],
                "dbt": {
                    "test_pass_count": test_pass_count,
                    "model_fingerprint": model_fingerprint,
                },
                "model_fingerprint": model_fingerprint,
                "reconciliation": {"rows": []},
            })
        except RuntimeError as exc:
            gate_error = str(exc)
        if completed.returncode == 0 or not failures or gate_error is None:
            raise RuntimeError("fault injection did not produce the required real gate failure")

        after_release = gateway.current_release_id(TRUSTED_DATASET)
        after_content = _canonical_content(gateway)
        evidence = {
            "acceptance_only": True,
            "candidate_dataset": FAULT_DATASET,
            "fault_key": FAULT_KEY,
            "dbt_returncode": completed.returncode,
            "test_pass_count": test_pass_count,
            "failures": failures,
            "publication_gate_error": gate_error,
            "publication_called": False,
            "canonical_before": before_release,
            "canonical_after": after_release,
            "trusted_content_sha256_before": before_content,
            "trusted_content_sha256_after": after_content,
        }
        manifest.finish_stage(
            run_id, "candidate_tests", status="failed", evidence=evidence,
            error=gate_error,
        )
        manifest.finish_pipeline_run(run_id, status="failed", error=gate_error)
        print(json.dumps({"run_id": run_id, **evidence}, indent=2, sort_keys=True))
        return 1


def _canonical_content(gateway: ReleaseGateway) -> str:
    result = gateway.query(
        f"SELECT * FROM `{PROJECT}.{TRUSTED_DATASET}.canonical_release` "
        "ORDER BY domain,month_start,COALESCE(currency_code,location_id)",
        job_prefix="kep_p4_fault_canonical_check_",
    )
    normalized = [
        {
            key: (
                value.isoformat() if hasattr(value, "isoformat")
                else value if value is None or isinstance(value, (str, int, float, bool))
                else str(value)
            )
            for key, value in row.items()
        }
        for row in result.rows
    ]
    return sha256_bytes(canonical_json(normalized).encode("utf-8"))


def _job(result: object) -> dict[str, int | str]:
    return {
        "job_id": result.job_id,
        "bytes_processed": result.bytes_processed,
        "bytes_billed": result.bytes_billed,
    }


if __name__ == "__main__":
    raise SystemExit(main())
