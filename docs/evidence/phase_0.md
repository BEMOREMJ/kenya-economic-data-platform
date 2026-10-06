# Phase 0 evidence

Observed 2026-10-05 on Windows in
`C:\Users\Mark\Desktop\Personal Projects\Data Science\Kenya_economic_data_platform`.
No credentials, tokens, or private configuration are recorded here.

## Repository and tools

- Initial directory: empty and not a Git repository. No existing user work was
  overwritten. A new repository was initialized on branch `main`; final state is
  `No commits yet on main` with the Phase 0 files untracked. Nothing was committed,
  pushed, or published.
- Git: 2.49.0.windows.1.
- System `python`: 3.14.2; requested `py -3.12` was initially unavailable on
  PATH. `uv` located managed CPython 3.12.14 and created `.venv` from it.
- uv: 0.12.9.
- Initial `gcloud`, `bq`, and `dbt`: not found on PATH. Google Cloud SDK
  587.0.0 was then installed from the official Google installer via winget;
  `bq` 2.1.39 is included. A new shell may be needed before `gcloud` is on PATH.
- dbt dependencies selected: Core 1.12.5 and BigQuery adapter 1.12.1, Python
  3.12-compatible stable v1 releases. Installation/verification outcome is
  recorded in the closeout section below.

## Cloud readiness

- Explicit project ID requested: `elevated-legacy-457718-h2`.
- Project metadata: explicit read-only lookup succeeded for
  `elevated-legacy-457718-h2` (project number `546054437041`, lifecycle `ACTIVE`,
  created 2025-04-23). The global current-project setting remains unchanged.
- CLI authentication: one active account; its identifier is not recorded here.
- ADC: token mint succeeded with token output discarded. CLI login and ADC were
  verified independently.
- Billing status: read-only metadata returned `billingEnabled: false` and no
  billing account name.
- BigQuery: explicit `bq --project_id=elevated-legacy-457718-h2 ls` succeeded
  after adding the installed SDK directory to that process's PATH. It returned
  no dataset rows and created or modified nothing.
- No API was enabled, no global gcloud default changed, and no cloud resource,
  billing link, trial, or IAM policy was created or modified.

The cloud stop condition is cleared. Phase 0 still performs no dataset creation,
load, query job, API enablement, IAM change, trial activation, or billing action.

## Source checks

CBK and NASA results, semantics, licence findings, sanitized samples, and hashes
are recorded in `docs/source_inventory.md`. Summary:

- CBK: official page HTTP 200 HTML; official historical download HTTP 200
  `text/csv`; completed 2,082,067-byte CSV is parseable. The initial inspector
  reported 37,875 five-field records. Phase 2 clarified that the file contains
  37,877 total CSV records: 37,875 five-field records plus two malformed
  three-field records at parser positions 243–244. It contains
  37,281 unique date/currency keys, 594 duplicate rows, mixed date formats, and
  one invalid 2038 date. Usable coverage ends 2024-01-03; proposed-window
  result: 177 unique rows. Reuse licence
  remains unresolved even though CBK describes the rates as for public use.
- NASA POWER: HTTP 200 `application/json`; valid seven-day Nairobi response with
  API/source/time/units/fill metadata and 14 parameter-day values. NASA data are
  gridded model estimates, not station observations. NASA acknowledgement and
  provenance are required/recommended.
- Food prices: deferred; no source was adopted or substituted.

## Files created

- `.gitignore`, `.python-version`, `pyproject.toml`, `uv.lock`
- `README.md`
- `config/settings.example.toml`
- `src/kenya_economic_data/__init__.py` and `source_contracts.py`
- `tests/README.md` and `test_source_contracts.py`
- `scripts/inspect_phase0_samples.py`
- `docs/source_inventory.md`
- `docs/decisions/sandbox_strategy.md`
- `docs/evidence/phase_0.md`

Ignored local evidence includes response headers, the CBK page/CSV, and the NASA
JSON sample under `data/raw/phase_0/`. The incomplete first CBK transfer is also
ignored and is not used as evidence.

## Closeout

Checks to complete before changing the recommendation:

Completed local checks:

- `uv lock --check` and `uv sync --frozen`: passed; 110 packages resolved.
- Python 3.12.14; dbt Core 1.12.5; dbt-bigquery 1.12.1; pytest 8.4.2.
- `uv run pytest`: 3 passed in 0.11 seconds.
- Local source inspector: passed and reproduced the recorded hashes/counts.
- Google Cloud SDK 587.0.0 and `bq` 2.1.39 version checks: passed.
- Explicit project describe, billing describe, and `bq ls`: passed after the
  user completed CLI and ADC browser sign-in; no resource mutation occurred.

Restriction carried forward: confirm CBK redistribution terms before publicly
redistributing its raw file. Internal processing with provenance can proceed;
do not present the data as openly licensed.

Elapsed implementation time: approximately 55 minutes. Bounded discovery stayed
within each ceiling (CBK approximately 18 minutes, NASA POWER approximately 8
minutes, optional food-price review approximately 5 minutes).

Recommendation: **Phase 0 PASS**, with CBK raw-data public redistribution
restricted until its reuse terms are clarified. The repository, sources,
authentication, billing-disabled project, and read-only BigQuery access meet the
Phase 0 acceptance intent. Cloud architecture decisions remain proposals until
the separately authorized live Sandbox checks in Phase 2.

