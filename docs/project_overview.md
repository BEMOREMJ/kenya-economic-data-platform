# Project overview: Kenya Economic Data Platform

## Purpose

Kenya Economic Data Platform is a personal data engineering project that
ingests historical exchange-rate and weather data, validates and models it in
BigQuery with dbt, and publishes reproducible reporting outputs.

The project addresses practical data engineering tasks: reliable ingestion,
raw preservation, explicit source contracts, warehouse modelling, validation,
orchestration, scoped backfills, recovery, and reporting. Its deliberately
small historical scope makes each result traceable from source evidence to the
published monthly rows.

## Source challenges

The CBK historical exchange-rate file contains mixed date formats, duplicate
records, different quotation conventions across currencies, and an invalid
future row. NASA POWER provides structured daily data, but its values are
gridded estimates. The pipeline must also handle its missing-value convention,
explicit UTC dates, and legitimate differences in location coverage.

## Architecture

Python performs bounded extraction, parsing, contract checks, reconciliation,
content hashing, and local manifest recording. Accepted immutable batches load
to owned BigQuery Sandbox candidate tables. dbt builds typed staging views,
dimensions, daily facts, and separate exchange/weather monthly marts. The local
orchestrator requires dbt and source-to-fact reconciliation evidence before it
freezes a candidate into release tables and replaces one canonical view. Fixed
reporting views resolve through the same pointer.

The platform is batch-oriented and laptop-operated. It uses no streaming,
incremental dbt models, managed scheduler, or billing-enabled cloud services.

## Engineering decisions

### Pinned source identity

CBK exposes a complete historical CSV. The implementation hashes that file and
filters the bounded date/currency scope locally. It does not represent this as a
rolling current-rate API. Raw CBK redistribution remains excluded while reuse
terms are unclear.

NASA requests always specify UTC, `T2M`, and `PRECTOTCORR`. Fill values, missing
dates, unexpected units, and invalid ranges block readiness.

### Separate provenance and observation identity

Each batch records source bytes, accepted-output identity, business-key/value
identity, retrieval metadata, and reconciliation. A fresh retrieval can create
new provenance while normalized observations remain identical. Reruns reuse
artifacts only when the relevant fingerprints match.

### Gated publication

Critical dbt tests and reconciliation must agree on keys and counts before the
pipeline freezes monthly rows into release tables. The canonical view switch
uses one statement, so prepublication failures leave consumers on the previous
release.

Application code never updates release tables and verifies identity before
reuse. BigQuery IAM does not prevent every possible manual change by a
privileged project operator.

### Scoped historical backfills

The demonstrated backfill added Nairobi September without extending Mombasa or
Kisumu. Composition treated the replacement as authoritative only inside its
declared date/location scope and preserved all keys outside that scope. dbt
coverage expectations were derived separately for each location.

## Verified results

Final canonical release `release_a74a4772ee3b0338a041` contains:

- 177 CBK observations across USD, GBP, and EUR, reconciled to 177 daily fact
  rows and 9 monthly report rows;
- 306 NASA POWER observations, reconciled to 306 daily fact rows and 10 monthly
  report rows;
- Nairobi weather from 2023-09-01 through 2023-12-31, covering 122 days; and
- Mombasa and Kisumu weather from 2023-10-01 through 2023-12-31, covering 92
  days each.

The Nairobi September extraction added exactly 30 observations. All 276
baseline weather keys/values and all 177 baseline exchange keys/values remained
unchanged. An independent September calculation matched BigQuery within the
documented `1e-9` tolerance.

## Failure and recovery demonstration

An isolated candidate copied verified inputs and omitted Nairobi 2023-09-15.
The live dbt completeness test failed, and the normal publication gate rejected
305 weather rows against the expected 306. The pipeline created no publication
attempt or release record. The canonical release ID and all 19 trusted monthly
rows remained unchanged.

A fresh candidate restored the record, built 9 models, passed 39 tests,
reconciled 177/9 exchange and 306/10 weather, and published the final release.
The fault dataset stayed isolated and never appeared in the canonical views.

## Results dashboard

The local standalone dashboard reads only the trusted exchange and weather CSV
exports for one release. It requires matching release identities, derives
counts and coverage from those files, and embeds Plotly for offline viewing.
Real exports and HTML remain ignored because CBK redistribution terms are not
resolved.

## Limitations

- BigQuery Sandbox objects expire and do not provide durable storage.
- Execution and recovery depend on ignored local artifacts and a SQLite
  manifest on one laptop.
- CBK raw redistribution remains withheld pending licence clarification.
- NASA POWER describes representative grid cells, not observed weather stations
  or entire cities.
- Floating aggregation requires explicit numeric tolerances.
- GitHub Actions performs offline code validation only and does not schedule the
  warehouse.
- Production IAM hardening, monitoring, streaming, AI/ML, and the food-price
  domain remain outside scope.

