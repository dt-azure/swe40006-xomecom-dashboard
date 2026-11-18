-- xom_source: the simulated Xóm E-Com operational database (not the warehouse).
-- Applied by `python -m src.source.seed` inside the xom_source database; every statement is
-- idempotent.
--
-- The four e_commerce tables keep the source's column names and types. The sales table is
-- `sales_line` here (the upstream name is `ecom_sales`) so that it matches the envelope's entity.
-- Two technical columns are added to every table and are never part of a record's payload:
--   is_sample   true for rows inserted by the mock generator (scripts/generate_burst.py)
--   change_seq  from one shared sequence: set on insert, bumped on every update. The source
--               poller reads rows above its high-water mark in this column.
-- No foreign keys on purpose: the source holds orphan references (see CLAUDE.md, "Known source
-- quirks"), and the pipeline must see them as they are.

CREATE SCHEMA IF NOT EXISTS e_commerce;

CREATE SEQUENCE IF NOT EXISTS e_commerce.change_seq AS bigint;

CREATE TABLE IF NOT EXISTS e_commerce.customer (
    customer_id      varchar(20)  PRIMARY KEY,
    first_name       varchar(50),
    last_name        varchar(50),
    birth_date       date,
    marital_status   varchar(20),
    gender           varchar(1),
    email_address    varchar(100),
    annual_income    integer,
    education_level  varchar(50),
    occupation       varchar(50),
    home_owner       varchar(1),
    is_sample        boolean  NOT NULL DEFAULT false,
    change_seq       bigint   NOT NULL DEFAULT nextval('e_commerce.change_seq')
);

CREATE TABLE IF NOT EXISTS e_commerce.product (
    product_code  varchar(10)  PRIMARY KEY,
    product       varchar(255),
    category      varchar(50),
    subcategory   varchar(50),
    is_sample     boolean  NOT NULL DEFAULT false,
    change_seq    bigint   NOT NULL DEFAULT nextval('e_commerce.change_seq')
);

CREATE TABLE IF NOT EXISTS e_commerce.region (
    region_code        varchar(10)  PRIMARY KEY,
    city               varchar(50),
    state              varchar(50),
    country            varchar(50),
    country_latitude   numeric(10,6),
    country_longitude  numeric(10,6),
    region             varchar(50),
    market             varchar(50),
    is_sample          boolean  NOT NULL DEFAULT false,
    change_seq         bigint   NOT NULL DEFAULT nextval('e_commerce.change_seq')
);

CREATE TABLE IF NOT EXISTS e_commerce.sales_line (
    row_id        integer  PRIMARY KEY,
    order_id      varchar(50),
    order_date    date,
    customer_id   varchar(20),
    segment       varchar(50),
    region_code   varchar(10),
    product_code  varchar(10),
    quantity      integer,
    sales         numeric(10,2),
    discount      numeric(10,2),
    profit        numeric(10,2),
    is_sample     boolean  NOT NULL DEFAULT false,
    change_seq    bigint   NOT NULL DEFAULT nextval('e_commerce.change_seq')
);

-- Bump change_seq on every update, so a changed row is sent again as a new version.
CREATE OR REPLACE FUNCTION e_commerce.bump_change_seq() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.change_seq := nextval('e_commerce.change_seq');
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER customer_bump_change_seq
    BEFORE UPDATE ON e_commerce.customer
    FOR EACH ROW EXECUTE FUNCTION e_commerce.bump_change_seq();
CREATE OR REPLACE TRIGGER product_bump_change_seq
    BEFORE UPDATE ON e_commerce.product
    FOR EACH ROW EXECUTE FUNCTION e_commerce.bump_change_seq();
CREATE OR REPLACE TRIGGER region_bump_change_seq
    BEFORE UPDATE ON e_commerce.region
    FOR EACH ROW EXECUTE FUNCTION e_commerce.bump_change_seq();
CREATE OR REPLACE TRIGGER sales_line_bump_change_seq
    BEFORE UPDATE ON e_commerce.sales_line
    FOR EACH ROW EXECUTE FUNCTION e_commerce.bump_change_seq();

-- The poller's read: WHERE change_seq > :mark ORDER BY change_seq LIMIT :batch.
CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_change_seq   ON e_commerce.customer   (change_seq);
CREATE UNIQUE INDEX IF NOT EXISTS ux_product_change_seq    ON e_commerce.product    (change_seq);
CREATE UNIQUE INDEX IF NOT EXISTS ux_region_change_seq     ON e_commerce.region     (change_seq);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_line_change_seq ON e_commerce.sales_line (change_seq);
