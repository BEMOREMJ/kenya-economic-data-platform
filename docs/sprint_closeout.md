# Sprint closeout

## Outcome

The personal Kenya Economic Data Platform is implemented, accepted, documented,
and rehearsed for another operator. It extracts or reuses bounded verified
inputs, records immutable local evidence, loads owned BigQuery Sandbox
candidates, builds/tests dbt models, reconciles source-to-fact-to-report counts,
freezes releases, and moves one canonical reporting pointer only after critical
gates pass.

Final canonical release: `release_a74a4772ee3b0338a041`.

| Domain | Landing observations | Daily fact rows | Monthly report rows |
|---|---:|---:|---:|
| CBK exchange | 177 | 177 | 9 |
| NASA POWER weather | 306 | 306 | 10 |

Exchange covers 59 CBK publication dates for USD/GBP/EUR from 2023-10-02 to
2023-12-29. Weather covers Nairobi from 2023-09-01 to 2023-12-31 (122 days) and
Mombasa/Kisumu from 2023-10-01 to 2023-12-31 (92 days each).

## Implemented capabilities

- Pinned-source provenance, content-addressed artifacts, validation,
  quarantine/reconciliation, stable business-key identities, and safe reuse.
- Explicit immutable candidate loads with ownership/schema/fingerprint checks.
- Nine dbt models: typed staging, three dimensions, two daily facts, and two
  monthly marts, protected by schema and singular critical tests.
- One local orchestrator with a concurrency lock, deterministic stages,
  prepublication gates, frozen releases, canonical view publication, health,
  scoped composition, rollback, and export-only retry.
- Asymmetric historical backfill that preserved all out-of-scope keys/values.
- Recovery after live quality failure and after publication/local-recording
  interruption, with Sandbox-expiration reconstruction documented.
- Offline Windows setup, behavioral tests, dbt parse, and static dbt lineage
  documentation rehearsed from a clean publication-only copy.

## Final nine-gate acceptance matrix

| Gate | Result | Evidence |
|---|---|---|
| 1. End-to-end BigQuery execution | PASS | [Phase 3](evidence/phase_3.md), [Phase 4](evidence/phase_4.md) |
| 2. Critical ingestion and dbt checks | PASS | [Phase 1](evidence/phase_1.md), [Phase 2](evidence/phase_2.md), [Phase 4](evidence/phase_4.md) |
| 3. Duplicate rerun stability | PASS | [Phase 3](evidence/phase_3.md), [Phase 4](evidence/phase_4.md) |
| 4. Targeted historical backfill isolation | PASS | [Phase 4](evidence/phase_4.md) |
| 5. Quality failure blocks publication | PASS | [Phase 4](evidence/phase_4.md) |
| 6. Correction and recovery | PASS | [Phase 3](evidence/phase_3.md), [Phase 4](evidence/phase_4.md) |
| 7. Source-to-report reconciliation | PASS | [Phase 2](evidence/phase_2.md), [Phase 4](evidence/phase_4.md) |
| 8. Reporting definitions, units, coverage, source dates | PASS | [Source inventory](source_inventory.md), [models](warehouse_models.md), [Phase 4](evidence/phase_4.md) |
| 9. Operator documentation | PASS | [Phase 5 rehearsal](evidence/phase_5.md), [README](../README.md), [runbook](operator_runbook.md) |

## Reconciliation and content preservation

The final exchange chain is `177 landing = 177 fact = 177 report-observation
count`, producing 9 unique currency/month keys. The weather chain is `306
landing = 306 fact = 306 report-observation count`, producing 10 unique
location/month keys. Frozen release validation reported zero identity errors.

Independent key/value comparison found all 177 baseline exchange and 276
baseline weather observations unchanged. Exactly 30 Nairobi dates from
2023-09-01 through 2023-09-30 were added, with zero unintended keys and no
duplicate weather business keys.

## Real and synthetic demonstrations

Real data and cloud demonstrations used the pinned official CBK historical file,
bounded NASA POWER responses, real BigQuery Sandbox candidate/release tables,
and live dbt builds. The backfill's 30 observations were real NASA data.

The quality-failure demonstration used an explicitly labelled, isolated copy of
verified real inputs with one deliberately omitted Nairobi date. It was not
published. Offline behavioral tests and the small files under `tests/fixtures/`
are synthetic/mock evidence for edge cases and control flow; they are not
reported as real observations.

## Failure and recovery result

The isolated 305-row weather candidate failed the live completeness test and
the independent publication count gate. No publication attempt or release
record was created, while the canonical ID and trusted 19-row content hash
remained unchanged. Clean recovery restored the missing key, passed 39 dbt
tests, reconciled the final counts, and published the final release. Independent
Phase 4 review confirmed that the canonical views do not reference the fault
dataset.

## Cost and usage evidence

Billing remained disabled throughout all recorded cloud work; no billing link
or paid service was enabled. BigQuery still reports bytes billed under its
minimum accounting granularity. Available evidence includes:

- Phase 2 candidate dbt jobs: 213,138 bytes processed and 608,174,080 bytes
  billed; separate reconciliation: 144 processed and 62,914,560 billed.
- Phase 3 first publication jobs: 5,085 bytes processed and 167,772,160 billed.
- Phase 4 cloud window: 291 jobs, 1,149,054 bytes processed and 3,166,699,520
  billed; four loads used 168,976 input and 179,760 output bytes.
- Independent final Phase 4 read-only checks: 148,520 bytes processed and
  83,886,080 bytes billed across two successful bounded queries.

These phase figures are recorded separately rather than summed because their
collection scopes differ. Every application query retained a 1 GiB cap.

## Timeline

Evidence records initial environment/source discovery on 2026-10-05, the first
trusted release across 2026-10-05/06, and Phase 4 acceptance on 2026-10-06. The
Phase 4 cloud-job window was 25 minutes 37.928 seconds. No reliable end-to-end
active-work timer exists, so this closeout does not infer total working hours
from message or file timestamps.

## Known limitations

- CBK redistribution terms are unresolved; raw records and substantial derived
  datasets are excluded from the public snapshot.
- CBK ingestion filters a pinned whole-file download and is not a rolling feed.
- NASA POWER is a grid-cell estimate, not station or whole-city observation.
- BigQuery Sandbox candidate/release objects expire (configured for 60 days).
- Straightforward reconstruction depends on ignored local sources and manifest;
  if lost, sources must be obtained and verified again.
- Immutability is enforced by application behaviour, not absolute IAM denial of
  all privileged manual changes.
- The laptop is the operator and scheduler; availability is not guaranteed.
- Floating aggregation requires the documented numeric tolerance.
- GitHub Actions has passed only as a local command rehearsal; it has not run on
  GitHub and has no cloud credentials.

## Recommended next work

1. Create a public GitHub repository after an owner visibility review, add the
   remote, push `main`, and observe the first GitHub Actions run.
2. Resolve CBK reuse/licensing terms before publishing raw or substantial
   derived exchange data.
3. Add durable artifact backup and a recovery drill that does not depend on one
   laptop, while preserving credential/data exclusions.
4. Add least-privilege service identities and production-grade IAM only if the
   project moves beyond Sandbox/personal operation.
5. Consider managed scheduling/monitoring only after defining freshness,
   ownership, cost controls, and an updated-source contract.

## Handoff summary

This project demonstrates hands-on Python, SQL, BigQuery, and dbt data
engineering on a deliberately small but rigorously verified scope. It turns 483
final daily historical observations into 19 monthly report rows, preserves
source and batch lineage, blocks publication on critical data-quality failure,
supports deterministic reruns and scoped backfills, and documents recovery and
Sandbox-expiration limits without claiming production scale or business impact.

