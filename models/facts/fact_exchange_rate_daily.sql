select
    publication_date,
    currency_code,
    mean_rate,
    buy_rate,
    sell_rate,
    rate_type,
    base_currency,
    quote_currency,
    unit_multiplier,
    source,
    batch_id,
    source_snapshot_sha256
from {{ ref('stg_exchange_rates') }}
