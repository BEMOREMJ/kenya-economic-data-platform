{{ config(materialized='view') }}

select
    cast(probe_id as int64) as probe_id,
    cast(label as string) as label,
    cast(amount as numeric) as amount
from {{ source('probe_landing', 'probe_input') }}
