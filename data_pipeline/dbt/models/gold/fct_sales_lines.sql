{{
    config(
        materialized='incremental',
        unique_key='sales_line_key',
        indexes=[
            {'columns': ['sales_line_key'], 'unique': True},
            {'columns': ['ingested_at']},
            {'columns': ['order_date']},
        ],
    )
}}

-- One row per sales line (source, row_id), with a key to every dimension and the measures.
-- Incremental. Besides new silver rows, each run re-reads the lines that currently point at an
-- "unknown" member, so a customer, product or region that arrives after its sales line is
-- linked on the next cycle instead of never.

with lines as (

    select
        source, row_id, order_id, order_date, customer_id, segment, region_code, product_code,
        quantity, sales, discount, profit, unit_price, pre_discount_amount, discount_amount,
        net_sales, discount_band, is_loss, currency, is_sample, ingested_at
    from {{ ref('stg_sales_lines') }} as lines
    {% if is_incremental() %}
    where {{ ingested_since_last_run('lines.ingested_at') }}
        or (lines.source, lines.row_id) in (
            select source, row_id
            from {{ this }}
            where customer_key = source || '|unknown'
                or product_key = source || '|unknown'
                or region_key = source || '|unknown'
        )
    {% endif %}

)

select
    lines.source || '|' || lines.row_id as sales_line_key,
    lines.source,
    lines.row_id,
    lines.order_id,
    lines.order_date,
    coalesce(customers.customer_key, lines.source || '|unknown') as customer_key,
    coalesce(products.product_key, lines.source || '|unknown') as product_key,
    coalesce(regions.region_key, lines.source || '|unknown') as region_key,
    lines.segment,
    lines.quantity,
    lines.sales,
    lines.discount,
    lines.profit,
    lines.unit_price,
    lines.pre_discount_amount,
    lines.discount_amount,
    lines.net_sales,
    lines.discount_band,
    lines.is_loss,
    lines.currency,
    lines.is_sample,
    lines.ingested_at
from lines
left join {{ ref('dim_customer') }} as customers
    on customers.source = lines.source
    and customers.customer_id = lines.customer_id
    and not customers.is_unknown
left join {{ ref('dim_product') }} as products
    on products.source = lines.source
    and products.product_code = lines.product_code
    and not products.is_unknown
left join {{ ref('dim_region') }} as regions
    on regions.source = lines.source
    and regions.region_code = lines.region_code
    and not regions.is_unknown
