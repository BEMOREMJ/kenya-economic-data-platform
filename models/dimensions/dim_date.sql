select
    date_day,
    date_trunc(date_day, month) as month_start,
    extract(year from date_day) as calendar_year,
    extract(month from date_day) as calendar_month,
    extract(dayofweek from date_day) in (1, 7) as is_weekend
from unnest(generate_date_array(
    date('{{ var("scope_start_date") }}'),
    date('{{ var("scope_end_date") }}')
)) as date_day
