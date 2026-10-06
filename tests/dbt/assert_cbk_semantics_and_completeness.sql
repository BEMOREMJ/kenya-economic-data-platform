select *
from {{ ref('stg_exchange_rates') }}
where publication_date not between date('{{ var("cbk_scope_start_date", var("scope_start_date")) }}') and date('{{ var("cbk_scope_end_date", var("scope_end_date")) }}')
   or currency_code not in ('USD', 'GBP', 'EUR')
   or base_currency != currency_code
   or quote_currency != 'KES'
   or unit_multiplier != 1
   or rate_type != 'indicative_opening_mean_buy_sell'
   or source != 'CBK'
   or mean_rate <= 0 or buy_rate <= 0 or sell_rate <= 0
   or not (buy_rate <= mean_rate and mean_rate <= sell_rate)
union all
select *
from {{ ref('stg_exchange_rates') }}
where publication_date in (
    select publication_date
    from {{ ref('stg_exchange_rates') }}
    group by publication_date
    having count(*) != 3 or count(distinct currency_code) != 3
)
