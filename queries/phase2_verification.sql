select
    'integrity' as kind, 'cbk_landing' as name,
    count(*) as row_count,
    count(distinct concat(cast(observation_date as string), '|', currency_code)) as unique_keys,
    cast(null as string) as value_1, cast(null as string) as value_2,
    cast(null as date) as first_date, cast(null as date) as last_date
from `elevated-legacy-457718-h2.kep_candidate_v1.landing_cbk__batch_1fbe96c779d3e2aa706b`
union all
select 'integrity', 'cbk_staging', count(*),
    count(distinct concat(cast(publication_date as string), '|', currency_code)),
    null, null, null, null
from `elevated-legacy-457718-h2.kep_candidate_v1.stg_exchange_rates`
union all
select 'integrity', 'cbk_fact', count(*),
    count(distinct concat(cast(publication_date as string), '|', currency_code)),
    null, null, null, null
from `elevated-legacy-457718-h2.kep_candidate_v1.fact_exchange_rate_daily`
union all
select 'integrity', 'weather_landing', count(*),
    count(distinct concat(cast(observation_date as string), '|', location_name)),
    null, null, null, null
from `elevated-legacy-457718-h2.kep_candidate_v1.landing_nasa_power__batch_5d09562b5edc416d16eb`
union all
select 'integrity', 'weather_staging', count(*),
    count(distinct concat(cast(observation_date as string), '|', location_name)),
    null, null, null, null
from `elevated-legacy-457718-h2.kep_candidate_v1.stg_weather`
union all
select 'integrity', 'weather_fact', count(*),
    count(distinct concat(cast(observation_date as string), '|', location_id)),
    null, null, null, null
from `elevated-legacy-457718-h2.kep_candidate_v1.fact_weather_daily`
union all
select 'metric', 'USD_2023_10', publication_observation_count, null,
    cast(mean_published_daily_mean_rate_kes_per_foreign_unit as string), null,
    first_available_publication_date, last_available_publication_date
from `elevated-legacy-457718-h2.kep_candidate_v1.mart_exchange_rate_monthly`
where currency_code = 'USD' and month_start = date '2023-10-01'
union all
select 'metric', 'Nairobi_2023_10', observed_day_count, expected_day_count,
    cast(mean_daily_temperature_c as string), cast(sum_daily_precipitation_mm as string),
    null, null
from `elevated-legacy-457718-h2.kep_candidate_v1.mart_weather_monthly`
where location_id = 'nairobi' and month_start = date '2023-10-01'
order by kind, name
