"""Local extraction orchestration; no warehouse or publication operations."""

from __future__ import annotations

import csv
import json
import logging
import re
import shutil
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable

from . import cbk, nasa
from .config import Location, Settings
from .http_client import BoundedHttpClient
from .io_utils import (
    atomic_write_json_once,
    atomic_write_once,
    canonical_json,
    identity,
    sha256_bytes,
    sha256_file,
)
from .manifest import Manifest, ReusableBatch


def configure_logging(root: Path) -> logging.Logger:
    logger = logging.getLogger("kenya_economic_data")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    log_path = root / "logs" / "extraction.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def extract_cbk(
    settings: Settings,
    manifest: Manifest,
    *,
    start_date: date,
    end_date: date,
    refresh: bool,
    input_path: Path | None = None,
) -> dict[str, Any]:
    logger = configure_logging(settings.project_root)
    source_path = (input_path or settings.cbk_raw_path).resolve()
    scope = {
        "source": "cbk",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency_labels": list(settings.cbk_currencies),
        "rate_type": "indicative_opening_mean_buy_sell",
        "quotation": "KES per one foreign currency unit",
        "contract_version": "cbk-v1",
    }
    scope_id = identity("scope", scope)
    manifest.ensure_scope(scope_id, "cbk", scope)
    attempt_id = manifest.start_attempt(scope_id, {"refresh": refresh})
    started = time.monotonic()
    try:
        reusable = manifest.latest_candidate(scope_id)
        if reusable is not None and not refresh:
            valid, failures = manifest.verify_batch(reusable.batch_id)
            if not valid:
                raise RuntimeError("completed batch artifact verification failed: " + "; ".join(failures))
            elapsed = time.monotonic() - started
            manifest.finish_attempt(
                attempt_id, status="reused", elapsed_seconds=elapsed, request_count=0,
                batch_id=reusable.batch_id,
                details={"observation_sha256": reusable.observation_sha256},
            )
            logger.info("source=cbk scope=%s attempt=%s outcome=reused batch=%s", scope_id, attempt_id, reusable.batch_id)
            return _summary(reusable, attempt_id, "reused", 0, elapsed)

        if not source_path.is_file():
            raise FileNotFoundError(f"verified CBK input is missing: {source_path}")
        raw_bytes = source_path.read_bytes()
        content_sha256 = sha256_bytes(raw_bytes)
        if input_path is None and content_sha256 != settings.cbk_verified_sha256:
            raise RuntimeError(
                "default CBK input does not match the Phase 0 verified checksum"
            )
        raw_snapshot = (
            settings.project_root / "data" / "raw" / "cbk" / scope_id /
            f"{content_sha256}.csv"
        )
        atomic_write_once(raw_snapshot, raw_bytes)
        batch_id = identity("batch", {"scope_id": scope_id, "content_sha256": content_sha256})
        retrieval_date = datetime.fromtimestamp(source_path.stat().st_mtime, UTC).date()
        result = cbk.process_cbk(
            raw_bytes,
            start_date=start_date,
            end_date=end_date,
            selected_labels=settings.cbk_currencies,
            retrieval_date=retrieval_date,
            batch_id=batch_id,
            snapshot_sha256=content_sha256,
        )
        if result.blocked:
            failed_dir = settings.project_root / "data" / "processed" / "failed" / attempt_id
            rejected_path = failed_dir / "rejected.csv"
            reconciliation_path = failed_dir / "reconciliation.json"
            atomic_write_once(rejected_path, _csv_bytes(result.rejected, cbk.REJECTED_FIELDS))
            atomic_write_json_once(reconciliation_path, result.reconciliation)
            raise RuntimeError(
                "CBK candidate blocked by conflicts, incomplete publication dates, or reconciliation failure"
            )
        return _complete_batch(
            settings=settings,
            manifest=manifest,
            attempt_id=attempt_id,
            source="cbk",
            scope_id=scope_id,
            batch_id=batch_id,
            content_sha256=content_sha256,
            observation_rows=result.accepted,
            observation_hash_fields=[
                "observation_date", "currency_code", "source_currency_label", "rate_type",
                "base_currency", "quote_currency", "unit_multiplier", "mean_rate",
                "buy_rate", "sell_rate", "source",
            ],
            accepted_fields=cbk.ACCEPTED_FIELDS,
            rejected_rows=result.rejected,
            rejected_fields=cbk.REJECTED_FIELDS,
            reconciliation=result.reconciliation,
            snapshot_refs=[{
                "location": None,
                "path": str(raw_snapshot),
                "sha256": content_sha256,
                "source_url": settings.cbk_source_url,
                "upstream_selection": "none; full historical file filtered locally",
            }],
            extra_artifacts=[],
            started=started,
            request_count=0,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        manifest.finish_attempt(
            attempt_id, status="failed", elapsed_seconds=elapsed, request_count=0,
            error=sanitize_error(exc),
        )
        logger.error("source=cbk scope=%s attempt=%s elapsed=%.3fs outcome=failed error=%s", scope_id, attempt_id, elapsed, sanitize_error(exc))
        raise


def extract_nasa(
    settings: Settings,
    manifest: Manifest,
    *,
    start_date: date,
    end_date: date,
    locations: list[Location],
    refresh: bool,
) -> dict[str, Any]:
    logger = configure_logging(settings.project_root)
    scope = {
        "source": "nasa_power",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "locations": [
            {"name": item.name, "latitude": item.latitude, "longitude": item.longitude}
            for item in sorted(locations, key=lambda item: item.name)
        ],
        "parameters": list(settings.nasa_parameters),
        "community": settings.nasa_community,
        "time_standard": settings.nasa_time_standard,
        "format": "JSON",
        "contract_version": "nasa-power-v1",
    }
    scope_id = identity("scope", scope)
    manifest.ensure_scope(scope_id, "nasa_power", scope)
    attempt_id = manifest.start_attempt(scope_id, {"refresh": refresh})
    started = time.monotonic()
    request_count = 0
    client = BoundedHttpClient(
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=settings.read_timeout_seconds,
        max_attempts=settings.max_attempts,
        retry_after_cap=settings.retry_after_cap_seconds,
        logger=logger,
    )
    try:
        reusable = manifest.latest_candidate(scope_id)
        if reusable is not None and not refresh:
            valid, failures = manifest.verify_batch(reusable.batch_id)
            if not valid:
                raise RuntimeError("completed batch artifact verification failed: " + "; ".join(failures))
            elapsed = time.monotonic() - started
            manifest.finish_attempt(
                attempt_id, status="reused", elapsed_seconds=elapsed, request_count=0,
                batch_id=reusable.batch_id,
                details={"observation_sha256": reusable.observation_sha256},
            )
            logger.info("source=nasa_power scope=%s attempt=%s outcome=reused batch=%s", scope_id, attempt_id, reusable.batch_id)
            return _summary(reusable, attempt_id, "reused", 0, elapsed)

        downloads: list[dict[str, Any]] = []
        for location in locations:
            params = nasa.request_parameters(
                location, start_date, end_date,
                community=settings.nasa_community,
                time_standard=settings.nasa_time_standard,
                parameters=settings.nasa_parameters,
            )
            result = client.get(
                settings.nasa_endpoint, params, source="nasa_power",
                scope_id=f"{scope_id}:{location.name}",
            )
            request_count += result.attempts
            if "application/json" not in result.content_type.lower():
                raise ValueError(f"unexpected NASA content type for {location.name}: {result.content_type}")
            checksum = sha256_bytes(result.body)
            raw_path = (
                settings.project_root / "data" / "raw" / "nasa_power" / scope_id /
                location.name.lower() / f"{checksum}.json"
            )
            atomic_write_once(raw_path, result.body)
            retrieved_at = datetime.now(UTC).isoformat(timespec="milliseconds")
            metadata = {
                "endpoint": settings.nasa_endpoint,
                "request_parameters": params,
                "retrieved_at": retrieved_at,
                "http_status": result.status,
                "content_type": result.content_type,
                "sha256": checksum,
                "http_attempts": result.attempts,
                "elapsed_seconds": round(result.elapsed_seconds, 6),
                "source_metadata": _nasa_source_metadata(result.body),
            }
            metadata_path = raw_path.with_name(f"{checksum}.{attempt_id}.metadata.json")
            atomic_write_json_once(metadata_path, metadata)
            downloads.append(
                {
                    "location": location,
                    "params": params,
                    "body": result.body,
                    "checksum": checksum,
                    "raw_path": raw_path,
                    "metadata_path": metadata_path,
                    "metadata": metadata,
                }
            )

        content_sha256 = sha256_bytes(
            canonical_json({item["location"].name: item["checksum"] for item in downloads}).encode("utf-8")
        )
        batch_id = identity("batch", {"scope_id": scope_id, "content_sha256": content_sha256})
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        location_reconciliations: list[dict[str, Any]] = []
        source_metadata: dict[str, Any] = {}
        blocked_locations: list[str] = []
        for item in downloads:
            parsed = nasa.process_nasa_location(
                item["body"], location=item["location"], start_date=start_date,
                end_date=end_date, missing_value=settings.nasa_missing_value,
                batch_id=batch_id, snapshot_sha256=item["checksum"],
            )
            accepted.extend(parsed.accepted)
            rejected.extend(parsed.rejected)
            location_reconciliations.append(parsed.reconciliation)
            source_metadata[item["location"].name] = parsed.source_metadata
            if parsed.blocked:
                blocked_locations.append(item["location"].name)
        accepted.sort(key=lambda row: (row["observation_date"], row["location_name"]))
        rejected.sort(key=lambda row: (row["observation_date"], row["location_name"]))
        expected_rows = (end_date - start_date).days + 1
        expected_rows *= len(locations)
        reconciliation = {
            "expected_observation_row_count": expected_rows,
            "accepted_observation_count": len(accepted),
            "rejected_observation_row_count": len(rejected),
            "missing_measurement_field_count": sum(item["missing_measurement_field_count"] for item in location_reconciliations),
            "invalid_measurement_field_count": sum(item["invalid_measurement_field_count"] for item in location_reconciliations),
            "location_results": location_reconciliations,
            "source_metadata": source_metadata,
            "warehouse_loaded_count": None,
            "published_count": None,
            "warehouse_counts_verified": False,
            "equation": {
                "left": expected_rows,
                "right": len(accepted) + len(rejected),
                "passed": expected_rows == len(accepted) + len(rejected),
                "formula": "expected rows = accepted rows + rejected rows",
            },
            "quality_policy": {
                "complete_dates": "Every requested UTC date requires both T2M and PRECTOTCORR for every selected point.",
                "missing": "The documented -999 fill value becomes null and blocks readiness; it is never converted to zero.",
                "bounds": "T2M must be finite and within -90..60 C; PRECTOTCORR must be finite and within 0..2000 mm/day.",
                "freshness": "Historical observation dates are not compared to today's date for failure; retrieval time is operational metadata only.",
            },
        }
        if blocked_locations or not reconciliation["equation"]["passed"]:
            failed_dir = settings.project_root / "data" / "processed" / "failed" / attempt_id
            atomic_write_once(failed_dir / "rejected.csv", _csv_bytes(rejected, nasa.REJECTED_FIELDS))
            atomic_write_json_once(failed_dir / "reconciliation.json", reconciliation)
            raise RuntimeError(f"NASA candidate blocked for: {', '.join(blocked_locations)}")
        extra_artifacts = [
            ("retrieval_metadata", item["metadata_path"], sha256_file(item["metadata_path"]))
            for item in downloads
        ]
        return _complete_batch(
            settings=settings,
            manifest=manifest,
            attempt_id=attempt_id,
            source="nasa_power",
            scope_id=scope_id,
            batch_id=batch_id,
            content_sha256=content_sha256,
            observation_rows=accepted,
            observation_hash_fields=[
                "observation_date", "location_name", "latitude", "longitude",
                "time_standard", "t2m_c", "prectotcorr_mm_day", "source",
            ],
            accepted_fields=nasa.ACCEPTED_FIELDS,
            rejected_rows=rejected,
            rejected_fields=nasa.REJECTED_FIELDS,
            reconciliation=reconciliation,
            snapshot_refs=[{
                "location": item["location"].name,
                "path": str(item["raw_path"]),
                "sha256": item["checksum"],
                "metadata_path": str(item["metadata_path"]),
                "endpoint": settings.nasa_endpoint,
                "request_parameters": item["params"],
            } for item in downloads],
            extra_artifacts=extra_artifacts,
            started=started,
            request_count=request_count,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        manifest.finish_attempt(
            attempt_id, status="failed", elapsed_seconds=elapsed,
            request_count=request_count, error=sanitize_error(exc),
        )
        logger.error("source=nasa_power scope=%s attempt=%s elapsed=%.3fs outcome=failed error=%s", scope_id, attempt_id, elapsed, sanitize_error(exc))
        raise


def _complete_batch(
    *,
    settings: Settings,
    manifest: Manifest,
    attempt_id: str,
    source: str,
    scope_id: str,
    batch_id: str,
    content_sha256: str,
    observation_rows: list[dict[str, Any]],
    observation_hash_fields: list[str],
    accepted_fields: list[str],
    rejected_rows: list[dict[str, Any]],
    rejected_fields: list[str],
    reconciliation: dict[str, Any],
    snapshot_refs: list[dict[str, Any]],
    extra_artifacts: list[tuple[str, Path, str]],
    started: float,
    request_count: int,
) -> dict[str, Any]:
    observation_content = [
        {field: row[field] for field in observation_hash_fields} for row in observation_rows
    ]
    observation_sha256 = sha256_bytes(canonical_json(observation_content).encode("utf-8"))
    output_dir = settings.project_root / "data" / "processed" / source / scope_id / batch_id
    accepted_path = output_dir / "accepted.csv"
    rejected_path = output_dir / "rejected.csv"
    reconciliation_path = output_dir / "reconciliation.json"
    status_path = output_dir / "candidate_status.json"
    atomic_write_once(accepted_path, _csv_bytes(observation_rows, accepted_fields))
    atomic_write_once(rejected_path, _csv_bytes(rejected_rows, rejected_fields))
    atomic_write_json_once(reconciliation_path, reconciliation)
    counts = {
        "accepted_observation_count": len(observation_rows),
        "rejected_artifact_row_count": len(rejected_rows),
    }
    status = {
        "candidate_ready": True,
        "source": source,
        "scope_id": scope_id,
        "batch_id": batch_id,
        "content_sha256": content_sha256,
        "observation_sha256": observation_sha256,
        "counts": counts,
        "warehouse_loaded_count": None,
        "published_count": None,
    }
    # Readiness is written last, after every validation and candidate artifact succeeds.
    atomic_write_json_once(status_path, status)
    artifacts: list[tuple[str, Path, str]] = [
        ("raw_snapshot", Path(item["path"]), item["sha256"]) for item in snapshot_refs
    ]
    artifacts.extend(
        [
            ("accepted", accepted_path, sha256_file(accepted_path)),
            ("rejected", rejected_path, sha256_file(rejected_path)),
            ("reconciliation", reconciliation_path, sha256_file(reconciliation_path)),
            ("candidate_status", status_path, sha256_file(status_path)),
        ]
    )
    artifacts.extend(extra_artifacts)
    batch = ReusableBatch(
        batch_id=batch_id, source=source, scope_id=scope_id,
        content_sha256=content_sha256, observation_sha256=observation_sha256,
        snapshot_refs=snapshot_refs, accepted_path=accepted_path,
        rejected_path=rejected_path, reconciliation_path=reconciliation_path,
        status_path=status_path, counts=counts,
    )
    manifest.record_batch(batch, artifacts)
    elapsed = time.monotonic() - started
    manifest.finish_attempt(
        attempt_id, status="completed", elapsed_seconds=elapsed,
        request_count=request_count, batch_id=batch_id,
        details={"observation_sha256": observation_sha256},
    )
    return _summary(batch, attempt_id, "completed", request_count, elapsed)


def _summary(
    batch: ReusableBatch,
    attempt_id: str,
    attempt_status: str,
    request_count: int,
    elapsed: float,
) -> dict[str, Any]:
    return {
        "source": batch.source,
        "scope_id": batch.scope_id,
        "batch_id": batch.batch_id,
        "attempt_id": attempt_id,
        "attempt_status": attempt_status,
        "candidate_ready": True,
        "content_sha256": batch.content_sha256,
        "observation_sha256": batch.observation_sha256,
        "accepted_path": str(batch.accepted_path),
        "reconciliation_path": str(batch.reconciliation_path),
        "request_count": request_count,
        "elapsed_seconds": round(elapsed, 6),
        "counts": batch.counts,
    }


def _csv_bytes(rows: Iterable[dict[str, Any]], fields: list[str]) -> bytes:
    stream = __import__("io").StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def sanitize_error(error: Exception) -> str:
    text = re.sub(r"\s+", " ", f"{type(error).__name__}: {error}").strip()
    text = re.sub(r"(?i)(bearer|token|password|secret)\s*[=:]\s*\S+", r"\1=[REDACTED]", text)
    return text[:500]


def _nasa_source_metadata(raw_bytes: bytes) -> dict[str, Any]:
    payload = json.loads(raw_bytes.decode("utf-8"))
    header = payload.get("header", {})
    definitions = payload.get("parameters", {})
    return {
        "api": header.get("api"),
        "sources": header.get("sources"),
        "fill_value": header.get("fill_value"),
        "time_standard": header.get("time_standard"),
        "coordinates_returned": payload.get("geometry", {}).get("coordinates"),
        "units": {
            name: definitions.get(name, {}).get("units")
            for name in ("T2M", "PRECTOTCORR")
        },
    }

