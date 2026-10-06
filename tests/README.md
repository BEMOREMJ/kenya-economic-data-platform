# Test plan

The Phase 1 suite is entirely local and uses synthetic fixtures. It covers:

- mixed CBK date formats and explicit USD/GBP/EUR quote semantics;
- exact duplicate collapse and conflicting-key rejection;
- NASA UTC/unit metadata, fill-value handling, completeness, and bounds;
- transient retry versus immediate permanent-failure behaviour;
- deterministic zero-request reuse and corrupt-artifact refusal; and
- preservation of a successful batch after a failed refresh.
- immutable warehouse load reuse, fingerprint checks, and failed-load recording.
- scoped backfill precedence and out-of-scope rejection;
- publication locking, gate failure, interrupted-attempt reconciliation, and
  frozen candidate namespace enforcement; and
- single canonical-view SQL without DML.

Run `uv run pytest -q -p no:cacheprovider` from the repository root. Tests do
not call live sources or cloud services.

