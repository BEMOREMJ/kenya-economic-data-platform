select
    observation_date,
    lower(location_name) as location_id,
    mean_temperature_c,
    precipitation_mm_day,
    time_standard,
    source,
    batch_id,
    source_snapshot_sha256
from {{ ref('stg_weather') }}
