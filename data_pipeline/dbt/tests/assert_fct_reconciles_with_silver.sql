-- Gold neither loses nor doubles sales lines: the line count and the sums of sales and profit in
-- fct_sales_lines equal those of the latest sales-line versions in silver.
with gold as (
    select count(*) as line_count, sum(sales) as sales, sum(profit) as profit
    from {{ ref('fct_sales_lines') }}
),

silver as (
    select count(*) as line_count, sum(sales) as sales, sum(profit) as profit
    from {{ ref('stg_sales_lines') }}
)

select
    gold.line_count as gold_lines,
    silver.line_count as silver_lines,
    gold.sales as gold_sales,
    silver.sales as silver_sales,
    gold.profit as gold_profit,
    silver.profit as silver_profit
from gold
cross join silver
where gold.line_count <> silver.line_count
    or gold.sales is distinct from silver.sales
    or gold.profit is distinct from silver.profit
