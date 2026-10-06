{{ config(materialized='table') }}

select
    count(*) as probe_row_count,
    sum(amount) as total_amount
from {{ ref('stg_probe') }}
