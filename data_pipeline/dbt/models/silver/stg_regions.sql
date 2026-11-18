{{
    config(
        materialized='incremental',
        unique_key=['source', 'region_code'],
        indexes=[
            {'columns': ['source', 'region_code'], 'unique': True},
            {'columns': ['ingested_at']},
        ],
    )
}}

-- Latest version of each region (city level), typed and trimmed.

with received as (

    select
        source,
        record_id,
        payload,
        is_sample,
        collected_at,
        ingested_at,
        kafka_offset,
        id as bronze_id
    from {{ source('bronze', 'raw_records') }}
    where entity = 'region'
    {% if is_incremental() %}
        and {{ ingested_since_last_run() }}
    {% endif %}

),

latest as (

    select
        received.*,
        row_number() over (
            partition by source, record_id
            order by ingested_at desc, kafka_offset desc nulls last, bronze_id desc
        ) as version_rank
    from received

)

select
    source,
    trim(payload ->> 'region_code') as region_code,
    trim(payload ->> 'city') as city,
    trim(payload ->> 'state') as state,
    trim(payload ->> 'country') as country,
    round({{ safe_numeric("payload ->> 'country_latitude'") }}, 6) as country_latitude,
    round({{ safe_numeric("payload ->> 'country_longitude'") }}, 6) as country_longitude,
    trim(payload ->> 'region') as region,
    trim(payload ->> 'market') as market,
    (
        (payload ->> 'country_latitude' is not null and {{ safe_numeric("payload ->> 'country_latitude'") }} is null)
        or (payload ->> 'country_longitude' is not null and {{ safe_numeric("payload ->> 'country_longitude'") }} is null)
    ) as has_invalid_value,
    is_sample,
    record_id,
    collected_at,
    ingested_at,
    kafka_offset
from latest
where version_rank = 1
