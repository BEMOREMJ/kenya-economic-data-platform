select
    cast(observation_date as date) as observation_date,
    cast(location_name as string) as location_name,
    cast(latitude as float64) as latitude,
    cast(longitude as float64) as longitude,
    cast(time_standard as string) as time_standard,
    cast(t2m_c as float64) as mean_temperature_c,
    cast(prectotcorr_mm_day as float64) as precipitation_mm_day,
    cast(source as string) as source,
    cast(batch_id as string) as batch_id,
    cast(source_snapshot_sha256 as string) as source_snapshot_sha256
from {{ source('candidate_landing', 'nasa_weather') }}
