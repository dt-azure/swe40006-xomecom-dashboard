-- Profit and loss by customer segment. One row per order quarter x segment x is_sample.
-- Order-level averages and medians come from orders summed within the segment.

with lines as (

    select
        date_trunc('quarter', order_date)::date as order_quarter,
        segment,
        is_sample,
        order_id,
        customer_key,
        order_date,
        sales,
        discount_amount,
        net_sales,
        profit,
        is_loss
    from {{ ref('fct_sales_lines') }}

),

orders as (

    select
        order_quarter,
        segment,
        is_sample,
        order_id,
        sum(net_sales) as order_net_sales,
        sum(profit) as order_profit
    from lines
    group by order_quarter, segment, is_sample, order_id

),

order_stats as (

    select
        order_quarter,
        segment,
        is_sample,
        count(*) as order_count,
        count(*) filter (where order_profit < 0) as loss_order_count,
        round(avg(order_net_sales), 2) as avg_order_value,
        round((percentile_cont(0.5) within group (order by order_net_sales))::numeric, 2) as median_order_value,
        round(avg(order_profit), 2) as avg_order_profit,
        round((percentile_cont(0.5) within group (order by order_profit))::numeric, 2) as median_order_profit
    from orders
    group by order_quarter, segment, is_sample

),

line_stats as (

    select
        order_quarter,
        segment,
        is_sample,
        count(*) as line_count,
        count(distinct customer_key) as customer_count,
        sum(sales) as gross_sales,
        sum(discount_amount) as discount_amount,
        sum(net_sales) as net_sales,
        sum(profit) as profit,
        coalesce(sum(profit) filter (where profit > 0), 0) as profit_from_gains,
        coalesce(sum(profit) filter (where profit < 0), 0) as profit_lost_on_losses,
        count(*) filter (where is_loss) as loss_line_count,
        min(order_date) as first_order_date,
        max(order_date) as last_order_date
    from lines
    group by order_quarter, segment, is_sample

)

select
    line_stats.order_quarter,
    to_char(line_stats.order_quarter, 'YYYY') || '-Q' || extract(quarter from line_stats.order_quarter) as quarter_label,
    line_stats.segment,
    line_stats.is_sample,
    line_stats.line_count,
    order_stats.order_count,
    line_stats.customer_count,
    line_stats.gross_sales,
    line_stats.discount_amount,
    line_stats.net_sales,
    line_stats.profit,
    round(line_stats.profit / nullif(line_stats.net_sales, 0), 4) as profit_margin,
    line_stats.profit_from_gains,
    line_stats.profit_lost_on_losses,
    line_stats.loss_line_count,
    order_stats.loss_order_count,
    order_stats.avg_order_value,
    order_stats.median_order_value,
    order_stats.avg_order_profit,
    order_stats.median_order_profit,
    line_stats.first_order_date,
    line_stats.last_order_date
from line_stats
inner join order_stats
    on order_stats.order_quarter is not distinct from line_stats.order_quarter
    and order_stats.segment is not distinct from line_stats.segment
    and order_stats.is_sample = line_stats.is_sample
