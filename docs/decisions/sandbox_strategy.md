# Sandbox strategy decision note

Status: proposed on 2026-10-05; live validation is deferred to Phase 2. None of
these decisions created or modified a cloud resource.

## Toolchain and authentication

Use Python 3.12 with `uv`, `dbt-core==1.12.5`, and
`dbt-bigquery==1.12.1`. These are stable dbt Core v1 packages, support Python
3.12, and are locked in `uv.lock`. Do not follow dbt platform/Cloud or dbt v2
instructions for this repository. Local dbt authentication should use user ADC
with `method: oauth`; do not create or store service-account key files.

CLI login (`gcloud auth login`) authenticates `gcloud`. ADC (`gcloud auth
application-default login`) is a distinct local credential used by client
libraries and dbt OAuth. The user must perform both interactive sign-ins if
needed. No token is printed during readiness checks.

## BigQuery Sandbox constraints

Official Sandbox documentation currently grants a lifetime 10 GiB storage
allowance, 1 TiB/month processed-query allowance, and automatic 60-day expiry
for datasets' tables, views, and partitions. Streaming, DML, and BigQuery Data
Transfer Service are unsupported. All ordinary BigQuery quotas still apply.

Consequences:

- Load local Parquet/CSV files with batch load jobs; no streaming and no DML.
- Cap an individual query at 1 GB processed, dry-run queries first, use at most
  10 warehouse queries per local run, and keep the initial dataset below 1 MB.
- Treat all warehouse state as disposable. Retain deterministic local inputs,
  schemas, run manifests, and hashes so expired resources can be reconstructed.
- Prefer dbt views for light renaming/casting and dbt tables for bounded trusted
  facts. Do not use dbt incremental models or snapshots initially.
- Avoid BigQuery materialized views initially: they add refresh behaviour,
  maintenance considerations, and SQL restrictions without value at this scale.

References:

- Sandbox: https://cloud.google.com/bigquery/docs/sandbox
- Local batch loads: https://cloud.google.com/bigquery/docs/batch-loading-data
- dbt Python matrix: https://docs.getdbt.com/faqs/Core/install-python-compatibility
- dbt BigQuery setup/OAuth: https://docs.getdbt.com/docs/local/connect-data-platform/bigquery-setup
- dbt materializations: https://docs.getdbt.com/docs/build/materializations
- dbt BigQuery configurations: https://docs.getdbt.com/reference/resource-configs/bigquery-configs
- BigQuery materialized views: https://cloud.google.com/bigquery/docs/materialized-views-intro
- Package versions: https://pypi.org/project/dbt-core/ and
  https://pypi.org/project/dbt-bigquery/

## Data model and orchestration

- Keep `fact_exchange_rate_daily` and `fact_weather_daily` separate. Their
  grains, spatial meaning, units, calendars, and revision behaviour differ.
- Orchestrate extraction, validation, load, and dbt locally. CI should lint,
  test, and compile against fixtures; it is not a warehouse scheduler.
- Every local run receives a deterministic `run_id` derived from source name,
  bounded parameters, retrieval timestamp, and content SHA-256.
- Load each run to isolated candidate tables. Validate schema, dates, uniqueness,
  source hashes, units, and row bounds before publication.
- Publish without `MERGE` or `DELETE`: run a bounded `CREATE OR REPLACE TABLE ...
  AS SELECT ...` from a validated candidate, or use a load job with
  `WRITE_TRUNCATE` for a whole bounded table. Never append blindly. Keep trusted
  names stable and candidate names run-scoped, then expire/reconstruct them.
- Phase 2 must prove Sandbox support and permissions for the selected replacement
  operation before this proposal is accepted.

## Proposed bounded dataset

- Dates: 2023-10-01 through 2023-12-31 inclusive (92 historical days).
- Locations: Nairobi (`-1.2921, 36.8219`), Mombasa
  (`-4.0435, 39.6682`), Kisumu (`-0.0917, 34.7680`).
- Weather: NASA POWER daily point, community `AG`, UTC, `T2M` and
  `PRECTOTCORR`. Expected 276 wide rows (92 days x 3 locations) or 552 long
  parameter rows.
- Exchange rates: CBK `US DOLLAR`, `STG POUND`, and `EURO`, retaining mean/buy/
  sell and explicit units/quote direction. The source contains 177 rows for this
  window (59 publication dates x 3 currencies).
- Expected fact volume: 453 rows if weather parameters remain columns, or 729
  rows if weather is normalized long. Backfill before/after this window remains
  a later acceptance decision.

