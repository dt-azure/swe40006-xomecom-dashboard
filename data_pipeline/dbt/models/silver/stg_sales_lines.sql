{{
    config(
        materialized='incremental',
        unique_key=['source', 'row_id'],
        indexes=[
            {'columns': ['source', 'row_id'], 'unique': True},
            {'columns': ['ingested_at']},
        ],
    )
}}

-- Latest version of each sales line, typed, with derived fields and row-level quality flags.
-- `sales` is the amount before discount (unit price x quantity; see _silver.yml).

with received as (

    select
        source,
        record_id,
        payload,
        is_sample,
        collected_at,
        ingested_at,
        kafka_partition,
        kafka_offset,
        id as bronze_id
    from {{ source('bronze', 'raw_records') }}
    where entity = 'sales_line'
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

),

typed as (

    select
        source,
        record_id,
        {{ safe_integer("payload ->> 'row_id'") }} as row_id,
        trim(payload ->> 'order_id') as order_id,
        {{ safe_date("payload ->> 'order_date'") }} as order_date,
        trim(payload ->> 'customer_id') as customer_id,
        trim(payload ->> 'segment') as segment,
        trim(payload ->> 'region_code') as region_code,
        trim(payload ->> 'product_code') as product_code,
        {{ safe_integer("payload ->> 'quantity'") }} as quantity,
        round({{ safe_numeric("payload ->> 'sales'") }}, 2) as sales,
        round({{ safe_numeric("payload ->> 'discount'") }}, 2) as discount,
        round({{ safe_numeric("payload ->> 'profit'") }}, 2) as profit,
        (
            (payload ->> 'row_id' is not null and {{ safe_integer("payload ->> 'row_id'") }} is null)
            or (payload ->> 'order_date' is not null and {{ safe_date("payload ->> 'order_date'") }} is null)
            or (payload ->> 'quantity' is not null and {{ safe_integer("payload ->> 'quantity'") }} is null)
            or (payload ->> 'sales' is not null and {{ safe_numeric("payload ->> 'sales'") }} is null)
            or (payload ->> 'discount' is not null and {{ safe_numeric("payload ->> 'discount'") }} is null)
            or (payload ->> 'profit' is not null and {{ safe_numeric("payload ->> 'profit'") }} is null)
        ) as has_invalid_value,
        is_sample,
        collected_at,
        ingested_at,
        kafka_partition,
        kafka_offset
    from latest
    where version_rank = 1

)

select
    source,
    row_id,
    order_id,
    order_date,
    customer_id,
    segment,
    region_code,
    product_code,
    quantity,
    sales,
    discount,
    profit,
    round(sales / nullif(quantity, 0), 2) as unit_price,
    sales as pre_discount_amount,
    round(sales * discount, 2) as discount_amount,
    round(sales * (1 - discount), 2) as net_sales,
    case
        when discount is null then null
        when discount = 0 then 'none'
        when discount <= 0.20 then 'low'
        when discount <= 0.40 then 'medium'
        else 'high'
    end as discount_band,
    profit < 0 as is_loss,
    'USD'::text as currency,
    (quantity is null or sales is null or discount is null or profit is null) as has_missing_measure,
    has_invalid_value,
    is_sample,
    record_id,
    collected_at,
    ingested_at,
    kafka_partition,
    kafka_offset
from typed
