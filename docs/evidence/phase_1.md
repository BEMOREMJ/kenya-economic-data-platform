# Phase 1 acceptance evidence

Recorded 2026-10-05 (Africa/Nairobi). This is sanitized evidence; generated raw
data, candidates, logs, and the SQLite manifest remain ignored local state.

## Scope and result

- Window: 2023-10-01 through 2023-12-31 inclusive.
- CBK: USD/GBP/EUR; scope `scope_bea223740d6a057c46bc`; batch
  `batch_1fbe96c779d3e2aa706b`.
- CBK raw SHA-256: `eaea9637cf763ea61ebb81661ed6471f50f79051cc983dff9cac072d92d8c677`.
- CBK observation SHA-256: `0f1352fb230bd3b6c91eae96dfa3d8684e2870d2415b9124f0d17deffa0b26e9`.
- CBK accepted 177 unique rows over 59 complete publication dates; zero
  selected duplicates or conflicts; zero requests (verified local snapshot).
- NASA: Nairobi/Mombasa/Kisumu, T2M/PRECTOTCORR, AG, UTC; scope
  `scope_e0d54bd3255dfad40dbe`.
- NASA accepted 276 rows (92 dates x 3 points), zero rejected; all three initial
  requests returned HTTP 200 on their first attempt.

CBK reconciliation passed:

```text
37,877 source = 25 invalid + 36,613 excluded-date
                + 1,062 excluded-currency + 177 selected
177 selected = 177 accepted + 0 exact-duplicate + 0 conflict-row
```

The rejected artifact has 235 rows: 25 invalid plus 210 rows from 105
whole-file conflict keys outside the selected scope. The source also has 488
additional exact-duplicate rows. These whole-file duplicate/conflict values are
overlapping diagnostics over valid records, not extra additive terms in the
source-partition equation. Weekends/holidays are not synthesized. A 2038 future
record was rejected; the maximum valid source date was 2024-01-03.

NASA reconciliation passed globally and per location: 276 expected = 276
accepted + 0 rejected, with 92 unique dates per point and no missing, extra,
invalid, or fill-valued observations. Metadata reported POWER Daily API v2.10.0,
MERRA2, UTC, C, mm/day, and fill value `-999.0`.

## Versioning and rerun proof

Initial NASA batch `batch_5936876895e1d3e00eb9` had combined content SHA-256
`eb1807f2bb9084056933ba4cc91456920043e0012d2880295403400a34419ad4`.
An explicit refresh made three first-attempt HTTP 200 requests and created batch
`batch_5d09562b5edc416d16eb` with content SHA-256
`7ab1c2c781b196a543d5008658241e740fd889eefe38ac0c35ab56d07ff04705`.
Both have observation SHA-256
`b89441303df9e1fdfb217382319be660a3c529962b0d3cf2c3df23be3a8c4d54`.
Thus changed response bytes produced an immutable new version while normalized
observations remained stable.

A combined no-refresh rerun verified and reused both source batches with zero
HTTP requests (CBK attempt `attempt_a0f60827454e4afebbb4ff7522a8e2e9`, initial
NASA attempt `attempt_e98b3544f89d4f3f81f19e5039570198`). After the NASA
refresh, another no-refresh run selected the new latest batch with zero requests
(`attempt_24a0490f4e1940e28f136fc366bbcc58`).

## Verification and recommendation

`uv run pytest -q -p no:cacheprovider` completed with `10 passed in 0.64s`.
Tests cover parsing, duplicate/conflict and fill handling, reconciliation,
transient/permanent HTTP failures, zero-request reuse, failed-refresh recovery,
and corrupt-artifact refusal.

**PASS for Phase 1 local extraction.** Both candidates are locally ready for a
later warehouse phase. Do not redistribute the CBK raw snapshot until reuse
terms are clarified. Phase 2 must separately prove BigQuery Sandbox loading,
schema enforcement, warehouse counts, and publication mechanics. No cloud or
warehouse mutation was performed in Phase 1.
