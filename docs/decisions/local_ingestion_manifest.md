# Local ingestion and manifest decision

Status: accepted for Phase 1 on 2026-10-05.

## Identity and atomicity

Scope identity hashes the source contract and request parameters. Content
identity hashes exact source bytes. Observation identity hashes canonical
accepted rows. This separates an upstream response-byte change from a change in
the analytical observations.

A completed batch is reused only after every artifact still matches its size
and SHA-256. `--refresh` bypasses reuse. Failed attempts are recorded separately
and cannot replace the last successful batch. Raw responses use content hashes
as filenames and are created via a temporary file plus atomic hard-link, so an
existing object is never overwritten. Candidate status is written last.

The ignored SQLite manifest records scopes, batches, artifacts, and attempts,
including outcome, elapsed time, request count, and sanitized error class.

## Source policies

CBK's official historical CSV has no bounded server-side selection, so its
pinned whole-file snapshot is filtered locally. Parsing permits only the two
observed date formats, maps the three currencies explicitly, requires positive
finite values and `buy <= mean <= sell`, rejects future dates, and analyzes
duplicates/conflicts across the whole file. A selected conflict blocks the
candidate; out-of-scope conflicts are quarantined and reported.

NASA POWER is requested once per representative city point with `community=AG`,
UTC, and only `T2M,PRECTOTCORR`. Fill value `-999` becomes null and blocks
readiness. Every date/location requires both measurements. Bounds are -90..60 C
for T2M and 0..2000 mm/day for precipitation. These are gridded estimates, not
station observations or city-wide averages.

HTTPS has distinct 10-second connect and 30-second read timeouts. Only transient
transport failures and HTTP 408/425/429/500/502/503/504 retry, with three total
attempts and a 10-second backoff/`Retry-After` cap. Permanent responses fail
immediately. Logs exclude credentials.

## Phase boundary

Schemas are BigQuery-compatible, but Phase 1 performs no warehouse action.
Local candidate readiness is recorded while warehouse counts remain explicitly
unverified/null for Phase 2.
