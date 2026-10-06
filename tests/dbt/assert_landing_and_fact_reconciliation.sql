with checks as (
    select 'cbk_landing' as check_name, count(*) as actual, {{ var('cbk_expected_rows') }} as expected
    from {{ source('candidate_landing', 'cbk_exchange_rates') }}
    union all
    select 'cbk_staging', count(*), {{ var('cbk_expected_rows') }} from {{ ref('stg_exchange_rates') }}
    union all
    select 'cbk_fact', count(*), {{ var('cbk_expected_rows') }} from {{ ref('fact_exchange_rate_daily') }}
    union all
    select 'cbk_monthly_observations', sum(publication_observation_count), {{ var('cbk_expected_rows') }}
    from {{ ref('mart_exchange_rate_monthly') }}
    union all
    select 'weather_landing', count(*), {{ var('weather_expected_rows') }}
    from {{ source('candidate_landing', 'nasa_weather') }}
    union all
    select 'weather_staging', count(*), {{ var('weather_expected_rows') }} from {{ ref('stg_weather') }}
    union all
    select 'weather_fact', count(*), {{ var('weather_expected_rows') }} from {{ ref('fact_weather_daily') }}
    union all
    select 'weather_monthly_observations', sum(observed_day_count), {{ var('weather_expected_rows') }}
    from {{ ref('mart_weather_monthly') }}
)
select * from checks where actual != expected
