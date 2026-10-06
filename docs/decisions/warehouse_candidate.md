# Phase 2 warehouse candidate design

Status: accepted for candidate evaluation on 2026-10-05. Nothing in this design
is a trusted or published interface.

## Namespaces and lifecycle

All resources use project `elevated-legacy-457718-h2`, location `US`, and a
distinctive `kep_` prefix:

- `kep_sandbox_probe_v1`: isolated synthetic compatibility probe.
- `kep_candidate_v1`: immutable landing tables and candidate dbt models.

Both datasets carry `kep_owner=kenya_economic_data_platform` and phase labels.
Their default table and partition expiration is 5,184,000,000 ms (60 days).
Sandbox state is disposable: recreate datasets, rerun immutable manifest-driven
loads, then run `dbt build` and `dbt docs generate`. No existing dataset is
adopted without the ownership label.

After rechecking that billing is disabled and that the names are absent, the
datasets can be recreated with explicit project/location and expiration:

```powershell
bq --project_id=elevated-legacy-457718-h2 --location=US mk --dataset `
  --default_table_expiration=5184000 `
  --label=kep_owner:kenya_economic_data_platform `
  --label=kep_phase:phase2_probe `
  elevated-legacy-457718-h2:kep_sandbox_probe_v1

bq --project_id=elevated-legacy-457718-h2 --location=US mk --dataset `
  --default_table_expiration=5184000 `
  --label=kep_owner:kenya_economic_data_platform `
  --label=kep_phase:phase2_candidate `
  elevated-legacy-457718-h2:kep_candidate_v1
```

## Loading

Landing names include the immutable Phase 1 batch ID. They contain typed landing
records derived from accepted artifacts, not byte-for-byte source responses.
The loader uses explicit schemas and local-file load jobs with `WRITE_EMPTY`.
Before reuse it verifies the local artifact and compares destination row count,
schema fingerprint, batch/artifact/schema labels, location, and ownership.

Load attempts and completed loads are separate SQLite records. A table that
exists after a client interruption can be recovered only if all fingerprints
match. A mismatched table fails; it is never appended to or replaced.

## dbt execution

The ignored OAuth profile uses ADC, two threads, explicit project/dataset/US
location, and `maximum_bytes_billed: 1073741824`. This is a per-query guard, not
a total budget. Staging objects are views; dimensions, facts, and marts are
tables created using `CREATE OR REPLACE TABLE AS SELECT`. No incremental model,
snapshot, DML, `MERGE`, or trusted/public view is present.
