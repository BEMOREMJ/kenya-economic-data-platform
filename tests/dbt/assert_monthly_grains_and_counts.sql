select 'exchange_month_rows' as check_name, count(*) as actual, {{ var('cbk_expected_monthly_rows', 9) }} as expected
from {{ ref('mart_exchange_rate_monthly') }}
having count(*) != {{ var('cbk_expected_monthly_rows', 9) }}
union all
select 'weather_month_rows', count(*), {{ var('weather_expected_monthly_rows', 9) }}
from {{ ref('mart_weather_monthly') }}
having count(*) != {{ var('weather_expected_monthly_rows', 9) }}
union all
select 'weather_incomplete_months', count(*), 0
from {{ ref('mart_weather_monthly') }}
where observed_day_count != expected_day_count
having count(*) != 0
