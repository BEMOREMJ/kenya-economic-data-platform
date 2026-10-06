from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kenya_economic_data.manifest import Manifest
from kenya_economic_data import cli
from kenya_economic_data.orchestration import (
    PipelineLock,
    _assert_candidate_namespace,
    _input_profile,
    _assert_publication_gates,
    _reconcile_interrupted_publications,
)
from kenya_economic_data.release import canonical_view_sql


class CurrentReleaseGateway:
    def __init__(self, release_id: str | None) -> None:
        self.release_id = release_id

    def current_release_id(self, trusted_dataset: str) -> str | None:
        return self.release_id


def _run_and_release(manifest: Manifest, release_id: str) -> tuple[str, str]:
    run_id = "run_test"
    manifest.start_pipeline_run(
        run_id=run_id, scope={"test": True}, selected_batches={"cbk": "batch_test"},
        model_fingerprint="model", config_fingerprint="config",
    )
    manifest.record_release(
        release_id=release_id, run_id=run_id, project_id="project",
        location="US", release_dataset="kep_release_test",
        exchange_table="exchange_monthly", weather_table="weather_monthly",
        status="validated", previous_release_id=None, gate_evidence={}, counts={}, coverage={},
    )
    attempt = manifest.start_publication_attempt(run_id, release_id, None)
    return run_id, attempt


def test_pipeline_lock_prevents_concurrent_execution(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lock"
    with PipelineLock(path, "run_one"):
        with pytest.raises(RuntimeError, match="already held"):
            with PipelineLock(path, "run_two"):
                pass
    assert not path.exists()


def test_recovery_treats_current_bigquery_release_as_authoritative(tmp_path: Path) -> None:
    release_id = "release_authoritative"
    with Manifest(tmp_path / "manifest.sqlite3") as manifest:
        _, attempt = _run_and_release(manifest, release_id)
        _reconcile_interrupted_publications(
            manifest, CurrentReleaseGateway(release_id), "kep_trusted_v1"
        )
        publication = manifest.connection.execute(
            "SELECT status,current_release_id FROM publication_attempts WHERE publication_attempt_id=?",
            (attempt,),
        ).fetchone()
        release = manifest.release(release_id)
    assert publication["status"] == "published_recovered"
    assert publication["current_release_id"] == release_id
    assert release["status"] == "published"


def test_failed_gate_does_not_call_publication() -> None:
    publish = Mock()
    evidence = {
        "ingestion": {"cbk": True, "nasa_power": True},
        "loads": {"cbk": 176, "nasa_power": 276},
        "dbt": {"test_pass_count": 39, "model_fingerprint": "model"},
        "reconciliation": {"rows": [{}, {}]},
        "model_fingerprint": "model",
        "expected": {
            "cbk": {"observations": 177, "reporting_rows": 9},
            "weather": {"observations": 276, "reporting_rows": 9},
        },
    }
    with pytest.raises(RuntimeError, match="load counts"):
        _assert_publication_gates(evidence)
        publish()
    publish.assert_not_called()


def test_mismatched_validation_evidence_refuses_publication() -> None:
    evidence = {
        "ingestion": {"cbk": True, "nasa_power": True},
        "loads": {"cbk": 177, "nasa_power": 276},
        "dbt": {"test_pass_count": 39, "model_fingerprint": "stale-model"},
        "reconciliation": {"rows": [{}, {}]},
        "model_fingerprint": "current-model",
        "expected": {
            "cbk": {"observations": 177, "reporting_rows": 9},
            "weather": {"observations": 276, "reporting_rows": 9},
        },
    }
    with pytest.raises(RuntimeError, match="model fingerprint mismatch"):
        _assert_publication_gates(evidence)


def test_canonical_switch_is_one_view_over_frozen_domain_tables() -> None:
    sql = canonical_view_sql(
        project_id="project", trusted_dataset="kep_trusted_v1",
        release_dataset="kep_release_abc",
    )
    normalized = " ".join(sql.lower().split())
    assert normalized.count("create or replace view") == 1
    assert "kep_trusted_v1.canonical_release" in normalized
    assert "kep_release_abc.exchange_monthly" in normalized
    assert "kep_release_abc.weather_monthly" in normalized
    assert "merge " not in normalized
    assert "insert " not in normalized
    assert "update " not in normalized


def test_changed_inputs_require_new_candidate_namespace(tmp_path: Path) -> None:
    with Manifest(tmp_path / "manifest.sqlite3") as manifest:
        run_id = "run_published"
        manifest.start_pipeline_run(
            run_id=run_id,
            scope={"candidate_dataset": "kep_candidate_v1"},
            selected_batches={"cbk": "old", "nasa_power": "weather"},
            model_fingerprint="model", config_fingerprint="config",
        )
        manifest.record_release(
            release_id="release_published", run_id=run_id, project_id="project",
            location="US", release_dataset="kep_release_old",
            exchange_table="exchange_monthly", weather_table="weather_monthly",
            status="validated", previous_release_id=None, gate_evidence={}, counts={}, coverage={},
        )
        attempt = manifest.start_publication_attempt(run_id, "release_published", None)
        manifest.finish_publication_attempt(
            attempt, status="published", current_release_id="release_published"
        )
        with pytest.raises(RuntimeError, match="new candidate dataset"):
            _assert_candidate_namespace(
                manifest, candidate_dataset="kep_candidate_v1",
                selected_batches={"cbk": "new", "nasa_power": "weather"},
                model_fingerprint="model",
            )
        _assert_candidate_namespace(
            manifest, candidate_dataset="kep_candidate_backfill_v1",
            selected_batches={"cbk": "new", "nasa_power": "weather"},
            model_fingerprint="model",
        )


def test_export_retry_calls_only_export_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_id = "release_current"
    manifest_path = tmp_path / "data" / "manifests" / "ingestion.sqlite3"
    with Manifest(manifest_path) as manifest:
        run_id, attempt = _run_and_release(manifest, release_id)
        manifest.finish_publication_attempt(
            attempt, status="published", current_release_id=release_id
        )
        manifest.finish_pipeline_run(run_id, status="published_export_failed")

    gateway = CurrentReleaseGateway(release_id)
    export = Mock(return_value={"exchange": {"row_count": 9}, "weather": {"row_count": 9}})
    monkeypatch.setattr(cli, "ReleaseGateway", lambda *_: gateway)
    monkeypatch.setattr(cli, "export_release_reports", export)

    result = cli._retry_export(
        Namespace(
            project="project", location="US", trusted_dataset="kep_trusted_v1",
            release_id=release_id,
        ),
        SimpleNamespace(project_root=tmp_path),
    )

    assert result == 0
    export.assert_called_once()
    assert export.call_args.kwargs["release_id"] == release_id


def test_input_profile_supports_asymmetric_weather_backfill(tmp_path: Path) -> None:
    cbk = tmp_path / "cbk.csv"
    cbk.write_text(
        "observation_date,currency_code\n2023-10-02,USD\n2023-10-02,EUR\n",
        encoding="utf-8",
    )
    weather = tmp_path / "weather.csv"
    weather.write_text(
        "observation_date,location_name\n"
        "2023-09-01,Nairobi\n2023-09-02,Nairobi\n2023-10-01,Nairobi\n"
        "2023-10-01,Mombasa\n",
        encoding="utf-8",
    )

    profile = _input_profile(cbk, weather)

    assert profile["expected"] == {
        "cbk": {"observations": 2, "reporting_rows": 2},
        "weather": {"observations": 4, "reporting_rows": 3},
    }
    assert profile["coverage"]["start_date"] == "2023-09-01"
    assert profile["coverage"]["exchange"]["start_date"] == "2023-10-02"
    assert profile["coverage"]["weather_by_location"]["Nairobi"] == {
        "start_date": "2023-09-01", "end_date": "2023-10-01",
        "observation_count": 3,
    }
