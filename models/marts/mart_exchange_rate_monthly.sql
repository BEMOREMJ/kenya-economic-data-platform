select
    currency_code,
    date_trunc(publication_date, month) as month_start,
    avg(mean_rate) as mean_published_daily_mean_rate_kes_per_foreign_unit,
    min(publication_date) as first_available_publication_date,
    max(publication_date) as last_available_publication_date,
    count(*) as publication_observation_count
from {{ ref('fact_exchange_rate_daily') }}
group by currency_code, month_start
