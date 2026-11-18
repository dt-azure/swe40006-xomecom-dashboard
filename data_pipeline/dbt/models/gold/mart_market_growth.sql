-- Growth by market and region. One row per order year x market x region x is_sample, with the
-- change against the same market, region and is_sample one calendar year earlier. Years are
-- compared only when they are consecutive: there is no data for 2024 onwards until the demo,
-- so the demo year's change is NULL rather than a comparison with 2023.

with lines as (

    select
        extract(year from fct.order_date)::integer as order_year,
        regions.market,
        regions.region,
        fct.is_sample,
        fct.order_id,
        fct.customer_key,
        fct.order_date,
        fct.sales,
        fct.net_sales,
        fct.profit
    from {{ ref('fct_sales_lines') }} as fct
    inner join {{ ref('dim_region') }} as regions
        on regions.region_key = fct.region_key

),

yearly as (

    select
        order_year,
        market,
        region,
        is_sample,
        count(*) as line_count,
        count(distinct order_id) as order_count,
        count(distinct customer_key) as customer_count,
        sum(sales) as gross_sales,
        sum(net_sales) as net_sales,
        sum(profit) as profit,
        min(order_date) as first_order_date,
        max(order_date) as last_order_date
    from lines
    group by order_year, market, region, is_sample

),

orders as (

    select order_year, market, region, is_sample, order_id, sum(net_sales) as order_net_sales
    from lines
    group by order_year, market, region, is_sample, order_id

),

order_stats as (

    select
        order_year,
        market,
        region,
        is_sample,
        round(avg(order_net_sales), 2) as avg_order_value,
        round((percentile_cont(0.5) within group (order by order_net_sales))::numeric, 2) as median_order_value
    from orders
    group by order_year, market, region, is_sample

)

select
    yearly.order_year,
    yearly.market,
    yearly.region,
    yearly.is_sample,
    yearly.line_count,
    yearly.order_count,
    yearly.customer_count,
    yearly.gross_sales,
    yearly.net_sales,
    yearly.profit,
    round(yearly.profit / nullif(yearly.net_sales, 0), 4) as profit_margin,
    order_stats.avg_order_value,
    order_stats.median_order_value,
    previous.gross_sales as prev_year_gross_sales,
    round((yearly.gross_sales - previous.gross_sales) / nullif(previous.gross_sales, 0), 4) as gross_sales_yoy_change,
    previous.net_sales as prev_year_net_sales,
    round((yearly.net_sales - previous.net_sales) / nullif(previous.net_sales, 0), 4) as net_sales_yoy_change,
    previous.profit as prev_year_profit,
    yearly.profit - previous.profit as profit_yoy_delta,
    previous.order_count as prev_year_order_count,
    yearly.first_order_date,
    yearly.last_order_date
from yearly
inner join order_stats
    on order_stats.order_year is not distinct from yearly.order_year
    and order_stats.market is not distinct from yearly.market
    and order_stats.region is not distinct from yearly.region
    and order_stats.is_sample = yearly.is_sample
left join yearly as previous
    on previous.order_year = yearly.order_year - 1
    and previous.market is not distinct from yearly.market
    and previous.region is not distinct from yearly.region
    and previous.is_sample = yearly.is_sample
