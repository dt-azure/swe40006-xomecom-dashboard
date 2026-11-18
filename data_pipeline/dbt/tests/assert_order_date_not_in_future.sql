-- No order is dated after the current date (mock orders are dated today).
select source, row_id, order_date
from {{ ref('stg_sales_lines') }}
where order_date > current_date
