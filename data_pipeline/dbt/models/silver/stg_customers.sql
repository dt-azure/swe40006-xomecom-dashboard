{{
    config(
        materialized='incremental',
        unique_key=['source', 'customer_id'],
        indexes=[
            {'columns': ['source', 'customer_id'], 'unique': True},
            {'columns': ['ingested_at']},
        ],
    )
}}

-- Latest version of each customer, typed and trimmed. A missing attribute stays NULL.

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
    where entity = 'customer'
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
    trim(payload ->> 'customer_id') as customer_id,
    trim(payload ->> 'first_name') as first_name,
    trim(payload ->> 'last_name') as last_name,
    {{ safe_date("payload ->> 'birth_date'") }} as birth_date,
    trim(payload ->> 'marital_status') as marital_status,
    trim(payload ->> 'gender') as gender,
    trim(payload ->> 'email_address') as email_address,
    {{ safe_integer("payload ->> 'annual_income'") }} as annual_income,
    trim(payload ->> 'education_level') as education_level,
    trim(payload ->> 'occupation') as occupation,
    trim(payload ->> 'home_owner') as home_owner,
    (
        (payload ->> 'birth_date' is not null and {{ safe_date("payload ->> 'birth_date'") }} is null)
        or (payload ->> 'annual_income' is not null and {{ safe_integer("payload ->> 'annual_income'") }} is null)
    ) as has_invalid_value,
    is_sample,
    record_id,
    collected_at,
    ingested_at,
    kafka_offset
from latest
where version_rank = 1
