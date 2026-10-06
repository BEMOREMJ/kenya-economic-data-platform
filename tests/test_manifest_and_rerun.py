from datetime import date
from pathlib import Path

import pytest

from kenya_economic_data.config import Settings
from kenya_economic_data.io_utils import sha256_file
from kenya_economic_data.manifest import Manifest
from kenya_economic_data.pipeline import extract_cbk


FIXTURES = Path(__file__).parent / "fixtures"


def _settings(root: Path, raw_path: Path) -> Settings:
    return Settings(
        project_root=root,
        cbk_currencies=("US DOLLAR", "STG POUND", "EURO"),
        cbk_raw_path=raw_path,
        cbk_source_url="https://example.test/synthetic.csv",
        cbk_verified_sha256=sha256_file(raw_path),
        nasa_endpoint="https://example.test/nasa",
        nasa_community="AG",
        nasa_time_standard="UTC",
        nasa_parameters=("T2M", "PRECTOTCORR"),
        nasa_missing_value=-999.0,
        locations={},
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        retry_after_cap_seconds=1,
        max_attempts=1,
        max_window_days=366,
    )


def test_completed_batch_is_reused_and_failed_refresh_does_not_replace_it(tmp_path: Path) -> None:
    valid_path = FIXTURES / "synthetic_cbk_duplicates.csv"
    conflict_path = FIXTURES / "synthetic_cbk_conflict.csv"
    settings = _settings(tmp_path, valid_path)
    with Manifest(tmp_path / "data" / "manifests" / "ingestion.sqlite3") as manifest:
        first = extract_cbk(
            settings, manifest, start_date=date(2023, 10, 1),
            end_date=date(2023, 12, 31), refresh=False,
        )
        reused = extract_cbk(
            settings, manifest, start_date=date(2023, 10, 1),
            end_date=date(2023, 12, 31), refresh=False,
        )
        with pytest.raises(RuntimeError, match="candidate blocked"):
            extract_cbk(
                settings, manifest, start_date=date(2023, 10, 1),
                end_date=date(2023, 12, 31), refresh=True, input_path=conflict_path,
            )
        recovered = extract_cbk(
            settings, manifest, start_date=date(2023, 10, 1),
            end_date=date(2023, 12, 31), refresh=False,
        )
        attempts = manifest.attempts_for_scope(first["scope_id"])

    assert first["attempt_status"] == "completed"
    assert reused["attempt_status"] == "reused"
    assert reused["request_count"] == 0
    assert first["observation_sha256"] == reused["observation_sha256"]
    assert recovered["attempt_status"] == "reused"
    assert recovered["batch_id"] == first["batch_id"]
    assert [row["status"] for row in attempts] == ["completed", "reused", "failed", "reused"]


def test_corrupt_completed_artifact_fails_clearly(tmp_path: Path) -> None:
    valid_path = FIXTURES / "synthetic_cbk_duplicates.csv"
    settings = _settings(tmp_path, valid_path)
    with Manifest(tmp_path / "data" / "manifests" / "ingestion.sqlite3") as manifest:
        first = extract_cbk(
            settings, manifest, start_date=date(2023, 10, 1),
            end_date=date(2023, 12, 31), refresh=False,
        )
        Path(first["accepted_path"]).write_text("corrupt", encoding="utf-8")
        with pytest.raises(RuntimeError, match="artifact verification failed"):
            extract_cbk(
                settings, manifest, start_date=date(2023, 10, 1),
                end_date=date(2023, 12, 31), refresh=False,
            )

