-- Customer retention by first-order cohort. One row per cohort month x months since first order
-- x is_sample. Each is_sample slice is its own cohort analysis: a customer's cohort is the month
-- of their first order within that slice, so hiding sample rows leaves the real figures exactly
-- as they would be without the demo. Lines with an unknown customer are left out (no cohort).
-- No churn is defined here: a customer without later orders is only "not active" in that month.

with lines as (

    select
        customer_key,
        is_sample,
        order_id,
        order_date,
        date_trunc('month', order_date)::date as order_month,
        net_sales,
        profit
    from {{ ref('fct_sales_lines') }}
    where order_date is not null
        and customer_key <> source || '|unknown'

),

first_orders as (

    select customer_key, is_sample, min(order_month) as cohort_month
    from lines
    group by customer_key, is_sample

),

cohort_sizes as (

    select cohort_month, is_sample, count(*) as cohort_customers
    from first_orders
    group by cohort_month, is_sample

),

activity as (

    select
        first_orders.cohort_month,
        (
            (extract(year from lines.order_month) - extract(year from first_orders.cohort_month)) * 12
            + extract(month from lines.order_month) - extract(month from first_orders.cohort_month)
        )::integer as months_since_first_order,
        lines.is_sample,
        lines.customer_key,
        lines.order_id,
        lines.order_date,
        lines.net_sales,
        lines.profit
    from lines
    inner join first_orders
        on first_orders.customer_key = lines.customer_key
        and first_orders.is_sample = lines.is_sample

),

per_customer as (

    select
        cohort_month,
        months_since_first_order,
        is_sample,
        customer_key,
        sum(net_sales) as customer_net_sales
    from activity
    group by cohort_month, months_since_first_order, is_sample, customer_key

),

customer_stats as (

    select
        cohort_month,
        months_since_first_order,
        is_sample,
        round(avg(customer_net_sales), 2) as avg_net_sales_per_customer,
        round((percentile_cont(0.5) within group (order by customer_net_sales))::numeric, 2) as median_net_sales_per_customer
    from per_customer
    group by cohort_month, months_since_first_order, is_sample

),

activity_stats as (

    select
        cohort_month,
        months_since_first_order,
        is_sample,
        count(distinct customer_key) as active_customers,
        count(distinct order_id) as order_count,
        sum(net_sales) as net_sales,
        sum(profit) as profit,
        min(order_date) as first_order_date,
        max(order_date) as last_order_date
    from activity
    group by cohort_month, months_since_first_order, is_sample

)

select
    activity_stats.cohort_month,
    activity_stats.months_since_first_order,
    activity_stats.is_sample,
    cohort_sizes.cohort_customers,
    activity_stats.active_customers,
    round(activity_stats.active_customers::numeric / cohort_sizes.cohort_customers, 4) as retention_rate,
    activity_stats.order_count,
    activity_stats.net_sales,
    activity_stats.profit,
    customer_stats.avg_net_sales_per_customer,
    customer_stats.median_net_sales_per_customer,
    activity_stats.first_order_date,
    activity_stats.last_order_date
from activity_stats
inner join cohort_sizes
    on cohort_sizes.cohort_month = activity_stats.cohort_month
    and cohort_sizes.is_sample = activity_stats.is_sample
inner join customer_stats
    on customer_stats.cohort_month = activity_stats.cohort_month
    and customer_stats.months_since_first_order = activity_stats.months_since_first_order
    and customer_stats.is_sample = activity_stats.is_sample
