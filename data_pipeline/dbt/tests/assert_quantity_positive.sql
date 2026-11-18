-- quantity must be > 0 when present.
select source, row_id, quantity
from {{ ref('stg_sales_lines') }}
where quantity <= 0
