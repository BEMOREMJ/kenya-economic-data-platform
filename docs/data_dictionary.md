# Data dictionary

This dictionary describes the implemented ingestion, warehouse, and canonical
reporting fields. Physical types shown for landing data follow the checked-in
BigQuery schemas.

## CBK accepted landing record

Grain: one CBK publication date × selected currency. Business key:
`(observation_date, currency_code)`.

| Field | BigQuery type | Meaning |
|---|---|---|
| `observation_date` | DATE | CBK publication date. |
| `currency_code` | STRING | Normalized `USD`, `GBP`, or `EUR`. |
| `source_currency_label` | STRING | Original CBK label used for the explicit mapping. |
| `rate_type` | STRING | `indicative_opening_mean_buy_sell` for this historical series. |
| `base_currency` | STRING | Selected foreign currency code. |
| `quote_currency` | STRING | `KES`. |
| `unit_multiplier` | INTEGER | `1`; the selected rates are per one foreign unit. |
| `mean_rate` | NUMERIC | Published mean, KES per foreign currency unit. |
| `buy_rate` | NUMERIC | Published buy rate in the same quotation. |
| `sell_rate` | NUMERIC | Published sell rate in the same quotation. |
| `source` | STRING | `CBK`. |
| `batch_id` | STRING | Immutable extraction/composition identity. |
| `source_snapshot_sha256` | STRING | SHA-256 provenance for the downloaded source bytes. |

Rejected CBK artifacts retain source row number, five raw values, and a reason.
They stay in ignored local storage and are not warehouse facts.

## NASA POWER accepted landing record

Grain: one UTC date × configured representative point. Business key:
`(observation_date, location_name)`.

| Field | BigQuery type | Meaning |
|---|---|---|
| `observation_date` | DATE | UTC observation date. |
| `location_name` | STRING | `Nairobi`, `Mombasa`, or `Kisumu`. |
| `latitude` | FLOAT64 | Requested representative-point latitude. |
| `longitude` | FLOAT64 | Requested representative-point longitude. |
| `time_standard` | STRING | `UTC`. |
| `t2m_c` | FLOAT64 | NASA POWER T2M daily mean temperature, degrees C. |
| `prectotcorr_mm_day` | FLOAT64 | Corrected precipitation for the day, mm/day. |
| `source` | STRING | NASA POWER source identifier. |
| `batch_id` | STRING | Immutable extraction/composition identity. |
| `source_snapshot_sha256` | STRING | SHA-256 provenance for the API payload. |

Rejected weather rows retain date, location, raw measurements, and a reason.
The `-999.0` fill value is rejected rather than treated as a measurement.

## Staging and daily facts

`stg_exchange_rates` renames `observation_date` to `publication_date` and casts
the landing fields explicitly. `fact_exchange_rate_daily` preserves the same
business key and measurement/provenance fields.

`stg_weather` renames `t2m_c` to `mean_temperature_c` and
`prectotcorr_mm_day` to `precipitation_mm_day`.
`fact_weather_daily` lowercases `location_name` to `location_id` and preserves
the date, measurements, time standard, and provenance.

Dimensions contain:

- `dim_date`: `date_day`, `month_start`, `year_number`, and `month_number`;
- `dim_currency`: selected code, quotation direction, unit multiplier, and
  description; and
- `dim_location`: lowercase location ID, display name, representative
  coordinates, and point/grid limitation.

## Monthly marts and canonical reports

| Field | Domain | Meaning |
|---|---|---|
| `release_id` | both canonical reports | Frozen release identity. |
| `source_batch_id` | both | Verified effective input identity. |
| `domain` | canonical union | `exchange` or `weather`. |
| `month_start` | both | First calendar day of the reporting month. |
| `currency_code` | exchange | `USD`, `GBP`, or `EUR`; null for weather. |
| `location_id` | weather | Lowercase point identifier; null for exchange. |
| `mean_published_daily_mean_rate_kes_per_foreign_unit` | exchange | Arithmetic mean of available published daily CBK means. |
| `first_available_publication_date` | exchange | First CBK publication date used that month. |
| `last_available_publication_date` | exchange | Last CBK publication date used that month. |
| `publication_observation_count` | exchange | Number of daily publication records aggregated. |
| `mean_daily_temperature_c` | weather | Arithmetic mean of complete daily T2M values. |
| `sum_daily_precipitation_mm` | weather | Sum of complete daily PRECTOTCORR values. |
| `observed_day_count` | weather | Daily rows in that location/month. |
| `expected_day_count` | weather | Calendar dates expected for that location/month scope. |
| `missing_precipitation_day_count` | weather mart/release | Null precipitation inputs; required to be zero before publication. |
| `metric_definition` | canonical reports | Human-readable units and formula summary. |

`missing_precipitation_day_count` exists on the mart and frozen weather table;
the fixed consumer convenience view exposes the validated counts and metrics
but omits this always-zero diagnostic column.

