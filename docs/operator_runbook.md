# Operator runbook

This is a local, laptop-driven pipeline. It is not a managed scheduler: a
powered-off, sleeping, or disconnected laptop cannot run it.

The runbook assumes Python 3.12 and the frozen `uv.lock`. Application Default
Credentials, source downloads, local settings/profiles, the SQLite manifest,
exports, logs, and generated dbt artifacts must stay outside Git. Before cloud
work, confirm the project/location explicitly and verify that billing is not
attached. Stop if project ownership, dataset ownership, location, or billing
state is uncertain.

## Normal execution and safe rerun

From the repository root in PowerShell:

```powershell
$ProjectId = "YOUR_GCP_PROJECT"
$env:GOOGLE_CLOUD_PROJECT = $ProjectId
uv run python -m kenya_economic_data operate `
  --project $ProjectId --location US `
  --candidate-dataset kep_candidate_v1 `
  --trusted-dataset kep_trusted_v1 `
  --start-date 2023-10-01 --end-date 2023-12-31 `
  --locations Nairobi Mombasa Kisumu
```

Run the same command again after an interruption. The exclusive local lock
prevents concurrent executions. Source artifacts, landing tables, dbt evidence,
frozen release tables, and the current canonical pointer are reused only when
their identities and fingerprints match. If BigQuery already exposes a release
after a crash but the local publication attempt is still `running`, BigQuery is
treated as authoritative and the manifest is reconciled to
`published_recovered`.

A failure before the publication call leaves the canonical release unchanged.
Inspect the emitted stage/error and `health`; correct the input/configuration or
use a fresh candidate namespace when identity changed. Do not manually mark a
failed run complete. The isolated Phase 4 live failure and recovery are recorded
in `docs/evidence/phase_4.md`.

## Health and export recovery

```powershell
uv run python -m kenya_economic_data health `
  --project $ProjectId --location US `
  --trusted-dataset kep_trusted_v1

uv run python -m kenya_economic_data retry-export `
  --project $ProjectId --location US `
  --trusted-dataset kep_trusted_v1 `
  --release-id RELEASE_ID
```

Health reports the latest attempt separately from the latest successful
published release. It includes stage failures, counts, coverage, retrieval and
observation dates, recorded query bytes, and release-table expiration. States
include `never_published` and `expired_requires_reconstruction`.

An export failure after publication does not undo the warehouse switch. Retry
only the exports with `retry-export`; it does not extract, load, build, freeze,
or republish. Successful export also regenerates the ignored standalone results
dashboard from the two trusted domain summaries.

Regenerate or open the dashboard without cloud access:

```powershell
$ReleaseId = "release_a74a4772ee3b0338a041"
uv run python -m kenya_economic_data render-dashboard `
  --report-dir "data\reports\$ReleaseId"
Start-Process "data\reports\$ReleaseId\results_dashboard.html"
```

The renderer reads only `exchange_summary.csv`, `weather_summary.csv`, and their
metadata in the selected release directory. It refuses mismatched release IDs,
domains, coverage metadata, or duplicate reporting keys. It never reads raw,
candidate, or fault-injected data.

## Scoped backfill composition

First create and validate a replacement source batch for only the intended date
and entity scope. For CBK, use an ignored custom settings file when selecting a
currency subset. Then compose the effective full input:

```powershell
uv run python -m kenya_economic_data compose-backfill `
  --source cbk `
  --baseline-batch-id BASELINE_BATCH `
  --replacement-batch-id REPLACEMENT_BATCH `
  --start-date 2023-11-01 --end-date 2023-11-30 `
  --selections USD
```

For weather use `--source nasa` and location names in `--selections`. The
replacement is authoritative only inside the declared scope. Missing baseline
keys inside that scope are recorded as removals; new keys are additions;
different overlaps are replacements. Baseline rows outside the scope are
preserved. Duplicate keys or replacement rows outside the scope fail.

The result is a new candidate-ready manifest batch. Supply a **new** distinctive
candidate dataset to `operate`, for example `kep_candidate_backfill_202311_v1`.
The command performs a complete tiny-table reconstruction and fresh dbt build;
it does not perform an incremental warehouse update or DML. Changed inputs or
models are refused if the operator tries to reuse a candidate namespace already
associated with a published release.

For asymmetric coverage, explicitly select both verified effective inputs. This
prevents the narrower replacement batch from replacing the platform's full
input selection. Example:

```powershell
uv run python -m kenya_economic_data operate `
  --project $ProjectId --location US `
  --candidate-dataset kep_candidate_backfill_202309_nairobi_v1 `
  --trusted-dataset kep_trusted_v1 `
  --start-date 2023-09-01 --end-date 2023-12-31 `
  --locations Nairobi Mombasa Kisumu `
  --cbk-batch-id batch_1fbe96c779d3e2aa706b `
  --nasa-batch-id composition_a42482249b647d68ddaa
```

The orchestrator derives expected counts, monthly grains, and per-location date
ranges from the verified effective inputs. Explicit batch IDs must belong to the
correct source and pass artifact fingerprint verification.

The accepted Phase 4 Nairobi September composition added exactly 30 keys,
preserved all 276 baseline weather keys/values, and was recovered into canonical
release `release_a74a4772ee3b0338a041`.

## Rollback

```powershell
uv run python -m kenya_economic_data rollback `
  --project $ProjectId --location US `
  --trusted-dataset kep_trusted_v1
```

Rollback is allowed only when a previous release is recorded and both of its
frozen domain tables still exist. It performs one canonical-view replacement
and verifies the resulting release ID. The first release has no rollback target.

## Expiration recovery

Sandbox objects expire. If health reports an expired release or candidate:

1. Preserve and inspect the local manifest and accepted artifacts.
2. Rerun `operate` with an appropriate new candidate namespace if inputs/models
   changed; use the existing namespace only for identical inputs/model identity.
3. Missing landing/model/release tables are reconstructed in full.
4. Fresh load counts, dbt tests, reconciliation, reporting coverage, frozen-table
   validation, and switch verification are required.

An expired/missing relation invalidates completion evidence. The pipeline never
reports it reusable merely because a local success row exists.

If both BigQuery objects and required ignored local artifacts are gone, the old
release cannot be reconstructed from this public repository alone. Re-obtain
and re-verify the official source, create new immutable batches, and execute all
gates into new candidate/release resources.

## Publication guarantee and boundary

Frozen release tables are built and validated before publication. The only
release pointer is `kep_trusted_v1.canonical_release`, replaced in one DDL
statement. Fixed exchange/weather convenience views always filter that canonical
view and are not independently switched.

A failed prepublication stage cannot change the canonical view. After a switch,
the view is queried to verify exactly one expected release ID before local
success is recorded. Separate consumer queries executed on opposite sides of a
switch can observe different releases; this is not a multi-query transaction or
snapshot guarantee.

Release immutability is enforced by application behaviour: releases are created
once, identity-checked, and never updated by the code. It is not an assertion
that IAM prevents every manual change by a privileged project operator.

## dbt troubleshooting and documentation

The orchestrator supplies its selected landing table names and effective scope
to dbt. For manual diagnosis, use the same values shown in the failed/successful
run evidence; do not silently substitute a “latest” table. A connected rebuild
is:

```powershell
uv run dbt build --profiles-dir config --exclude tag:sandbox_probe `
  --full-refresh --no-partial-parse
```

To generate a connected catalog and serve it locally:

```powershell
uv run dbt docs generate --profiles-dir config --exclude tag:sandbox_probe `
  --no-partial-parse --static
uv run dbt docs serve --profiles-dir config
```

For offline structural documentation, use `--empty-catalog --no-compile`; this
validates parsed lineage but does not prove warehouse relations or data.

## Operational decision guide

| Condition | Safe response |
|---|---|
| Same command after interruption | Rerun; matching identities are reused and authoritative publication can repair the local record. |
| Extraction or contract failure | Inspect ignored rejected/reconciliation artifacts; do not load. |
| dbt test or reconciliation failure | Do not publish; preserve the trusted view and use a fresh corrected candidate where identity changed. |
| Publication succeeded but local recording failed | Rerun; verify BigQuery canonical state, then reconcile the manifest. |
| Local export failed after publication | Run `retry-export`; do not rebuild or republish. |
| Current release is wrong but prior frozen release exists | Inspect health, then run `rollback`; the first release has no rollback target. |
| Candidate/release expired | Reconstruct in full and repeat all validation gates. |
| Local manifest/source artifacts lost | Re-acquire and verify sources; old public code/evidence alone is insufficient. |
