select
    cast(observation_date as date) as publication_date,
    cast(currency_code as string) as currency_code,
    cast(source_currency_label as string) as source_currency_label,
    cast(rate_type as string) as rate_type,
    cast(base_currency as string) as base_currency,
    cast(quote_currency as string) as quote_currency,
    cast(unit_multiplier as int64) as unit_multiplier,
    cast(mean_rate as numeric) as mean_rate,
    cast(buy_rate as numeric) as buy_rate,
    cast(sell_rate as numeric) as sell_rate,
    cast(source as string) as source,
    cast(batch_id as string) as batch_id,
    cast(source_snapshot_sha256 as string) as source_snapshot_sha256
from {{ source('candidate_landing', 'cbk_exchange_rates') }}
