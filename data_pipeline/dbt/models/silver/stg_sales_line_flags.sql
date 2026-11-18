{{ config(materialized='table') }}

-- Quality flags that compare a sales line with other records. Rebuilt in full every run (a
-- table, not incremental), so a reference that arrives late clears its flag on the next cycle.

with lines as (

    select source, row_id, order_id, customer_id, region_code, product_code
    from {{ ref('stg_sales_lines') }}

),

multi_customer_orders as (

    select source, order_id
    from lines
    where order_id is not null
    group by source, order_id
    having count(distinct customer_id) > 1

)

select
    lines.source,
    lines.row_id,
    customers.customer_id is null as has_unknown_customer,
    regions.region_code is null as has_unknown_region,
    products.product_code is null as has_unknown_product,
    multi.order_id is not null as is_multi_customer_order
from lines
left join {{ ref('stg_customers') }} as customers
    on customers.source = lines.source and customers.customer_id = lines.customer_id
left join {{ ref('stg_regions') }} as regions
    on regions.source = lines.source and regions.region_code = lines.region_code
left join {{ ref('stg_products') }} as products
    on products.source = lines.source and products.product_code = lines.product_code
left join multi_customer_orders as multi
    on multi.source = lines.source and multi.order_id = lines.order_id
