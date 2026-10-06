# Portfolio case study: Kenya Economic Data Platform

## Problem

Public historical data is easy to download but harder to make trustworthy. The
CBK exchange-rate file contains mixed date formats, duplicates, inconsistent
quotation conventions across currencies, and at least one invalid future row.
NASA POWER provides structured daily data, but its values are gridded estimates,
its missing-value convention must be handled explicitly, and different
locations can legitimately have different requested date ranges.

I built this personal portfolio project to demonstrate a compact, evidence-led
Python/SQL/BigQuery/dbt workflow: validate the source boundary, preserve
provenance, build tested candidates, and publish a report only after critical
checks pass.

## Architecture

Python performs bounded extraction, parsing, contract checks, reconciliation,
content hashing, and local manifest recording. Accepted immutable batches load
to owned BigQuery Sandbox candidate tables. dbt builds typed staging views,
dimensions, daily facts, and separate exchange/weather monthly marts. The local
orchestrator requires dbt and source-to-fact reconciliation evidence before it
freezes a candidate into release tables and atomically replaces one canonical
view. Fixed reporting views resolve through that same pointer.

The platform is intentionally batch-oriented and laptop-operated. It uses no
streaming, incremental dbt models, managed scheduler, or billing-enabled cloud
services.

## Important decisions

### Pin source identity, not just a URL

CBK exposes a full historical CSV, so the implementation downloads and hashes
the complete file, then filters the bounded date/currency scope locally. It does
not pretend that this is a rolling current-rate API. Raw CBK redistribution is
excluded while reuse terms remain unclear.

NASA requests always specify UTC, `T2M`, and `PRECTOTCORR`. Fill values, missing
dates, unexpected units, and invalid ranges block readiness.

### Keep provenance and content identity separate

Each batch records source bytes, accepted-output identity, business-key/value
identity, retrieval metadata, and reconciliation. A fresh retrieval can create
new provenance while normalized observations remain identical. Reruns reuse
only when the relevant fingerprints match.

### Publish through gates and frozen releases

Candidate data is never trusted merely because a build completed. Critical dbt
tests and reconciliation must agree on keys and counts. Only then are monthly
rows copied to new release tables and validated. The canonical view switch is a
single statement, so prepublication failures leave consumers on the prior
release.

“Immutable” here means the application never updates release tables and checks
their identity before reuse. It does not claim that IAM prevents every manual
change by a privileged project operator.

### Make asymmetric backfills explicit

The demonstrated backfill added Nairobi September without extending Mombasa or
Kisumu. Composition treated the replacement as authoritative only inside its
declared date/location scope and preserved all out-of-scope business keys.
Expected dbt coverage was derived per location.

## Verified results

Final canonical release `release_a74a4772ee3b0338a041` contains:

- 177 CBK observations across USD, GBP, and EUR, reconciled to 177 daily fact
  rows and 9 monthly report rows;
- 306 NASA POWER observations, reconciled to 306 daily fact rows and 10 monthly
  report rows;
- Nairobi weather from 2023-09-01 through 2023-12-31 (122 days); and
- Mombasa and Kisumu weather from 2023-10-01 through 2023-12-31 (92 days each).

The real Nairobi September extraction added exactly 30 observations. Every one
of the 276 baseline weather keys/values and all 177 baseline exchange
keys/values survived unchanged. An independent September calculation matched
BigQuery at the documented `1e-9` tolerance.

## Failure and recovery demonstration

I copied verified inputs into an isolated candidate and removed Nairobi
2023-09-15. The live dbt completeness test failed and the normal publication
gate also rejected 305 weather rows against the expected 306. No publication
attempt or release record was created. The canonical release ID and all 19
trusted monthly rows remained unchanged.

A fresh candidate restored the record, built 9 models, passed 39 tests,
reconciled 177/9 exchange and 306/10 weather, and published the final release.
The fault dataset remained isolated and was never selected by the canonical
views.

## Limitations

- BigQuery Sandbox objects expire; the platform is not durable production
  infrastructure.
- Execution and recovery depend on local ignored source artifacts and a SQLite
  manifest on one laptop.
- CBK raw redistribution is withheld pending licence clarification.
- NASA POWER describes representative grid cells, not observed weather stations
  or entire cities.
- Floating aggregation requires explicit numeric tolerances.
- GitHub Actions performs offline code validation only and is not a scheduler.
- No production IAM hardening, monitoring/SLOs, streaming, AI/ML, food-price
  domain, or business-impact measurement is claimed.

## Lessons

The most useful engineering work was at the boundaries: defining business
keys, distinguishing retrieval from observation time, making quotation units
explicit, recording why rows were rejected, and proving that publication did
not occur on failure. Small data volumes did not remove the need for recovery
semantics, immutable evidence, and precise operator documentation.

