-- discount is a rate between 0 and 1 when present.
select source, row_id, discount
from {{ ref('stg_sales_lines') }}
where discount < 0 or discount > 1
