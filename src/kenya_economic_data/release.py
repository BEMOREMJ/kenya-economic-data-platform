"""Frozen release construction, canonical publication, rollback, and health."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.api_core.exceptions import Conflict, NotFound
from google.cloud import bigquery

from .io_utils import canonical_json, sha256_bytes


MAXIMUM_BYTES_BILLED = 1_073_741_824
OWNER_LABEL = "kenya_economic_data_platform"


@dataclass(frozen=True)
class QueryEvidence:
    job_id: str
    bytes_processed: int
    bytes_billed: int
    rows: list[dict[str, Any]]


class ReleaseGateway:
    def __init__(self, project_id: str, location: str) -> None:
        self.project_id = project_id
        self.location = location
        self.client = bigquery.Client(project=project_id, location=location)

    def ensure_owned_dataset(self, dataset_id: str, phase: str) -> dict[str, Any]:
        reference = f"{self.project_id}.{dataset_id}"
        try:
            dataset = self.client.get_dataset(reference)
            created = False
        except NotFound:
            dataset = bigquery.Dataset(reference)
            dataset.location = self.location
            dataset.description = (
                f"Kenya Economic Data Platform {phase}; reproducible Sandbox state"
            )
            dataset.labels = {"kep_owner": OWNER_LABEL, "kep_phase": phase}
            dataset.default_table_expiration_ms = 5_184_000_000
            dataset.default_partition_expiration_ms = 5_184_000_000
            dataset = self.client.create_dataset(dataset, exists_ok=False)
            created = True
        labels = dataset.labels or {}
        if dataset.location.upper() != self.location.upper():
            raise RuntimeError(
                f"dataset location mismatch for {dataset_id}: {dataset.location}"
            )
        if labels.get("kep_owner") != OWNER_LABEL:
            raise RuntimeError(f"dataset ownership collision: {dataset_id}")
        return {
            "dataset_id": dataset_id,
            "created": created,
            "location": dataset.location,
            "labels": labels,
            "default_table_expiration_ms": dataset.default_table_expiration_ms,
        }

    def table_exists(self, table_ref: str) -> bool:
        try:
            self.client.get_table(table_ref)
            return True
        except NotFound:
            return False

    def query(self, sql: str, *, job_prefix: str) -> QueryEvidence:
        config = bigquery.QueryJobConfig(
            use_legacy_sql=False,
            maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        )
        job = self.client.query(
            sql,
            location=self.location,
            job_id_prefix=job_prefix,
            job_config=config,
        )
        rows = [dict(row.items()) for row in job.result(timeout=180)]
        return QueryEvidence(
            job_id=job.job_id,
            bytes_processed=int(job.total_bytes_processed or 0),
            bytes_billed=int(job.total_bytes_billed or 0),
            rows=rows,
        )

    def current_release_id(self, trusted_dataset: str) -> str | None:
        view_ref = f"{self.project_id}.{trusted_dataset}.canonical_release"
        if not self.table_exists(view_ref):
            return None
        evidence = self.query(
            f"SELECT ARRAY_AGG(DISTINCT release_id) AS release_ids FROM `{view_ref}`",
            job_prefix="kep_current_release_",
        )
        values = evidence.rows[0]["release_ids"] if evidence.rows else []
        if not values:
            raise RuntimeError("canonical release view exists but returns no release ID")
        if len(values) != 1:
            raise RuntimeError(f"canonical release exposes multiple releases: {values}")
        return str(values[0])

    def relation_metadata(self, table_ref: str) -> dict[str, Any]:
        try:
            table = self.client.get_table(table_ref)
        except NotFound:
            return {"state": "expired_or_missing", "table_ref": table_ref}
        return {
            "state": "available",
            "table_ref": table_ref,
            "type": table.table_type,
            "rows": int(table.num_rows) if table.num_rows is not None else None,
            "bytes": int(table.num_bytes) if table.num_bytes is not None else None,
            "created": _timestamp(table.created),
            "modified": _timestamp(table.modified),
            "expires": _timestamp(table.expires),
        }

    def view_query(self, table_ref: str) -> str | None:
        try:
            table = self.client.get_table(table_ref)
        except NotFound:
            return None
        return table.view_query


def freeze_release_tables(
    gateway: ReleaseGateway,
    *,
    candidate_dataset: str,
    release_dataset: str,
    release_id: str,
    cbk_batch_id: str,
    nasa_batch_id: str,
    expected: dict[str, dict[str, int]],
) -> dict[str, Any]:
    project = gateway.project_id
    exchange_ref = f"{project}.{release_dataset}.exchange_monthly"
    weather_ref = f"{project}.{release_dataset}.weather_monthly"
    jobs: list[dict[str, Any]] = []
    if not gateway.table_exists(exchange_ref):
        sql = f"""
        CREATE TABLE `{exchange_ref}`
        OPTIONS(description='Immutable candidate release exchange monthly rows') AS
        SELECT
          '{release_id}' AS release_id,
          '{cbk_batch_id}' AS source_batch_id,
          currency_code,
          month_start,
          mean_published_daily_mean_rate_kes_per_foreign_unit,
          first_available_publication_date,
          last_available_publication_date,
          publication_observation_count
        FROM `{project}.{candidate_dataset}.mart_exchange_rate_monthly`
        """
        evidence = gateway.query(sql, job_prefix=f"kep_freeze_fx_{release_id[-8:]}_")
        jobs.append(_job_dict(evidence))
    if not gateway.table_exists(weather_ref):
        sql = f"""
        CREATE TABLE `{weather_ref}`
        OPTIONS(description='Immutable candidate release weather monthly rows') AS
        SELECT
          '{release_id}' AS release_id,
          '{nasa_batch_id}' AS source_batch_id,
          location_id,
          month_start,
          mean_daily_temperature_c,
          sum_daily_precipitation_mm,
          observed_day_count,
          expected_day_count,
          missing_precipitation_day_count
        FROM `{project}.{candidate_dataset}.mart_weather_monthly`
        """
        evidence = gateway.query(sql, job_prefix=f"kep_freeze_wx_{release_id[-8:]}_")
        jobs.append(_job_dict(evidence))

    validation_sql = f"""
    SELECT 'exchange' AS domain, COUNT(*) AS row_count,
      COUNT(DISTINCT CONCAT(currency_code, '|', CAST(month_start AS STRING))) AS unique_keys,
      MIN(month_start) AS min_month, MAX(month_start) AS max_month,
      COUNTIF(release_id != '{release_id}' OR source_batch_id != '{cbk_batch_id}') AS identity_errors,
      SUM(publication_observation_count) AS observation_count
    FROM `{exchange_ref}`
    UNION ALL
    SELECT 'weather', COUNT(*),
      COUNT(DISTINCT CONCAT(location_id, '|', CAST(month_start AS STRING))),
      MIN(month_start), MAX(month_start),
      COUNTIF(release_id != '{release_id}' OR source_batch_id != '{nasa_batch_id}'),
      SUM(observed_day_count)
    FROM `{weather_ref}`
    ORDER BY domain
    """
    validation = gateway.query(
        validation_sql, job_prefix=f"kep_validate_release_{release_id[-8:]}_"
    )
    by_domain = {str(row["domain"]): row for row in validation.rows}
    validation_expected = {
        "exchange": (
            expected["cbk"]["reporting_rows"], expected["cbk"]["observations"]
        ),
        "weather": (
            expected["weather"]["reporting_rows"], expected["weather"]["observations"]
        ),
    }
    for domain, (rows, observations) in validation_expected.items():
        result = by_domain.get(domain)
        if result is None:
            raise RuntimeError(f"release validation missing {domain}")
        if (
            int(result["row_count"]) != rows
            or int(result["unique_keys"]) != rows
            or int(result["identity_errors"]) != 0
            or int(result["observation_count"]) != observations
        ):
            raise RuntimeError(f"release validation failed for {domain}: {result}")
    return {
        "exchange_table": "exchange_monthly",
        "weather_table": "weather_monthly",
        "creation_jobs": jobs,
        "validation_job": _job_dict(validation),
        "validation_rows": [_json_safe(row) for row in validation.rows],
    }


def publish_canonical_view(
    gateway: ReleaseGateway,
    *,
    trusted_dataset: str,
    release_dataset: str,
    release_id: str,
) -> dict[str, Any]:
    project = gateway.project_id
    canonical_ref = f"{project}.{trusted_dataset}.canonical_release"
    previous_release_id = gateway.current_release_id(trusted_dataset)
    if previous_release_id == release_id:
        convenience_jobs = ensure_convenience_views(gateway, trusted_dataset=trusted_dataset)
        return {
            "canonical_view": canonical_ref,
            "previous_release_id": previous_release_id,
            "current_release_id": release_id,
            "switch_job": None,
            "convenience_jobs": convenience_jobs,
            "outcome": "reused",
        }
    sql = canonical_view_sql(
        project_id=project,
        trusted_dataset=trusted_dataset,
        release_dataset=release_dataset,
    )
    switched = gateway.query(sql, job_prefix=f"kep_publish_{release_id[-8:]}_")
    authoritative_release = gateway.current_release_id(trusted_dataset)
    if authoritative_release != release_id:
        raise RuntimeError(
            f"publication verification failed: expected {release_id}, got {authoritative_release}"
        )
    convenience_jobs = ensure_convenience_views(gateway, trusted_dataset=trusted_dataset)
    return {
        "canonical_view": canonical_ref,
        "previous_release_id": previous_release_id,
        "current_release_id": authoritative_release,
        "switch_job": _job_dict(switched),
        "convenience_jobs": convenience_jobs,
        "outcome": "switched",
    }


def canonical_view_sql(
    *, project_id: str, trusted_dataset: str, release_dataset: str
) -> str:
    canonical_ref = f"{project_id}.{trusted_dataset}.canonical_release"
    exchange_ref = f"{project_id}.{release_dataset}.exchange_monthly"
    weather_ref = f"{project_id}.{release_dataset}.weather_monthly"
    return f"""
    CREATE OR REPLACE VIEW `{canonical_ref}`
    OPTIONS(description='Single Phase 3 trusted release pointer; switch is atomic per statement') AS
    SELECT
      release_id, source_batch_id, 'exchange' AS domain, month_start,
      currency_code, CAST(NULL AS STRING) AS location_id,
      mean_published_daily_mean_rate_kes_per_foreign_unit,
      first_available_publication_date, last_available_publication_date,
      publication_observation_count,
      CAST(NULL AS FLOAT64) AS mean_daily_temperature_c,
      CAST(NULL AS FLOAT64) AS sum_daily_precipitation_mm,
      CAST(NULL AS INT64) AS observed_day_count,
      CAST(NULL AS INT64) AS expected_day_count,
      'KES per one foreign currency unit; arithmetic mean of published daily mean rates' AS metric_definition
    FROM `{exchange_ref}`
    UNION ALL
    SELECT
      release_id, source_batch_id, 'weather', month_start,
      CAST(NULL AS STRING), location_id,
      CAST(NULL AS NUMERIC), CAST(NULL AS DATE), CAST(NULL AS DATE), CAST(NULL AS INT64),
      mean_daily_temperature_c, sum_daily_precipitation_mm,
      observed_day_count, expected_day_count,
      'T2M monthly mean in C; sum of complete daily PRECTOTCORR in mm' AS metric_definition
    FROM `{weather_ref}`
    """


def ensure_convenience_views(
    gateway: ReleaseGateway, *, trusted_dataset: str
) -> list[dict[str, Any]]:
    project = gateway.project_id
    canonical_ref = f"{project}.{trusted_dataset}.canonical_release"
    jobs: list[dict[str, Any]] = []
    definitions = {
        "exchange_monthly": (
            "SELECT release_id,source_batch_id,month_start,currency_code,"
            "mean_published_daily_mean_rate_kes_per_foreign_unit,"
            "first_available_publication_date,last_available_publication_date,"
            "publication_observation_count,metric_definition "
            f"FROM `{canonical_ref}` WHERE domain='exchange'"
        ),
        "weather_monthly": (
            "SELECT release_id,source_batch_id,month_start,location_id,"
            "mean_daily_temperature_c,sum_daily_precipitation_mm,"
            "observed_day_count,expected_day_count,metric_definition "
            f"FROM `{canonical_ref}` WHERE domain='weather'"
        ),
    }
    for name, query in definitions.items():
        ref = f"{project}.{trusted_dataset}.{name}"
        existing = gateway.view_query(ref)
        if existing is None:
            evidence = gateway.query(
                f"CREATE VIEW `{ref}` AS {query}",
                job_prefix=f"kep_create_{name}_",
            )
            jobs.append(_job_dict(evidence))
        elif "canonical_release" not in existing:
            raise RuntimeError(f"fixed convenience view does not reference canonical release: {ref}")
    return jobs


def reporting_rows(
    gateway: ReleaseGateway, *, trusted_dataset: str, release_id: str
) -> dict[str, QueryEvidence]:
    canonical = f"{gateway.project_id}.{trusted_dataset}.canonical_release"
    results: dict[str, QueryEvidence] = {}
    for domain in ("exchange", "weather"):
        results[domain] = gateway.query(
            f"SELECT * FROM `{canonical}` WHERE domain='{domain}' "
            "ORDER BY month_start, COALESCE(currency_code, location_id)",
            job_prefix=f"kep_export_{domain}_{release_id[-8:]}_",
        )
    return results


def release_fingerprint(paths: list[Path]) -> str:
    entries = []
    for path in sorted(paths):
        entries.append({"path": path.as_posix(), "sha256": _file_sha(path)})
    return sha256_bytes(canonical_json(entries).encode("utf-8"))


def _file_sha(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _job_dict(evidence: QueryEvidence) -> dict[str, Any]:
    return {
        "job_id": evidence.job_id,
        "bytes_processed": evidence.bytes_processed,
        "bytes_billed": evidence.bytes_billed,
    }


def _json_safe(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="milliseconds")
