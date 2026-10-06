# Source inventory

Accessed on 2026-10-05 (Africa/Nairobi). Only bounded, read-only requests were
made. Local samples are under the ignored `data/raw/phase_0/` directory.

| Source | Retrieval pattern | Selected grain | Verified platform coverage | Main limitation |
|---|---|---|---|---|
| CBK historical exchange rates | Operator-downloaded, pinned full CSV; bounded local filtering | publication date × currency | USD/GBP/EUR, 2023-10-02 to 2023-12-29 | No explicit redistribution licence found; not a rolling feed |
| NASA POWER daily point | Bounded HTTPS request per configured point | UTC date × representative grid point | Nairobi 2023-09-01 to 2023-12-31; Mombasa/Kisumu 2023-10-01 to 2023-12-31 | Gridded model/assimilation estimate, not station observation |

## Central Bank of Kenya historical exchange rates

- Official landing page: https://www.centralbank.go.ke/rates/forex-exchange-rates/
- Official download: https://www.centralbank.go.ke/uploads/fx_rates/historical_data.csv
- Cadence and implemented use: the source is a complete historical-file
  download rather than a row-level API. The project pins the whole-file hash and
  filters the requested historical window locally. It does not claim a current
  or rolling exchange-rate feed.
- Selected grain and units: one publication date × USD/GBP/EUR, quoted as KES
  per one foreign unit. Weekends and holidays are absent rather than imputed.
- Evidence: landing page and CSV both returned HTTP 200. The CSV response was
  `text/csv`, `Content-Length: 2,082,067`, and last-modified 2024-01-04. A retry
  was required after one reset; the completed file matches `Content-Length`.
- Format: headerless CSV with five fields: date, currency label, mean, buy, sell.
  It is parseable, but dates are mixed (`DD/MM/YYYY` in an initial legacy block,
  then ISO `YYYY-MM-DD`). It contains duplicate `(date, currency)` records and a
  clearly invalid `2038-01-22` source row, so contract checks are mandatory.
- Observed usable coverage: 2007-08-06 through 2024-01-03 after rejecting the
  invalid future row. The page separately links annual files back to 2003; those
  were not adopted because the bounded three-month proposal is covered by the
  full download.
- Rate semantics in the downloaded series: CBK describes mean/buy/sell as indicative
  opening-of-trade averages from major market participants. Ordinary labels such
  as `US DOLLAR`, `STG POUND`, and `EURO` are KES per one foreign currency unit.
  `JPY (100)` is KES per 100 JPY. `KES / USHS`, `KES / TSHS`, `KES / RWF`, and
  `KES / BIF` reverse direction and express foreign units per KES. Labels must be
  mapped explicitly; a universal KES-per-unit assumption would be wrong.
- Current-series caveat: CBK's newer page describes rates from 2024-01-05 as a
  weighted average of registered interbank spot trades. That is a methodology
  boundary outside the proposed 2023 window.
- Licence/terms: CBK states the rates are compiled for use by the general public,
  but the exchange-rate page does not publish a clear data reuse licence. A
  search found a similarly named PDF that applies to government-securities CDS
  accounts, not website data. Attribute CBK and retain provenance, but do not
  redistribute the raw file publicly until CBK reuse terms are confirmed.
- Local SHA-256:
  `eaea9637cf763ea61ebb81661ed6471f50f79051cc983dff9cac072d92d8c677`.

Sanitized record example:

```text
2023-10-02,US DOLLAR,148.2015,148.1029412,148.3000
```

## NASA POWER daily weather

- Endpoint: https://power.larc.nasa.gov/api/temporal/daily/point
- Cadence and implemented use: one bounded daily API request per configured
  representative point, retrieved on demand by a human-operated local run.
- Selected grain: one UTC date × requested point, with T2M in degrees C and
  PRECTOTCORR in mm/day.
- Sample query: `parameters=T2M,PRECTOTCORR`, `community=AG`, longitude
  `36.8219`, latitude `-1.2921`, `start=20240101`, `end=20240107`,
  `format=JSON`, `time-standard=UTC`.
- Evidence: HTTP 200, `application/json`, valid JSON Feature payload, POWER Daily
  API v2.10.0, source `MERRA2`, returned point `[36.822, -1.292]` and elevation
  1642.2 m.
- Units and missing values: `T2M` is degrees C; `PRECTOTCORR` is mm/day; the
  payload declares `-999.0` as its fill value. Daily API supports UTC and Local
  Solar Time and defaults to LST, so UTC is always explicit here.
- Coverage: official documentation reports daily UTC/LST data from 1981-01-01 to
  near real time. The historical proposal avoids the mutable near-real-time tail.
- Semantics: POWER returns grid-cell estimates, not observations at a weather
  station. Meteorology is model/assimilation output (MERRA-2/GEOS-IT); source
  resolution is approximately 0.5 degrees latitude by 0.625 degrees longitude.
  Location coordinates select the containing grid estimate.
- Use/attribution: NASA Earth science data are generally free and open; NASA
  should be acknowledged and dataset/API provenance cited. NASA marks restricted
  third-party content separately; no restriction appeared in this API payload.
- Local SHA-256:
  `8c7d908431da99fb6c59841cb39d6d622baa0a7018bf6e9ad0edc6cc998bd7ef`.

Sanitized record examples:

```text
2024-01-01,Nairobi,T2M,20.9,C,UTC
2024-01-01,Nairobi,PRECTOTCORR,0.3,mm/day,UTC
```

Official references:

- https://power.larc.nasa.gov/docs/services/api/temporal/daily/
- https://power.larc.nasa.gov/docs/methodology/data/sources/
- https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy

## Optional Kenyan food prices — deferred

The World Bank's `KEN_2021_RTFP_v02_M` catalog was reviewed as a possible source.
It advertises monthly model-estimated prices for 233 markets (2007-01 through
2026-08), a market/admin coordinate schema, local-currency units, public/open
access, and a required citation. However, Kenya commodity observation coverage
shown in the catalog is low (for example, approximately 3.44% for beans and
5.42% for maize), most values are model estimates, and an exact licensed download
was not retrieved and parsed during this bounded check. It is semantically
different from observed retail prices. Food prices are therefore excluded from
the Phase 0 dataset rather than silently substituted.

Catalog reviewed: https://microdata.worldbank.org/index.php/catalog/6167/study-description

