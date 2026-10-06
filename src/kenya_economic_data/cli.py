"""Command-line interface for bounded local extraction."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import Settings, load_settings
from .backfill import compose_backfill
from .manifest import Manifest
from .orchestration import export_release_reports, health_report, operate, rollback_release
from .pipeline import extract_cbk, extract_nasa, sanitize_error
from .release import ReleaseGateway
from .warehouse import BigQueryGateway, load_candidate_batch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kenya-econ")
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract", help="extract validated local candidates")
    extract.add_argument("--source", choices=("cbk", "nasa", "all"), required=True)
    extract.add_argument("--start-date", required=True, help="inclusive ISO date")
    extract.add_argument("--end-date", required=True, help="inclusive ISO date")
    extract.add_argument("--locations", nargs="+", help="configured NASA location names")
    extract.add_argument("--refresh", action="store_true", help="re-read/retrieve source even if a verified batch exists")
    extract.add_argument("--cbk-input", type=Path, help="local official CBK snapshot; defaults to verified Phase 0 file")
    extract.add_argument("--config", type=Path, default=Path("config/settings.example.toml"))
    load = subparsers.add_parser("load", help="load immutable candidate batches to BigQuery")
    load.add_argument("--source", choices=("cbk", "nasa", "all"), required=True)
    load.add_argument("--project", required=True, help="explicit Google Cloud project ID")
    load.add_argument("--location", required=True, help="explicit BigQuery location")
    load.add_argument("--dataset", required=True, help="existing owned candidate dataset")
    load.add_argument("--batch-id", help="specific immutable batch; defaults to latest ready batch")
    load.add_argument("--config", type=Path, default=Path("config/settings.example.toml"))
    run = subparsers.add_parser("operate", help="run the gated local Phase 3 pipeline")
    run.add_argument("--project", required=True)
    run.add_argument("--location", default="US")
    run.add_argument("--candidate-dataset", required=True)
    run.add_argument("--trusted-dataset", required=True)
    run.add_argument("--start-date", required=True)
    run.add_argument("--end-date", required=True)
    run.add_argument("--locations", nargs="+", required=True)
    run.add_argument("--cbk-batch-id", help="explicit verified effective CBK input")
    run.add_argument("--nasa-batch-id", help="explicit verified effective NASA input")
    run.add_argument("--profiles-dir", type=Path, default=Path("config"))
    run.add_argument("--config", type=Path, default=Path("config/settings.example.toml"))
    backfill = subparsers.add_parser("compose-backfill", help="compose explicit effective backfill inputs")
    backfill.add_argument("--source", choices=("cbk", "nasa"), required=True)
    backfill.add_argument("--baseline-batch-id", required=True)
    backfill.add_argument("--replacement-batch-id", required=True)
    backfill.add_argument("--start-date", required=True)
    backfill.add_argument("--end-date", required=True)
    backfill.add_argument("--selections", nargs="+", required=True)
    backfill.add_argument("--config", type=Path, default=Path("config/settings.example.toml"))
    health = subparsers.add_parser("health", help="report latest attempt and published release health")
    health.add_argument("--project", required=True)
    health.add_argument("--location", default="US")
    health.add_argument("--trusted-dataset", required=True)
    health.add_argument("--config", type=Path, default=Path("config/settings.example.toml"))
    rollback = subparsers.add_parser("rollback", help="switch the canonical view to the previous valid release")
    rollback.add_argument("--project", required=True)
    rollback.add_argument("--location", default="US")
    rollback.add_argument("--trusted-dataset", required=True)
    rollback.add_argument("--config", type=Path, default=Path("config/settings.example.toml"))
    retry_export = subparsers.add_parser("retry-export", help="retry local exports for the current release")
    retry_export.add_argument("--project", required=True)
    retry_export.add_argument("--location", default="US")
    retry_export.add_argument("--trusted-dataset", required=True)
    retry_export.add_argument("--release-id")
    retry_export.add_argument("--config", type=Path, default=Path("config/settings.example.toml"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.command == "load":
            return _load(args, settings)
        if args.command == "operate":
            return _operate(args, settings)
        if args.command == "compose-backfill":
            return _compose_backfill(args, settings)
        if args.command == "health":
            return _health(args, settings)
        if args.command == "rollback":
            return _rollback(args, settings)
        if args.command == "retry-export":
            return _retry_export(args, settings)
        start_date = _iso_date(args.start_date, "start-date")
        end_date = _iso_date(args.end_date, "end-date")
        if start_date > end_date:
            raise ValueError("start-date must be on or before end-date")
        window_days = (end_date - start_date).days + 1
        if window_days > settings.max_window_days:
            raise ValueError(f"requested window exceeds {settings.max_window_days} days")
        selected_names = args.locations or list(settings.locations)
        unsupported = sorted(set(selected_names) - settings.locations.keys())
        if unsupported:
            raise ValueError(f"unsupported locations: {', '.join(unsupported)}")
        if len(selected_names) != len(set(selected_names)):
            raise ValueError("locations must not be repeated")
        locations = [settings.locations[name] for name in selected_names]
        if args.source == "cbk" and args.locations:
            raise ValueError("--locations applies only to nasa or all")

        manifest_path = settings.project_root / "data" / "manifests" / "ingestion.sqlite3"
        results: list[dict[str, object]] = []
        failures: list[dict[str, str]] = []
        with Manifest(manifest_path) as manifest:
            if args.source in {"cbk", "all"}:
                try:
                    results.append(
                        extract_cbk(
                            settings, manifest, start_date=start_date, end_date=end_date,
                            refresh=args.refresh, input_path=args.cbk_input,
                        )
                    )
                except Exception as exc:
                    failures.append({"source": "cbk", "error": sanitize_error(exc)})
            if args.source in {"nasa", "all"}:
                try:
                    results.append(
                        extract_nasa(
                            settings, manifest, start_date=start_date, end_date=end_date,
                            locations=locations, refresh=args.refresh,
                        )
                    )
                except Exception as exc:
                    failures.append({"source": "nasa_power", "error": sanitize_error(exc)})
        print(json.dumps({"results": results, "failures": failures}, indent=2, sort_keys=True))
        return 1 if failures else 0
    except Exception as exc:
        print(json.dumps({"error": sanitize_error(exc)}, indent=2), file=sys.stderr)
        return 2


def _load(args: argparse.Namespace, settings: Settings) -> int:
    if args.batch_id and args.source == "all":
        raise ValueError("--batch-id requires a single --source")
    if not args.dataset.startswith("kep_"):
        raise ValueError("candidate dataset must use the kep_ prefix")
    if args.location.upper() != "US":
        raise ValueError("Phase 2 candidate location must be US")
    manifest_path = settings.project_root / "data" / "manifests" / "ingestion.sqlite3"
    gateway = BigQueryGateway(args.project, args.location)
    source_names = ["cbk", "nasa_power"] if args.source == "all" else [
        "nasa_power" if args.source == "nasa" else "cbk"
    ]
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    schemas = {
        "cbk": settings.project_root / "schemas" / "cbk_exchange_rates.json",
        "nasa_power": settings.project_root / "schemas" / "nasa_weather.json",
    }
    with Manifest(manifest_path) as manifest:
        for source in source_names:
            try:
                results.append(
                    load_candidate_batch(
                        manifest, gateway, source=source, project_id=args.project,
                        dataset_id=args.dataset, location=args.location,
                        schema_path=schemas[source], batch_id=args.batch_id,
                    )
                )
            except Exception as exc:
                failures.append({"source": source, "error": sanitize_error(exc)})
    print(json.dumps({"results": results, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


def _operate(args: argparse.Namespace, settings: Settings) -> int:
    start_date, end_date = _validated_dates(args.start_date, args.end_date, settings)
    unsupported = sorted(set(args.locations) - settings.locations.keys())
    if unsupported:
        raise ValueError(f"unsupported locations: {', '.join(unsupported)}")
    if len(args.locations) != len(set(args.locations)):
        raise ValueError("locations must not be repeated")
    result = operate(
        settings, project_id=args.project, location=args.location,
        candidate_dataset=args.candidate_dataset, trusted_dataset=args.trusted_dataset,
        start_date=start_date, end_date=end_date,
        location_names=tuple(args.locations), profiles_dir=args.profiles_dir,
        cbk_batch_id=args.cbk_batch_id, nasa_batch_id=args.nasa_batch_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def _compose_backfill(args: argparse.Namespace, settings: Settings) -> int:
    start_date, end_date = _validated_dates(args.start_date, args.end_date, settings)
    source = "nasa_power" if args.source == "nasa" else "cbk"
    manifest_path = settings.project_root / "data" / "manifests" / "ingestion.sqlite3"
    with Manifest(manifest_path) as manifest:
        result = compose_backfill(
            manifest, source=source, baseline_batch_id=args.baseline_batch_id,
            replacement_batch_id=args.replacement_batch_id,
            start_date=start_date, end_date=end_date,
            selections=tuple(args.selections),
            output_root=settings.project_root / "data" / "processed" / "compositions",
        )
    print(json.dumps({
        "composition_id": result.composition_id, "source": result.source,
        "output_path": str(result.output_path),
        "reconciliation_path": str(result.reconciliation_path),
        "output_sha256": result.output_sha256, "counts": result.counts,
        "warehouse_operation": "full reconstruction required; no DML performed",
    }, indent=2, sort_keys=True))
    return 0


def _health(args: argparse.Namespace, settings: Settings) -> int:
    gateway = ReleaseGateway(args.project, args.location)
    manifest_path = settings.project_root / "data" / "manifests" / "ingestion.sqlite3"
    with Manifest(manifest_path) as manifest:
        report = health_report(manifest, gateway, trusted_dataset=args.trusted_dataset)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


def _rollback(args: argparse.Namespace, settings: Settings) -> int:
    gateway = ReleaseGateway(args.project, args.location)
    manifest_path = settings.project_root / "data" / "manifests" / "ingestion.sqlite3"
    with Manifest(manifest_path) as manifest:
        result = rollback_release(manifest, gateway, trusted_dataset=args.trusted_dataset)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def _retry_export(args: argparse.Namespace, settings: Settings) -> int:
    gateway = ReleaseGateway(args.project, args.location)
    manifest_path = settings.project_root / "data" / "manifests" / "ingestion.sqlite3"
    with Manifest(manifest_path) as manifest:
        current = gateway.current_release_id(args.trusted_dataset)
        release_id = args.release_id or current
        if release_id is None or release_id != current:
            raise RuntimeError("retry-export requires the current published release")
        release = manifest.release(release_id)
        if release is None:
            raise RuntimeError(f"release is missing from local manifest: {release_id}")
        coverage = json.loads(release["coverage_json"])
        result = export_release_reports(
            manifest, gateway, trusted_dataset=args.trusted_dataset,
            release_id=release_id,
            output_root=settings.project_root / "data" / "reports",
            coverage=coverage,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def _validated_dates(raw_start: str, raw_end: str, settings: Settings) -> tuple[date, date]:
    start_date = _iso_date(raw_start, "start-date")
    end_date = _iso_date(raw_end, "end-date")
    if start_date > end_date:
        raise ValueError("start-date must be on or before end-date")
    if (end_date - start_date).days + 1 > settings.max_window_days:
        raise ValueError(f"requested window exceeds {settings.max_window_days} days")
    return start_date, end_date


def _iso_date(raw: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != raw:
        raise ValueError(f"{label} must be zero-padded YYYY-MM-DD")
    return parsed

