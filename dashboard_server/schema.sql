-- The gold schema of the xom-ecom pipeline, as exported on 2026-11-17T08:58:05+00:00 by dashboard_serve/export_gold.py.
-- Generated: do not edit by hand. load_gold.py applies it to an empty gold schema.
-- In the real warehouse these tables are built by dbt; constraints are not declared
-- there either, so the grain of each table is given in its comment.

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE gold.dim_customer (
    customer_key     text,
    source           text,
    customer_id      text,
    customer_name    text,
    gender           text,
    marital_status   text,
    birth_year       integer,
    annual_income    integer,
    education_level  text,
    occupation       text,
    home_owner       text,
    is_sample        boolean,
    is_unknown       boolean
);

COMMENT ON TABLE gold.dim_customer IS 'One row per (source, customer_id), plus one unknown member per source (customer_key ''<source>|unknown'', is_unknown = true, attributes NULL). Contact details stay in silver. Grain: customer_key.';
COMMENT ON COLUMN gold.dim_customer.customer_key IS '''<source>|<customer_id>'', or ''<source>|unknown''.';
COMMENT ON COLUMN gold.dim_customer.customer_name IS 'First and last name; NULL when both are missing.';
COMMENT ON COLUMN gold.dim_customer.birth_year IS 'Year of birth only; the full date stays in silver.';

CREATE TABLE gold.dim_date (
    date_day         date,
    year             integer,
    quarter          integer,
    month            integer,
    month_name       text,
    iso_day_of_week  integer,
    day_name         text,
    is_weekend       boolean,
    month_start      date,
    quarter_start    date,
    year_start       date,
    quarter_label    text
);

COMMENT ON TABLE gold.dim_date IS 'One row per calendar day from the first order_date to the current date. The 2024-to-demo gap has days but no sales. Grain: date_day.';

CREATE TABLE gold.dim_product (
    product_key   text,
    source        text,
    product_code  text,
    product_name  text,
    category      text,
    subcategory   text,
    is_sample     boolean,
    is_unknown    boolean
);

COMMENT ON TABLE gold.dim_product IS 'One row per (source, product_code), plus one unknown member per source. Categories as the source has them. Grain: product_key.';

CREATE TABLE gold.dim_region (
    region_key         text,
    source             text,
    region_code        text,
    city               text,
    state              text,
    country            text,
    country_latitude   numeric,
    country_longitude  numeric,
    region             text,
    market             text,
    is_sample          boolean,
    is_unknown         boolean
);

COMMENT ON TABLE gold.dim_region IS 'One row per (source, region_code) at city level, plus one unknown member per source. Grain: region_key.';

CREATE TABLE gold.fct_sales_lines (
    sales_line_key       text,
    source               text,
    row_id               integer,
    order_id             text,
    order_date           date,
    customer_key         text,
    product_key          text,
    region_key           text,
    segment              text,
    quantity             integer,
    sales                numeric,
    discount             numeric,
    profit               numeric,
    unit_price           numeric,
    pre_discount_amount  numeric,
    discount_amount      numeric,
    net_sales            numeric,
    discount_band        text,
    is_loss              boolean,
    currency             text,
    is_sample            boolean,
    ingested_at          timestamp with time zone
);

COMMENT ON TABLE gold.fct_sales_lines IS 'One row per sales line (source, row_id), with keys to every dimension, the measures, discount_band, is_loss, currency and is_sample. Lines with a missing customer, product or region point at that dimension''s unknown member, so totals reconcile; they are re-linked once the reference arrives. `sales` is before discount; net_sales is after. Grain: sales_line_key.';
COMMENT ON COLUMN gold.fct_sales_lines.sales_line_key IS '''<source>|<row_id>''.';
COMMENT ON COLUMN gold.fct_sales_lines.order_date IS 'Key to dim_date.';
COMMENT ON COLUMN gold.fct_sales_lines.sales IS 'Amount before discount (unit price x quantity).';
COMMENT ON COLUMN gold.fct_sales_lines.profit IS 'Profit after discount.';
COMMENT ON COLUMN gold.fct_sales_lines.pre_discount_amount IS 'Amount before discount; equal to sales.';
COMMENT ON COLUMN gold.fct_sales_lines.discount_amount IS 'sales x discount.';
COMMENT ON COLUMN gold.fct_sales_lines.net_sales IS 'Amount after discount, sales x (1 - discount).';

CREATE TABLE gold.mart_customer_retention (
    cohort_month                   date,
    months_since_first_order       integer,
    is_sample                      boolean,
    cohort_customers               bigint,
    active_customers               bigint,
    retention_rate                 numeric,
    order_count                    bigint,
    net_sales                      numeric,
    profit                         numeric,
    avg_net_sales_per_customer     numeric,
    median_net_sales_per_customer  numeric,
    first_order_date               date,
    last_order_date                date
);

COMMENT ON TABLE gold.mart_customer_retention IS 'Retention by first-order cohort. One row per cohort_month x months_since_first_order x is_sample. Each is_sample slice is computed on its own (a customer''s cohort is their first order within the slice), so hiding sample rows leaves the real figures untouched. retention_rate = active_customers / cohort_customers. Churn is not defined. Grain: cohort_month, months_since_first_order, is_sample.';

CREATE TABLE gold.mart_discount_impact (
    order_month             date,
    category                text,
    discount_band           text,
    is_sample               boolean,
    line_count              bigint,
    order_count             bigint,
    quantity                bigint,
    gross_sales             numeric,
    discount_amount         numeric,
    net_sales               numeric,
    profit                  numeric,
    profit_margin           numeric,
    avg_discount            numeric,
    avg_profit_per_line     numeric,
    median_profit_per_line  numeric,
    loss_line_count         bigint,
    loss_line_share         numeric,
    first_order_date        date,
    last_order_date         date
);

COMMENT ON TABLE gold.mart_discount_impact IS 'Discount impact on profit. One row per order_month x category x discount_band x is_sample. profit_margin = profit / net_sales. Carries line and order counts, averages with medians, the loss share and the order_date range covered. Grain: order_month, category, discount_band, is_sample.';

CREATE TABLE gold.mart_market_growth (
    order_year              integer,
    market                  text,
    region                  text,
    is_sample               boolean,
    line_count              bigint,
    order_count             bigint,
    customer_count          bigint,
    gross_sales             numeric,
    net_sales               numeric,
    profit                  numeric,
    profit_margin           numeric,
    avg_order_value         numeric,
    median_order_value      numeric,
    prev_year_gross_sales   numeric,
    gross_sales_yoy_change  numeric,
    prev_year_net_sales     numeric,
    net_sales_yoy_change    numeric,
    prev_year_profit        numeric,
    profit_yoy_delta        numeric,
    prev_year_order_count   bigint,
    first_order_date        date,
    last_order_date         date
);

COMMENT ON TABLE gold.mart_market_growth IS 'Growth by market. One row per order_year x market x region x is_sample, with the change against the previous calendar year for the same market, region and is_sample. A year whose previous year has no data (the demo year) gets NULL changes. Grain: order_year, market, region, is_sample.';

CREATE TABLE gold.mart_segment_pnl (
    order_quarter          date,
    quarter_label          text,
    segment                text,
    is_sample              boolean,
    line_count             bigint,
    order_count            bigint,
    customer_count         bigint,
    gross_sales            numeric,
    discount_amount        numeric,
    net_sales              numeric,
    profit                 numeric,
    profit_margin          numeric,
    profit_from_gains      numeric,
    profit_lost_on_losses  numeric,
    loss_line_count        bigint,
    loss_order_count       bigint,
    avg_order_value        numeric,
    median_order_value     numeric,
    avg_order_profit       numeric,
    median_order_profit    numeric,
    first_order_date       date,
    last_order_date        date
);

COMMENT ON TABLE gold.mart_segment_pnl IS 'Profit and loss by segment. One row per order_quarter x segment x is_sample, with gains and losses split, loss-making lines and orders, order value and order profit as averages and medians, and the order_date range covered. Grain: order_quarter, segment, is_sample.';
