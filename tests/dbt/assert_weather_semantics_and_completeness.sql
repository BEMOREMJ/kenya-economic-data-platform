{% set ranges = var('weather_expected_ranges', {}) %}
with expected as (
    {% if ranges %}
      {% for location_name, bounds in ranges.items() %}
        select date_day as observation_date, '{{ location_name }}' as location_name
        from unnest(generate_date_array(
          date('{{ bounds["start_date"] }}'), date('{{ bounds["end_date"] }}')
        )) as date_day
        {% if not loop.last %} union all {% endif %}
      {% endfor %}
    {% else %}
      select d.date_day as observation_date, l.location_name
      from {{ ref('dim_date') }} d
      cross join {{ ref('dim_location') }} l
    {% endif %}
),
missing as (
    select expected.*
    from expected
    left join {{ ref('stg_weather') }} actual using (observation_date, location_name)
    where actual.observation_date is null
),
invalid as (
    select observation_date, location_name
    from {{ ref('stg_weather') }}
    where observation_date not between date('{{ var("scope_start_date") }}') and date('{{ var("scope_end_date") }}')
       or time_standard != 'UTC'
       or source != 'NASA_POWER'
       or mean_temperature_c not between -90 and 60
       or precipitation_mm_day not between 0 and 2000
)
select * from missing
union all
select * from invalid
