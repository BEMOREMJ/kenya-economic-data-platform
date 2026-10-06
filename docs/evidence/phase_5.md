# Phase 5 documentation and operator-verification evidence

Recorded 2026-10-06 (Africa/Nairobi). Phase 5 changed documentation and
public-snapshot configuration only. It did not modify cloud data, rerun an
acceptance demonstration, create a GitHub repository, or push a branch.

## Clean operator rehearsal

A rehearsal copy was created outside the working repository at a unique path
under `%TEMP%`. It contained only the 78 files returned at that point by
`git ls-files --cached --others --exclude-standard`; ignored credentials,
profiles, source/processed data, SQLite manifests, exports, logs, caches,
virtual environments, and generated dbt artifacts were absent.

The first `uv sync --frozen --dev` attempt was correctly blocked by the
restricted execution environment's network policy. It also revealed that a
multi-command PowerShell rehearsal needs explicit `$LASTEXITCODE` guards for
external executables. The same frozen install was rerun with package-download
permission and exit guards; no repository or dependency change was needed.

The clean-copy results were:

| Check | Result |
|---|---|
| `uv sync --frozen --dev` | PASS; 110 locked packages installed |
| Python | PASS; 3.12.14 |
| dbt | PASS; Core 1.12.5, BigQuery 1.12.1 |
| top-level and `operate` CLI help | PASS; documented commands/flags exist |
| `config/settings.example.toml` load | PASS; three locations and pinned CBK hash validated |
| Python compile | PASS |
| `pytest -q -p no:cacheprovider` | PASS; 22 tests in 4.53 seconds |
| `dbt parse --profiles-dir config --no-partial-parse` | PASS with offline identifiers |
| offline static dbt docs generation | PASS; `target/static_index.html` created with `--empty-catalog --no-compile` |

No ADC was copied into the rehearsal. No online extraction, BigQuery load/build,
publication, health query, rollback, or export was executed. Those documented
commands were checked against CLI help and the successful Phase 1–4 command
evidence. Offline docs use an empty catalog and are not represented as a fresh
warehouse verification.

**Acceptance gate 9: PASS.** The README/runbook are sufficient for a clean
local setup and accurately distinguish offline rehearsal, authenticated cloud
execution, and prior verified releases.

## Documentation review

The README now leads with the portfolio purpose, architecture, final verified
release/counts, prerequisites, frozen Windows setup, ADC handling, explicit
project/location variables, zero-billing constraint, actual CLI commands,
pinned full-file CBK workflow, verified coverage, and limitations. The source
inventory, data dictionary, warehouse lineage/formulas, runbook, portfolio case
study, resume bullets, and sprint closeout describe the current implementation.

The docs explicitly distinguish application-enforced release immutability from
protection against every possible manual change by a privileged BigQuery
operator. GitHub Actions is described only as offline code validation—not a
scheduled warehouse run.

## Public-snapshot review

Before staging, publication candidates were enumerated explicitly rather than
with blanket staging. The ignored-state check confirmed local profiles,
`.venv`, logs, and dbt `target/` were excluded; `.gitignore` also excludes raw,
staging, processed, manifest, report, credential, cache, and temporary paths.
Only small fixtures labelled under `tests/fixtures/` are candidates. No CBK raw
records or substantial derived dataset is included.

Pattern scanning and manual configuration/evidence review found no private-key
block, Google API key, populated client secret/private key, access token, or
credential file. A zero-match scan is supporting evidence, not a guarantee;
the intended file list and non-secret templates were also manually reviewed.
After adding this evidence and the sprint closeout, the final reviewed staging
set contains 80 files; the largest is the 168,531-byte dependency lockfile, and
no publication candidate is a raw or generated dataset.
The real Google Cloud project identifier remains in historical sanitized
evidence and acceptance-only verification utilities; it is an identifier, not
an authentication secret. Account identifiers and tokens are absent.

Git has no configured remote. The GitHub CLI is not installed, so authenticated
account/repository metadata and destination visibility could not be queried.
There is therefore no existing Git destination or visibility to report from
local Git configuration, and no remote was created or pushed.

## CI status

The workflow commands passed in the clean local rehearsal. GitHub Actions has
not run because no remote repository exists and nothing has been pushed. The
workflow has no cloud credentials and performs compile, offline tests, and dbt
parse only.

