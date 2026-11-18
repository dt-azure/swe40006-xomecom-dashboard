-- One row per (source, product_code), plus one "unknown" member per source for sales lines
-- whose product is missing (2 lines today).

with products as (

    select
        source || '|' || product_code as product_key,
        source,
        product_code,
        product_name,
        category,
        subcategory,
        is_sample,
        false as is_unknown
    from {{ ref('stg_products') }}

),

unknown as (

    {% for source_name in var('known_sources', ['xom_ecom']) %}
    select
        '{{ source_name }}|unknown' as product_key,
        '{{ source_name }}' as source,
        null::text as product_code,
        null::text as product_name,
        null::text as category,
        null::text as subcategory,
        false as is_sample,
        true as is_unknown
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

)

select product_key, source, product_code, product_name, category, subcategory, is_sample, is_unknown
from products
union all
select product_key, source, product_code, product_name, category, subcategory, is_sample, is_unknown
from unknown
