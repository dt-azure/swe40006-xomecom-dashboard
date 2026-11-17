# CommercePulse Gold data audit

This audit covers the supplied Gold snapshot and the five CommercePulse views. The business questions come from the project brief, §1.3 Table 2, and the team overview. Where the brief uses different segment or market names, the dashboard uses the values present in Gold.

The local PostgreSQL audit used a read-only transaction and verified column order and PostgreSQL types for all nine relations against the manifest. The snapshot audit checked grains, foreign-key coverage, date ranges and aggregate totals. No schema, data or pipeline changes were required.

## Gold source inventory

| Relation | Rows / columns | Verified grain and useful fields | Nulls observed |
| --- | ---: | --- | --- |
| `fct_sales_lines` | 51,290 / 22 | Unique text `sales_line_key`; source-qualified order IDs; `order_date` (date), customer/product/region keys (text), segment, discount band, units (integer), discount and amounts (numeric), `is_sample` (boolean), `ingested_at` (timestamp with time zone). | None |
| `dim_date` | 2,513 / 12 | Unique `date_day`; date and calendar breakdown, including Boolean `is_weekend`. | None |
| `dim_customer` | 17,416 / 13 | Unique `customer_key`; demographic and occupation attributes, sample and unknown flags. Dashboard uses known customer keys without fetching names or demographics. | Gender 125 (0.718%); one row (0.006%) each in customer ID, name, marital status, birth year, income, education, occupation and home ownership |
| `dim_product` | 28,357 / 8 | Unique `product_key`; product code, name, category and subcategory (text), sample and unknown flags. | One each (0.004%) in product code, name, category and subcategory |
| `dim_region` | 3,829 / 12 | Unique `region_key`; city, state, country, region and market labels, country coordinates (numeric), sample and unknown flags. | One each (0.026%) in region code, city, state, country, both coordinates, region and market |
| `mart_discount_impact` | 960 / 19 | Month × category × discount band × sample flag; sales, average discount, profit, margin and loss-line measures. | Category 2 (0.208%) |
| `mart_segment_pnl` | 48 / 22 | Quarter × segment × sample flag; gross and net sales, profit, margin, customers, orders and loss-making orders. | None |
| `mart_market_growth` | 93 / 22 | Year × market × region × sample flag; sales, profit, margin and prior-year comparisons. | Market and region one each (1.075%); seven prior-year baseline or change fields 24 each (25.806%) |
| `mart_customer_retention` | 1,167 / 13 | Cohort month × months since first order × sample flag; cohort size, active customers, retention, orders and period spending. | None |

Fact keys `customer_key`, `product_key` and `region_key` join to their same-named dimensions. Fact `order_date` joins to `dim_date.date_day`. There were no orphan facts. Two lines each resolve to unknown product and location members. No facts resolve to the unknown customer. Unknown dimensions retain their sales and profit. Order-level metrics deduplicate by `source`, `is_sample` and `order_id`; grouped counts can overlap across locations or categories.

The fact contains order dates from 2020-01-01 through 2023-12-31. The date dimension covers 2020-01-01 through 2026-11-17. The only fact timestamp is `ingested_at`, covering a warehouse load from 06:24:17 through 06:25:00 UTC on 2026-11-17. It cannot identify a time of purchase. The marts have coverage fields for their order dates, and all snapshot rows are historical.

## Business requirement coverage

| Requirement | Available data | Existing dashboard coverage | Missing elements | Recommended action and shipped analysis |
| --- | --- | --- | --- | --- |
| **B1 · Discount cannibalization — partially supported** | `fct_sales_lines.discount`, `discount_band`, `net_sales`, `profit`, `order_id` and `segment`; `dim_product.category`, `product_key`, `product_name`; `mart_discount_impact.avg_discount`, `profit_margin`, `loss_line_count`; `mart_segment_pnl.loss_order_count`. | Categories showed a monthly discount mart and sales rankings. | The fact records observed transactions. It lacks a control group or counterfactual demand for measuring incremental sales or causal cannibalization. | Categories now shows average line discount by category, profit and margin by band, and the three highest-profit known products per category where available. Overview counts orders with negative total profit by segment. |
| **B2 · Segment profitability — fully supported** | `fct_sales_lines.segment`, `sales`, `net_sales`, `profit`, `order_id`; `dim_product.category`; `mart_segment_pnl.gross_sales`, `net_sales`, `profit`, `profit_margin`, `loss_order_count`. | Overview had a segment sales chart and quarterly P&L. | Gross revenue shares by category and loss counts were not visible in the date-scoped analysis. | Overview now shows scoped segment P&L, loss-making orders and Consumer versus Corporate gross sales shares by category. All segments contribute to the denominator. |
| **B3 · Geographic market performance — fully supported** | `dim_region.market`, `region`, `country`, `city`; `fct_sales_lines.region_key`, `customer_key`, `order_date`, `net_sales`, `profit`; `mart_market_growth.net_sales_yoy_change`, `profit_margin`, `prev_year_net_sales`. | Geography showed market distribution, metro rankings and an annual growth mart. | A monthly view and distinct customers purchasing across recorded regions were missing. | Geography now offers a market treemap, profitability by market, region or top 15 countries, a cross-region customer count and month-over-month and year-over-year growth for complete months. The country and region filters apply to the historical comparison, too. |
| **B4 · Retention and LTV — partially supported** | `fct_sales_lines.customer_key`, `order_id`, `order_date`, `net_sales`, `segment`; `mart_customer_retention.cohort_month`, `months_since_first_order`, `cohort_customers`, `active_customers`, `retention_rate`. | Overview offered the cohort mart table. | Predictive lifetime value, confirmed churn and a reliable probability of churn are unavailable. The published cohort mart has no segment dimension. | Overview now shows observed repeat purchase, observed lifetime sales per customer, descriptive recency/frequency/monetary groups and cohort heatmap. Repeat rate by segment uses orders within each segment. The inactive high-value count uses the upper spending quartile and 181+ days without an observed purchase, where the selected data span is long enough. |

In the full snapshot, 5,436 of 17,415 known customers made at least two distinct orders (31.21%). Observed lifetime sales per customer use recorded history through the observation date for customers who purchased in the selected window and segment. RFM spending and inactivity use the selected window. Neither estimates future customer value. All 1,167 cohort rows satisfy active customers ≤ cohort customers.

## Time of day, source coverage and operations

All nine schemas were checked for shipment, dispatch, promised delivery, actual delivery, review or rating fields and joinable equivalents. None are present. The date dimension, sales records and ingestion time do not establish delivery or review events. Shipment and review reporting are outside the current dashboard scope.

Sales Trend uses distinct orders by weekday instead of an hourly heatmap. Its stacked bar divides weekday and weekend net sales by total net sales. The full snapshot split is **64.7% Mon–Fri** and **35.3% Sat–Sun**. Zero totals and signed amounts unsuitable for a proportional bar show an unavailable message. Pipeline Health still requires an agreed operations feed for ETL execution and transform freshness.

## Reconciliation

The full snapshot reconciles to **25,728 distinct orders**, **$6,517,674.00 gross sales**, **$5,565,259.31 net sales** and **$1,065,413.58 profit**. Net sales and profit match the discount, segment and market marts. The 5,496 quarterly loss-making order counts match the segment mart when order profit is summed in exact cents within quarter and segment. USD is the warehouse label, pending data-owner confirmation.
