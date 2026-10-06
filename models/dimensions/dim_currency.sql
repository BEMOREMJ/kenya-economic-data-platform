select distinct
    currency_code,
    source_currency_label,
    base_currency,
    quote_currency,
    unit_multiplier,
    rate_type
from {{ ref('stg_exchange_rates') }}
