select distinct
    lower(location_name) as location_id,
    location_name,
    latitude,
    longitude,
    'NASA POWER representative grid point; not a station or city-wide average' as spatial_limitation
from {{ ref('stg_weather') }}
