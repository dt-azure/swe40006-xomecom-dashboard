-- sales must be >= 0 when present.
select source, row_id, sales
from {{ ref('stg_sales_lines') }}
where sales < 0
