# Resume bullets

- Built a personal Python/SQL/BigQuery/dbt batch platform that validates and
  reconciles 177 CBK exchange-rate and 306 NASA POWER weather observations into
  19 tested monthly reporting rows with source hashes and business-key lineage.
- Implemented gated publication through immutable-by-application release tables
  and one canonical BigQuery view; an isolated live missing-day fault failed dbt
  and left trusted report content unchanged before a clean 39-test recovery.
- Designed scoped backfill and idempotent recovery behaviour that added exactly
  30 Nairobi September records while preserving all 453 baseline exchange and
  weather observations unchanged, with bounded-query and zero-billing evidence.

