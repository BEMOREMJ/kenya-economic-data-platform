# Phase 3 acceptance evidence

Recorded 2026-10-05 (Africa/Nairobi). No source was redownloaded and the Phase 2
dbt graph was not rebuilt for the first release. Billing remained disabled.

## First trusted release

- Run: `run_6da0cd1f89f2957c9150`
- Release: `release_b791d9290ee623c82f45`
- Source batches: CBK `batch_1fbe96c779d3e2aa706b`; NASA POWER
  `batch_5d09562b5edc416d16eb`
- Model fingerprint:
  `039ce89f76060f6e207f9264a27e7f651c540ae38faba0f3247acbe159c974fd`
- Retained dbt evidence SHA-256:
  `dc866ebe2f0694e01365c32d78db636514244cfdaa1c45c20506cec4b8070b81`
- Retained dbt result: 9 model successes and 39 passing tests.

New US resources:

- `kep_release_b791d9290ee623c82f45` dataset, containing immutable
  `exchange_monthly` and `weather_monthly` tables.
- `kep_trusted_v1` dataset, containing `canonical_release` plus fixed
  `exchange_monthly` and `weather_monthly` convenience views.

Both datasets carry `kep_owner=kenya_economic_data_platform`, use 60-day default
table/partition expiration, and were collision checked. Frozen exchange and
weather tables contain 9 unique monthly keys each, representing 177 and 276
observations respectively, with zero identity errors and coverage from October
through December 2023. They expire on 2026-12-04 at approximately 19:41 UTC.

## Gates and publication SQL

All gates passed before the switch:

- immutable extraction artifact verification and zero-request reuse;
- landing fingerprint and 177/276 count verification;
- non-stale retained critical dbt evidence tied to the model fingerprint;
- landing = fact = reporting observation reconciliation;
- 9 unique reporting keys per domain and complete requested coverage; and
- frozen-table release/batch identity validation.

Freeze jobs used `CREATE TABLE AS SELECT`:

- `kep_freeze_fx_23c82f45_c1d51541-0351-485f-9b83-c637d7cd45c4`
- `kep_freeze_wx_23c82f45_9ea6173b-d24b-4a67-849c-ae9a33627c6b`

The publication switch used one statement:

```sql
CREATE OR REPLACE VIEW
  `elevated-legacy-457718-h2.kep_trusted_v1.canonical_release`
AS
SELECT typed exchange release rows
FROM `elevated-legacy-457718-h2.kep_release_b791d9290ee623c82f45.exchange_monthly`
UNION ALL
SELECT typed weather release rows
FROM `elevated-legacy-457718-h2.kep_release_b791d9290ee623c82f45.weather_monthly`
```

Job `kep_publish_23c82f45_ad2efa2e-6265-484e-9959-c0e3210b850f`
completed as `CREATE_VIEW`, processing and billing zero bytes. Querying the new
canonical view returned exactly `release_b791d9290ee623c82f45` before local
publication success was recorded. There was no previous release, so the stored
rollback reference is null.

The canonical view preserves separate domain grains with nullable domain-specific
typed columns. Its fixed convenience views reference only the canonical entry
point. A switch is atomic for one statement, but separate consumer queries on
opposite sides of a future switch may observe different releases.

## Orchestration, rerun, and health

The single `operate` command recorded preflight, extraction, loading, candidate
tests, reconciliation, freeze, publication, and export stages. A rerun with the
same content produced:

- zero source requests and reused source batches;
- zero new load or frozen-table creation jobs;
- reused model/test evidence without a dbt rebuild;
- fresh validation of 9/9 keys and 177/276 observations;
- `publication.outcome=reused`, no switch job; and
- identical report hashes.

Latest demonstrated reuse run: `run_7531f72789ce688db82e`. The health output
reports latest attempt separately from latest successful publication, current
warehouse release ID, stages/errors, source retrieval/coverage facts, historical
freshness policy, query volume, and resource states/expiration. Release resources
were `available`, not expired. Local generated outputs are ignored:

- `exchange_summary.csv`: 9 rows, SHA-256
  `0c54d048f064e0773620f079f090fd34d117a2c3e5cb4683eca8c405b6b852cf`
- `weather_summary.csv`: 9 rows, SHA-256
  `2cbf20867a277cd79119f80c729421f3509d2675d37b76f04fb8a2fc0df2e00f`
- `pipeline_health.json`

An independent `retry-export` succeeded with the same hashes and did not run
extraction, loading, dbt, freeze, or publication stages.

## Volume

The first run's recorded BigQuery jobs processed 5,085 bytes and billed
167,772,160 bytes in total. This includes reconciliation, two frozen CTAS jobs,
release validation, canonical verification, and two report queries. The
publication and convenience-view DDL jobs processed/billed zero bytes. No new
source download or landing load bytes were incurred. Every query retained the
1 GiB per-query maximum-bytes-billed guard.

## Backfill, recovery, and CI evidence

Local behavioral tests prove:

- scoped precedence preserves baseline rows outside the declared keys;
- additions, replacements, removals, and unchanged rows reconcile;
- duplicates and out-of-scope replacement rows fail;
- changed inputs/models require a new candidate namespace;
- concurrent locks fail closed;
- failed gates stop before publication;
- a current BigQuery release repairs an interrupted local publication record;
- canonical switching is a single view statement with no DML; and
- rollback requires a still-valid previous release.

The first release has no previous target, so a real rollback was not attempted.
Real backfill, injected failure, interrupted-run, recovery, and rollback
acceptance demonstrations remain explicitly deferred to Phase 4.

`.github/workflows/ci.yml` installs from the frozen lock, compiles Python, runs
offline behavioral tests, and parses dbt with fake non-cloud identifiers on
push/pull request. It has read-only repository permissions and no credentials,
source requests, warehouse execution, scheduling, or publication. Equivalent
steps were run locally; the workflow was not pushed or executed on GitHub. The
final local verification completed with `21 passed in 3.61s`, a clean Python
compile, a successful offline `dbt parse`, and a successful `uv lock --check`.

## Independent post-implementation verification

Verification was performed on 2026-10-05 and completed on 2026-10-06 after an
execution-quota interruption. The normal runbook command was executed twice
against the existing real scope using the final code state. Both executions
resolved to deterministic run `run_7f1480b26cbf982510b1` and existing release
`release_b791d9290ee623c82f45`.

Both executions confirmed:

- CBK and NASA extraction outcomes were `reused`, with zero source requests;
- landing loads and all 9 model/39 test results were reused;
- reconciliation remained 177 exchange and 276 weather observations, with 9
  monthly reporting rows and 9 unique keys per domain;
- no load job, frozen-table creation job, convenience-view job, or canonical
  switch job was created;
- publication outcome was `reused` and the current canonical release remained
  `release_b791d9290ee623c82f45`; and
- exchange and weather CSV content remained byte-identical at SHA-256
  `0c54d048f064e0773620f079f090fd34d117a2c3e5cb4683eca8c405b6b852cf`
  and `2cbf20867a277cd79119f80c729421f3509d2675d37b76f04fb8a2fc0df2e00f`.

New operational records were kept separate from content identity. The first
verification reuse attempts began at `2026-10-05T20:07:51.963Z` (CBK) and
`2026-10-05T20:07:51.995Z` (NASA). The unchanged rerun attempts began at
`2026-10-06T05:23:59.770Z` and `2026-10-06T05:23:59.903Z`. All four attempts
recorded status `reused` and request count zero. The latest rerun completed at
`2026-10-06T05:24:22.729Z`. Health output timestamps and query job IDs changed,
as expected, while release/report content did not.

A direct read-only canonical query returned exactly one release ID for each
domain: exchange had 9 rows/177 observations and weather had 9 rows/276
observations, both under `release_b791d9290ee623c82f45`. BigQuery metadata
confirmed `canonical_release` is a view referencing both frozen relations.
`exchange_monthly` and `weather_monthly` are physical `TABLE` objects, each
still at 9 rows and with modification timestamps equal to their original
creation timestamps (`2026-10-05T19:41:40.094Z` and
`2026-10-05T19:41:43.529Z`). Their expiration timestamps remain 2026-12-04.

Five requested focused offline scenarios passed in `2.25s`: critical gate
failure leaves the publication mock uncalled; mismatched dbt/current model
fingerprints refuse publication; scoped backfill preserves out-of-scope keys;
BigQuery-authoritative publication repairs an interrupted local record; and
`retry-export` invokes only the export path. The separate review added the
explicit model-fingerprint comparison to the publication gate and explicit
tests for that mismatch and export-only retry.

The CI commands were then run locally once: `uv sync --frozen --dev` checked 110
packages, Python compilation passed, all 21 offline tests passed, and offline
`dbt parse` passed with fake identifiers. A stale workspace-local
`.pytest-tmp` directory owned by an earlier sandbox identity could not be
removed, so the local pytest command used a fresh system-temporary `--basetemp`;
the workflow command remains unchanged for fresh runners. GitHub Actions was
not executed and is not claimed as passing.

The runbook's expiration-recovery section explicitly requires full
reconstruction and fresh load, dbt, reconciliation, coverage, frozen-table,
and switch validation when a referenced resource expires. Missing relations
invalidate retained completion evidence.

## Repository and closeout audit

- Branch: `main`; no commit or push was made.
- Git candidates inspected: 73.
- Sensitive-content scan: zero candidate files matched private-key, Google API
  key, populated `client_secret`, or populated `private_key` patterns.
- `config/profiles.yml`, `data/manifests/`, `data/reports/`, `logs/`, and
  `target/` are ignored and are not publication candidates.
- The cloud inventory after publication contains only the two pre-existing
  Phase 0/2 datasets plus the owned Phase 3 release and trusted datasets. No
  global project setting was changed and billing remained disabled.
- Work completed within the requested four-hour implementation window. Exact
  wall-clock duration was not captured by the pipeline, so no more precise
  elapsed-time claim is made.

## Recommendation

**PASS for Phase 3 orchestration and first gated publication.** The release is
reproducible, isolated from mutable candidates, verified after its single switch,
and operable through one local command. Scheduling remains laptop-dependent;
Sandbox expiry, ADC quota-project warnings, CBK redistribution restrictions, and
the Phase 4 demonstrations remain limitations.
