# Phase 2 acceptance evidence

Recorded 2026-10-05 (Africa/Nairobi). Identifiers and statistics are sanitized;
no credential material is retained. No billing, IAM, API, Cloud Storage,
trusted publication, commit, or push action occurred.

## Counting clarification

The Phase 0 inspector labelled its filtered count as `rows`: it counted only
five-field records. The unchanged CBK file actually contains 37,877 records from
Python `csv.reader`: 37,875 five-field records plus two three-field records:

```text
record 243: ['Date', 'US DOLLAR', 'STG POUND']
record 244: ['01/10/2016', '', '']
```

Phase 1 correctly included both as `field_count_not_5` invalid records. Its 25
invalid records comprise those two, 22 `buy_mean_sell_order` failures, and the
identified future 2038 record. No Phase 1 count or accepted observation required
correction. The Phase 0 inspector now
labels total source records, five-field records, and malformed records
separately. Whole-file duplicate/conflict values are explicitly overlapping,
non-additive diagnostics over valid records; the additive scope partition stays:

```text
37,877 = 25 invalid + 36,613 excluded-date
         + 1,062 excluded-currency + 177 selected
```

## Cloud preconditions and resources

Immediately before each dataset write, billing was reconfirmed disabled. The
initial collision inventory returned no datasets. Created resources:

- `elevated-legacy-457718-h2.kep_sandbox_probe_v1`, US.
- `elevated-legacy-457718-h2.kep_candidate_v1`, US.

Both have project ownership/phase labels and actual default table and partition
expiration metadata of 5,184,000,000 ms (60 days). The probe input expires
2026-12-04 18:40:41 UTC; the exchange fact sample expires 2026-12-04 18:52:44
UTC. Recreate expired state from the manifests, schemas, local accepted
artifacts, dbt project, and commands in the README.

## Sandbox probe

Load job `kep_probe_load_v1` loaded one 60-byte synthetic CSV, three rows, zero
bad records, and 92 output bytes into `probe_input`. dbt Core 1.12.5 with
dbt-bigquery 1.12.1 then created `stg_probe` as a view and `probe_summary` as a
table. Five tests passed; the complete probe result was `PASS=7`, `ERROR=0`.

Executed table SQL used:

```sql
create or replace table `elevated-legacy-457718-h2.kep_sandbox_probe_v1.probe_summary`
as (
  select count(*) as probe_row_count, sum(amount) as total_amount
  from `elevated-legacy-457718-h2.kep_sandbox_probe_v1.stg_probe`
)
```

It reported one output row and 48 bytes processed. There was no DML-dependent
adapter behavior.

## Immutable real loads

The loader selected the latest ready batch per source from SQLite:

| Source | Batch | Table | Job | Artifact SHA-256 | Schema SHA-256 | Rows | Input/output bytes |
|---|---|---|---|---|---|---:|---:|
| CBK | `batch_1fbe96c779d3e2aa706b` | `landing_cbk__batch_1fbe96c779d3e2aa706b` | `kep_load_cbk_1fbe96c779d3e2aa706b_913dfb0f` | `df6b120e9491984606052e74bd783a64ea36e679bf4d2f3059394a775421dab4` | `913dfb0fb53abe8a165f1e3b4639d483ef4629ec21fa57529d927a43d56ec0c0` | 177 | 34,598 / 39,176 |
| NASA POWER | `batch_5d09562b5edc416d16eb` | `landing_nasa_power__batch_5d09562b5edc416d16eb` | `kep_load_nasa_power_5d09562b5edc416d16eb_3b1f14bf` | `22668763f56d8fbfc6c3ed185762d330ec4c57ac520875306cea3ab4e4493ed8` | `3b1f14bf1463c5a79c1b210afe3115a3eb8b4464898f1560a82f5cd30404aec0` | 276 | 43,346 / 44,068 |

A same-command rerun created no load jobs and returned `outcome=reused` after
fingerprint verification. Load attempts were
`load_attempt_0a8b2cad1e2444d28a6314404ce75a3e` and
`load_attempt_fda236c7cdca4b01b809d7ef0267543f`; counts remained 177 and 276.

## Models, tests, and reconciliation

Candidate build: 2 staging views, 3 dimensions, 2 facts, 2 monthly marts, and 39
data tests. Result: `PASS=48 WARN=0 ERROR=0 SKIP=0` in 109.48 seconds. Tests
covered keys, required values, relationships, bounded dates, currency quotation,
units/time semantics, physical bounds, CBK publication-date completeness, NASA
date/location completeness, and landing-to-reporting reconciliation.

```text
CBK: 37,877 original -> 177 accepted -> 177 loaded -> 177 staged -> 177 fact
     -> 9 monthly rows whose publication counts sum to 177
NASA: 276 expected/accepted -> 276 loaded -> 276 staged -> 276 fact
      -> 9 monthly rows whose observed-day counts sum to 276
```

Published counts remain null/not implemented.

## Volume controls and lineage

The dbt OAuth profile used two threads and a 1 GiB maximum-bytes-billed guard per
query. The candidate build's adapter metadata totals were 213,138 bytes processed
and 608,174,080 bytes billed (BigQuery minimum billing granularity dominates at
this tiny scale). A handwritten reconciliation query dry-run estimated 144 bytes;
the executed job `kep_phase2_reconciliation_v1` processed 144 bytes and billed
62,914,560 bytes, returning 177/177/177 and 276/276/276.

Local ignored documentation artifacts:

- `target/index.html`
- `target/manifest.json`
- `target/catalog.json`
- `target/run_results.json`
- compiled and executed SQL under `target/compiled/` and `target/run/`

Regenerate them using the documented `dbt docs generate` command.

## Recommendation and limits

**PASS for Phase 2 candidate loading and modeling.** Candidate tables are small,
tested, reproducible, explicitly expiring, and not published. CBK raw reuse terms
remain unresolved; NASA values remain representative grid-point estimates. ADC
warns that the end-user credential has no quota project, although every executed
connection/job succeeded with the explicit project. Full end-to-end recovery
from every cloud interruption, backfill acceptance, trusted publication, and
operational scheduling are not implemented or claimed.

## Post-implementation verification

Verified on 2026-10-05 without rebuilding the dbt graph.

### Immutable load reuse and content

Repeating the manifest-selected `load --source all` command performed no load
job and returned `outcome=reused` for both tables:

| Source | Verification attempt | Batch | Rows | Artifact SHA-256 | Table bytes |
|---|---|---|---:|---|---:|
| CBK | `load_attempt_feb3c1d363714cc5a329982afcbcc023` | `batch_1fbe96c779d3e2aa706b` | 177 | `df6b120e9491984606052e74bd783a64ea36e679bf4d2f3059394a775421dab4` | 39,176 |
| NASA POWER | `load_attempt_5bd03d7314394ff9a6fbe706fb144e50` | `batch_5d09562b5edc416d16eb` | 276 | `22668763f56d8fbfc6c3ed185762d330ec4c57ac520875306cea3ab4e4493ed8` | 44,068 |

The load IDs, schema fingerprints, artifact fingerprints, observation hashes,
row counts, and table sizes are unchanged from the original load. A guarded
BigQuery verification query independently returned:

```text
relation          rows  distinct business keys
CBK landing        177  177
CBK staging        177  177
CBK fact           177  177
weather landing    276  276
weather staging    276  276
weather fact       276  276
```

This confirms no appended/duplicate business keys and exact source-to-fact row
reconciliation. The local mismatch/recovery test remains the evidence that an
existing mismatched table is recorded as failed rather than reused.

### Retained dbt execution evidence

`target/run_results.json`, generated at `2026-10-05T18:53:34.375440Z`, contains
48 successful results: nine model successes and 39 passing tests. The CBK and
NASA semantic/completeness tests, staging and fact composite-key uniqueness
tests, and landing-to-fact/reporting reconciliation test all have status `pass`.
Models were not rebuilt for this verification.

### Independent monthly reference calculations

The reference used Python `csv.DictReader` and `decimal.Decimal` directly over
the latest accepted local CSVs. It does not call or reproduce the dbt model SQL.
Exact tolerances were required for counts/dates, absolute `1e-9` for exchange
rates, and absolute `1e-6` for weather floating values.

| Selection | Metric | Local reference | BigQuery mart | Difference | Result |
|---|---|---:|---:|---:|---|
| USD, 2023-10 | publication count | 20 | 20 | 0 | pass |
| USD, 2023-10 | mean published daily mean rate | 149.397865 | 149.397865 | 0 | pass |
| USD, 2023-10 | first / last dates | 2023-10-02 / 2023-10-31 | same | 0 | pass |
| Nairobi, 2023-10 | observed / expected days | 31 / 31 | 31 / 31 | 0 | pass |
| Nairobi, 2023-10 | mean daily T2M (C) | 21.69741935483870967741935484 | 21.697419354838708 | about 1.68e-15 | pass |
| Nairobi, 2023-10 | summed daily precipitation (mm) | 45.84 | 45.84 | 0 | pass |

Authoritative query job `kep_phase2_verification_v2` processed 14,717 bytes,
billed 62,914,560 bytes, and retained the 1 GiB maximum-bytes-billed guard. An
earlier Windows CLI invocation (`kep_phase2_verification_v1`) received only the
first line of the intended statement; it was read-only and its single CBK
landing result is not used as complete verification evidence.

### Isolation and repository audit

The project dataset inventory contains exactly `kep_sandbox_probe_v1` and
`kep_candidate_v1`, both in US with expected ownership labels. The candidate
inventory contains only the two landing tables, two staging views, three
dimensions, two facts, and two candidate marts documented above. No dataset or
relation named trusted, published, or Phase 3 was found or created. Verification
performed only metadata reads, query jobs, and local reuse-attempt recording;
it made no cloud resource mutation.

Git remains on `main` with no commits. There are 65 non-ignored candidate files.
A targeted scan found no API keys, OAuth tokens, refresh tokens, client secrets,
private keys, or account email addresses. The active ADC/OAuth profile contains
only environment-variable references and is ignored, as are the SQLite manifest,
raw/generated data, logs, and dbt `target/` artifacts.
