# Phase 4 acceptance evidence

Recorded 2026-10-06 (Africa/Nairobi). This document covers real targeted
backfill, isolated live quality failure, and clean recovery. Billing remained
disabled. No IAM, API enablement, streaming, DML/MERGE, commit, push, or
repository publication occurred.

## Commands

```powershell
# One bounded real retrieval
uv run python -m kenya_economic_data extract --source nasa `
  --start-date 2023-09-01 --end-date 2023-09-30 --locations Nairobi

# Explicit effective-input composition
uv run python -m kenya_economic_data compose-backfill --source nasa `
  --baseline-batch-id batch_5d09562b5edc416d16eb `
  --replacement-batch-id batch_7ac5183fda0a7b88f4bb `
  --start-date 2023-09-01 --end-date 2023-09-30 --selections Nairobi

# Normal gated backfill publication (also repeated unchanged)
uv run python -m kenya_economic_data operate `
  --project elevated-legacy-457718-h2 --location US `
  --candidate-dataset kep_candidate_backfill_202309_nairobi_v1 `
  --trusted-dataset kep_trusted_v1 `
  --start-date 2023-09-01 --end-date 2023-12-31 `
  --locations Nairobi Mombasa Kisumu `
  --cbk-batch-id batch_1fbe96c779d3e2aa706b `
  --nasa-batch-id composition_a42482249b647d68ddaa

# Explicitly isolated fault injection; exit 1 is the expected acceptance result
uv run python scripts/phase4_fault_injection.py

# Fresh clean recovery candidate
uv run python -m kenya_economic_data operate `
  --project elevated-legacy-457718-h2 --location US `
  --candidate-dataset kep_candidate_recovery_202309_nairobi_v1 `
  --trusted-dataset kep_trusted_v1 `
  --start-date 2023-09-01 --end-date 2023-12-31 `
  --locations Nairobi Mombasa Kisumu `
  --cbk-batch-id batch_1fbe96c779d3e2aa706b `
  --nasa-batch-id composition_a42482249b647d68ddaa

uv run python -m kenya_economic_data health `
  --project elevated-legacy-457718-h2 --location US `
  --trusted-dataset kep_trusted_v1
```

All BigQuery queries retained the 1 GiB maximum-bytes-billed guard.

## Baseline

The canonical view returned only expected baseline release
`release_b791d9290ee623c82f45`. The retained rollback reference after backfill
was this release.

- Exchange: 177 observation keys; value fingerprint
  `855330dda944a7d8e80a7564dcbfb85016e612e0d3ae3f5101db465cafd7a15b`.
- Weather: 276 observation keys; value fingerprint
  `721e15f42d5559553d35467d5308d5b4c02be18b7841a31faef7598288ead1f7`.
- Combined local provenance fingerprint:
  `0e74c8ce986bb7d8f1761d262b721548c0d95e58e593216e4604818dd8412638`.
- Canonical monthly content: 18 rows; content fingerprint
  `3bdba7a471c77e9fb1f12d9e92496506e48b02bce6979cb01a16a6d1f8cd818b`;
  provenance fingerprint
  `33c19a273d937fbdcb5ab83ceb051f45bc2592c36e9e8593d6aed8f525e74cf9`.

Fingerprints include sorted business keys and measurement values. Provenance
fingerprints are separate and include batch/release/source-snapshot identity.

## Real Nairobi September backfill

NASA POWER extraction used the existing `AG` community, UTC convention, T2M
and PRECTOTCORR parameters. It completed in one HTTP attempt:

- Replacement batch: `batch_7ac5183fda0a7b88f4bb`.
- Accepted/rejected: 30/0.
- Content SHA-256:
  `135ac4214a89faa5080934372769feddea951ff5a1e6608c3fb5d85713ce6374`.
- Observation SHA-256:
  `3571b9b119509074342523b4747839fccd08021fdf6840dfe38dea1242d191eb`.

Composition `composition_a42482249b647d68ddaa` produced 306 rows with SHA-256
`c9d8b416bfe236fe719005cb1bd6b201ddd070ae345dc82cd0532eaf3eece59f`:

- added: 30, exactly Nairobi 2023-09-01 through 2023-09-30;
- removed: 0;
- replaced: 0;
- unchanged: 276; and
- changed baseline measurement values: 0 across all 276 baseline keys.

The independent preserved-baseline fingerprint was identical before and after:
`64f2c534010f5823edbf0410b7afcf678474abcce2ff384ec7eb9aba903343e0`.
The warehouse landing table was separately checked against every baseline key;
all 276 were present with zero value differences at tolerance `1e-9`.

The first successful gated run was `run_18ec19a0b93e38f5af17`. It published
`release_00e432b9ddf0abe27a84` over previous release
`release_b791d9290ee623c82f45`:

- 9 models succeeded and all 39 tests passed;
- exchange landing = fact = report observations = 177, with 9 monthly rows;
- weather landing = fact = report observations = 306, with 10 monthly rows;
- release validation found 9/10 unique keys and zero identity errors;
- reconciliation job:
  `kep_gate_reconciliation_1d7951ce-55a8-489e-9478-846fd454637b`;
- freeze jobs:
  `kep_freeze_fx_abe27a84_ce06193d-8d21-4587-8702-001e9637c0ac` and
  `kep_freeze_wx_abe27a84_dfea87cd-0228-4900-853e-ca8cbd6d0f7b`;
- validation job:
  `kep_validate_release_abe27a84_a527f254-dd79-45ad-8606-c72467aae4a1`; and
- zero-byte canonical switch job:
  `kep_publish_abe27a84_f57a5399-9e94-47d4-8f72-f454c933581c`.

Coverage was Nairobi 2023-09-01 through 2023-12-31 (122 days), while Mombasa
and Kisumu remained 2023-10-01 through 2023-12-31 (92 days each). September
Nairobi completeness was 30/30.

Independent accepted-record calculations gave mean temperature `21.658 C` and
precipitation total `14.77 mm`. BigQuery returned `21.658 C` and
`14.770000000000001 mm`; absolute differences were `0` and
`1.7763568394002505e-15`, both below tolerance `1e-9`.

## Unchanged backfill rerun

The composition repeated as the same ID, SHA and 306 rows without a source
request. Final reuse run `run_c6935cc7a829b51f4d5d` reused both landing
tables, retained dbt evidence from `run_18ec19a0b93e38f5af17`, both frozen
tables, and the canonical pointer. It created no load, freeze, convenience-view,
or switch job. Reconciliation remained 177/9 and 306/10. Report hashes were
unchanged:

- exchange: `22e3b63d464bef6179847760dc1f759e4cc0f66ca6be050a5fd0a79a8da33944`;
- weather: `3dc5aecf93c1f401004a12e1f38e345bc620c10895adb71d0ea98de03e1bad15`.

No duplicate insertion occurred: the effective input retained 306 unique
weather business keys and the release retained 10 unique monthly keys.

## Live quality failure and publication refusal

Acceptance-only dataset
`kep_acceptance_fault_missing_nairobi_20230915_v1` is labelled
`kep_phase=phase4_fault_injection`. It contains copied verified inputs only;
the NASA copy omits exactly `(2023-09-15, Nairobi)`, leaving 305 rows. The
original artifacts, successful candidates, frozen releases, and canonical view
were not modified.

Copy jobs were:

- `kep_p4_fault_copy_cbk_702534e8-558d-4e11-94d8-ca6cf156cbd7`;
- `kep_p4_fault_copy_nasa_04044e8d-38db-4c6f-bde2-0d94a5b34376`.

Actual `dbt build` returned 1. Critical test
`test.kep_warehouse.assert_weather_semantics_and_completeness` failed with one
missing expected key. The normal publication gate independently refused load
counts `{cbk: 177, nasa_power: 305}` against expected 177/306. Acceptance run
`run_44ce952e71f3f5a83346` is recorded failed; publication was never called and
no release record was created.

Canonical before/after remained `release_00e432b9ddf0abe27a84`. Trusted content
SHA-256 before and after was identical:
`98f23497a8c2b22b95a00f2e368760a637eb7a4da294caacede96681219a7e8b`.
Health showed this latest failed attempt separately from the latest successful
published backfill release.

## Clean recovery and final state

Recovery used fresh dataset `kep_candidate_recovery_202309_nairobi_v1` and the
preserved verified batches. It did not mutate the failed candidate. Run
`run_50c96002b2ab247ef15d` loaded 177/306 rows, built 9 models, passed 39 tests,
reconciled 177/9 and 306/10, froze a new release, and published
`release_a74a4772ee3b0338a041`.

- reconciliation job:
  `kep_gate_reconciliation_9a958b7f-8b7e-493a-abd1-1ef7f522d8c7`;
- freeze jobs:
  `kep_freeze_fx_0338a041_acfd3452-bfc7-4377-b208-44a7cfbbef22` and
  `kep_freeze_wx_0338a041_21a29b31-d2be-4a51-9547-cef9d3cdc5a3`;
- validation job:
  `kep_validate_release_0338a041_e4b02cf9-c917-480e-a317-46b13e0e79d6`;
- zero-byte switch job:
  `kep_publish_0338a041_855b0ac5-acab-4b5f-8649-a20890830d48`.

The final canonical view returns only `release_a74a4772ee3b0338a041`. Exchange
measurement content is byte-identical to the first backfilled release. Across
all 10 weather rows, completeness integers match exactly; maximum rebuild
differences are `1.4210854715202004e-14 C` and
`5.684341886080802e-14 mm`, below tolerance `1e-9`. Final health reports both
latest attempt and latest successful publication as healthy, with the intended
backfill retained.

## Volume, resources, and demonstrated fixes

The Phase 4 cloud job window was 2026-10-06T05:32:15.567Z through
2026-10-06T05:57:53.495Z: 1,537.928 seconds (25m 37.928s). Filtered project job
metadata recorded 291 jobs: 287 query and 4 load jobs. Total bytes processed
were 1,149,054; BigQuery reported 3,166,699,520 billed bytes due to per-query
minimums. Load input/output bytes were 168,976/179,760. Billing stayed disabled.

Five owned, US, 60-day-expiring datasets were added:

- `kep_candidate_backfill_202309_nairobi_v1`;
- `kep_release_00e432b9ddf0abe27a84`;
- `kep_acceptance_fault_missing_nairobi_20230915_v1`;
- `kep_candidate_recovery_202309_nairobi_v1`; and
- `kep_release_a74a4772ee3b0338a041`.

The acceptance run exposed and fixed three narrow defects: load job IDs now
include the candidate dataset identity; monthly-row expectations are dynamic;
and retained dbt evidence is evaluated before a deterministic stage record is
reset for rerun. Asymmetric per-location weather coverage and explicit verified
batch selection were also added for the required backfill.

Final local regression verification completed with a clean Python compile, 22
passing offline tests in 3.55 seconds, and the successful offline dbt parse
performed after the dbt coverage changes. Branch remains `main`; no commit or
push was made. Seventy-five Git candidates were inspected and zero files matched
private-key, Google API key, populated `client_secret`, or populated
`private_key` patterns. Credentials, source/processed data, manifests, reports,
logs, pytest temporary data, and dbt targets remain ignored.

Remaining limitations are Sandbox object expiration, laptop-dependent
operation, the ADC quota-project warning, floating aggregation noise requiring
numeric tolerances, and deferred final documentation/GitHub review. The
fault-injection and superseded candidate/release datasets remain isolated,
labelled, and subject to the configured 60-day expiration rather than being
deleted during acceptance.

## Acceptance matrix

| Sprint gate | Result | Evidence | Data |
|---|---|---|---|
| End-to-end BigQuery execution | PASS | Runs `run_18ec19a0b93e38f5af17`, `run_50c96002b2ab247ef15d`; freeze/validation/switch jobs above | Real |
| Critical ingestion and dbt checks | PASS | 30 accepted/0 rejected; 9 models and 39 tests pass on backfill and recovery | Real |
| Duplicate rerun stability | PASS | `run_c6935cc7a829b51f4d5d`; same release/content, no source/load/freeze/switch, retained dbt evidence reused | Real |
| Targeted historical backfill isolation | PASS | Composition 30 added, 0 removed/replaced, 276 unchanged; every baseline value checked | Real |
| Quality failure blocks publication | PASS | `run_44ce952e71f3f5a83346`; real failing completeness test, exit 1, gate refusal, unchanged canonical/content | Fault-injected isolated copy |
| Correction and recovery | PASS | Fresh recovery candidate; release `release_a74a4772ee3b0338a041`; 39 tests pass | Real preserved inputs |
| Source-to-report reconciliation | PASS | 177=177=177/9 and 306=306=306/10; validation identity errors zero | Real |
| Reporting definitions, units, coverage, source dates | PASS | KES/foreign-unit mean; C mean; mm sum; per-location ranges and September independent check above | Real |
| Operator documentation | NOT VERIFIED | Commands updated in runbook; final editorial review intentionally deferred to Phase 5 | Documentation |

Phase 4 acceptance demonstrations pass. This matrix does not declare the whole
sprint complete; final documentation review, commits, and GitHub publication
remain out of scope.

## Independent post-implementation verification

Verification date: `2026-10-06` (Africa/Nairobi). This review reused the
recorded Phase 4 demonstrations and added only two bounded, read-only BigQuery
queries plus local manifest/evidence inspection. It did not repeat extraction,
warehouse builds, publication, export, or fault injection.

### Final canonical release and coverage

Read-only BigQuery job `a8a41451-0ea2-40bb-9163-3c50180dd334` processed
`146,394` bytes (`62,914,560` bytes billed; `1 GiB` maximum bytes billed). It
independently confirmed:

- Both canonical reporting views resolve to `release_a74a4772ee3b0338a041`.
- Exchange reporting contains `9` monthly rows backed by `177` observations.
- Weather reporting contains `10` monthly rows backed by `306` observations.
- Final weather coverage is Kisumu `2023-10-01` through `2023-12-31` (`92`
  observations), Mombasa `2023-10-01` through `2023-12-31` (`92`), and Nairobi
  `2023-09-01` through `2023-12-31` (`122`).
- The canonical release depends only on `batch_1fbe96c779d3e2aa706b` and
  `composition_a42482249b647d68ddaa`.

### Baseline preservation and intended additions

The same bounded query compared the accepted baseline landing records with the
final recovery landing records by business key and value, rather than inferring
preservation from aggregate counts:

- All `177` baseline exchange observations remain present and unchanged across
  their recorded fields and numeric values.
- All `276` baseline weather observations remain present and unchanged,
  including coordinates, time standard, temperature, precipitation, source,
  and source snapshot; numeric comparison tolerance was `1e-12`.
- Exactly `30` weather keys were added. Every addition is Nairobi on one of the
  dates `2023-09-01` through `2023-09-30`; there are `0` unintended added keys
  and `0` duplicate weather business keys.
- The corrected Nairobi `2023-09-15` record occurs exactly once in the final
  selected data.

### Live failure isolation and correction

The local manifest records failure run `run_44ce952e71f3f5a83346` at
`candidate_tests`, with no publication attempt and no release record for that
run. The captured live dbt invocation returned `1` on
`test.kep_warehouse.assert_weather_semantics_and_completeness`. Its candidate
load contained `177` exchange and `305` weather observations after the Nairobi
`2023-09-15` fault was injected.

During that failure, the canonical release remained
`release_00e432b9ddf0abe27a84`, and the recorded trusted report-content hash
remained
`98f23497a8c2b22b95a00f2e368760a637eb7a4da294caacede96681219a7e8b`
before and after the failed run. Read-only BigQuery job
`a4a729fb-4ffe-4f3b-8629-505ae5fdbed3` processed `2,126` bytes (`20,971,520`
bytes billed; `1 GiB` maximum bytes billed) and independently reconstructed all
`19` report rows from that frozen release dataset to the same hash.

The recovery run `run_50c96002b2ab247ef15d` is recorded as completed without
error. BigQuery metadata confirms the current canonical views reference
`kep_release_a74a4772ee3b0338a041`, not the isolated fault candidate dataset.
Together with the final `306`-row key/value comparison, the single restored
fault key, and the clean canonical source-batch set, this confirms that the
correction passed the real checks and that no fault-injected data is selected
by the final release.

### Acceptance-matrix audit

No unsupported PASS claim was found. Each PASS row is backed by the recorded
commands, manifests, bounded BigQuery results, or immutable release comparison
in this document. The matrix appropriately leaves operator documentation as
`NOT VERIFIED`; this independent review does not promote it. Claims about CI
remain limited to local command execution and do not assert that GitHub Actions
ran.

Independent verification result: **PHASE 4 PASS**.
