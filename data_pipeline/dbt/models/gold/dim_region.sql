-- One row per (source, region_code), at city level, plus one "unknown" member per source for
-- sales lines whose region is missing (2 lines today).

with regions as (

    select
        source || '|' || region_code as region_key,
        source,
        region_code,
        city,
        state,
        country,
        country_latitude,
        country_longitude,
        region,
        market,
        is_sample,
        false as is_unknown
    from {{ ref('stg_regions') }}

),

unknown as (

    {% for source_name in var('known_sources', ['xom_ecom']) %}
    select
        '{{ source_name }}|unknown' as region_key,
        '{{ source_name }}' as source,
        null::text as region_code,
        null::text as city,
        null::text as state,
        null::text as country,
        null::numeric as country_latitude,
        null::numeric as country_longitude,
        null::text as region,
        null::text as market,
        false as is_sample,
        true as is_unknown
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

)

select
    region_key, source, region_code, city, state, country, country_latitude, country_longitude,
    region, market, is_sample, is_unknown
from regions
union all
select
    region_key, source, region_code, city, state, country, country_latitude, country_longitude,
    region, market, is_sample, is_unknown
from unknown
