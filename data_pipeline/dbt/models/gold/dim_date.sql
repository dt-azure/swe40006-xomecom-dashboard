-- One row per calendar day from the first order_date to today. Rebuilt every run, so it grows
-- with the calendar. History ends 2023-12-31 and mock orders are dated today; the days between
-- exist here but carry no sales.

with bounds as (

    select
        coalesce(min(order_date), current_date) as first_day,
        current_date as last_day
    from {{ ref('stg_sales_lines') }}

),

days as (

    select generate_series(first_day, last_day, interval '1 day')::date as date_day
    from bounds

)

select
    date_day,
    extract(year from date_day)::integer as year,
    extract(quarter from date_day)::integer as quarter,
    extract(month from date_day)::integer as month,
    to_char(date_day, 'Mon') as month_name,
    extract(isodow from date_day)::integer as iso_day_of_week,
    to_char(date_day, 'Dy') as day_name,
    extract(isodow from date_day) in (6, 7) as is_weekend,
    date_trunc('month', date_day)::date as month_start,
    date_trunc('quarter', date_day)::date as quarter_start,
    date_trunc('year', date_day)::date as year_start,
    to_char(date_day, 'YYYY') || '-Q' || extract(quarter from date_day) as quarter_label
from days
