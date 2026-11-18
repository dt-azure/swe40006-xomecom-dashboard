-- One row per (source, customer_id), plus one "unknown" member per source for sales lines whose
-- customer is missing. Contact details (email, full birth date) stay in silver.

with customers as (

    select
        source || '|' || customer_id as customer_key,
        source,
        customer_id,
        nullif(concat_ws(' ', first_name, last_name), '') as customer_name,
        gender,
        marital_status,
        extract(year from birth_date)::integer as birth_year,
        annual_income,
        education_level,
        occupation,
        home_owner,
        is_sample,
        false as is_unknown
    from {{ ref('stg_customers') }}

),

unknown as (

    {% for source_name in var('known_sources', ['xom_ecom']) %}
    select
        '{{ source_name }}|unknown' as customer_key,
        '{{ source_name }}' as source,
        null::text as customer_id,
        null::text as customer_name,
        null::text as gender,
        null::text as marital_status,
        null::integer as birth_year,
        null::integer as annual_income,
        null::text as education_level,
        null::text as occupation,
        null::text as home_owner,
        false as is_sample,
        true as is_unknown
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

)

select
    customer_key, source, customer_id, customer_name, gender, marital_status, birth_year,
    annual_income, education_level, occupation, home_owner, is_sample, is_unknown
from customers
union all
select
    customer_key, source, customer_id, customer_name, gender, marital_status, birth_year,
    annual_income, education_level, occupation, home_owner, is_sample, is_unknown
from unknown
