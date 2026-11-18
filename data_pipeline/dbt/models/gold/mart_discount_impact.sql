-- Does discounting pay? One row per order month x category x discount_band x is_sample.
-- Margins are profit / net_sales (the amount after discount), since profit is after discount.

with lines as (

    select
        date_trunc('month', fct.order_date)::date as order_month,
        products.category,
        fct.discount_band,
        fct.is_sample,
        fct.order_id,
        fct.order_date,
        fct.quantity,
        fct.sales,
        fct.discount,
        fct.discount_amount,
        fct.net_sales,
        fct.profit,
        fct.is_loss
    from {{ ref('fct_sales_lines') }} as fct
    inner join {{ ref('dim_product') }} as products
        on products.product_key = fct.product_key

)

select
    order_month,
    category,
    discount_band,
    is_sample,
    count(*) as line_count,
    count(distinct order_id) as order_count,
    sum(quantity) as quantity,
    sum(sales) as gross_sales,
    sum(discount_amount) as discount_amount,
    sum(net_sales) as net_sales,
    sum(profit) as profit,
    round(sum(profit) / nullif(sum(net_sales), 0), 4) as profit_margin,
    round(avg(discount), 4) as avg_discount,
    round(avg(profit), 2) as avg_profit_per_line,
    round((percentile_cont(0.5) within group (order by profit))::numeric, 2) as median_profit_per_line,
    count(*) filter (where is_loss) as loss_line_count,
    round(count(*) filter (where is_loss)::numeric / count(*), 4) as loss_line_share,
    min(order_date) as first_order_date,
    max(order_date) as last_order_date
from lines
group by order_month, category, discount_band, is_sample
