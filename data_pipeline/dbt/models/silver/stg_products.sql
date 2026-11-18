{{
    config(
        materialized='incremental',
        unique_key=['source', 'product_code'],
        indexes=[
            {'columns': ['source', 'product_code'], 'unique': True},
            {'columns': ['ingested_at']},
        ],
    )
}}

-- Latest version of each product, trimmed. Categories are kept as the source has them.

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
    where entity = 'product'
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
    trim(payload ->> 'product_code') as product_code,
    trim(payload ->> 'product') as product_name,
    trim(payload ->> 'category') as category,
    trim(payload ->> 'subcategory') as subcategory,
    false as has_invalid_value,
    is_sample,
    record_id,
    collected_at,
    ingested_at,
    kafka_offset
from latest
where version_rank = 1
