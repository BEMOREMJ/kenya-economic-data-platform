with expected as (
    select month_start, count(*) as expected_day_count
    from {{ ref('dim_date') }}
    group by month_start
),
monthly as (
    select
        location_id,
        date_trunc(observation_date, month) as month_start,
        avg(mean_temperature_c) as mean_daily_temperature_c,
        case
            when countif(precipitation_mm_day is null) > 0 then null
            else sum(precipitation_mm_day)
        end as sum_daily_precipitation_mm,
        count(*) as observed_day_count,
        countif(precipitation_mm_day is null) as missing_precipitation_day_count
    from {{ ref('fact_weather_daily') }}
    group by location_id, month_start
)
select
    monthly.*,
    expected.expected_day_count
from monthly
join expected using (month_start)
