-- Schema of [xomdata_dataset] scripted 2026-11-16 09:29:32
-- Source collation: SQL_Latin1_General_CP1_CI_AS. Run inside the target database.
-- Load the CSVs after the tables exist; the foreign keys are at the end of this file.
SET NOCOUNT ON;
GO

-- Schemas
IF SCHEMA_ID(N'e_commerce') IS NULL EXEC(N'CREATE SCHEMA [e_commerce]');
GO

-- Tables
CREATE TABLE [e_commerce].[customer] (
    [customer_id] nvarchar(20) NOT NULL,
    [first_name] nvarchar(50) NULL,
    [last_name] nvarchar(50) NULL,
    [birth_date] date NULL,
    [marital_status] nvarchar(20) NULL,
    [gender] nvarchar(1) NULL,
    [email_address] nvarchar(100) NULL,
    [annual_income] int NULL,
    [education_level] nvarchar(50) NULL,
    [occupation] nvarchar(50) NULL,
    [home_owner] nvarchar(1) NULL
);
GO
CREATE TABLE [e_commerce].[ecom_sales] (
    [row_id] int NOT NULL,
    [order_id] nvarchar(50) NULL,
    [order_date] date NULL,
    [customer_id] nvarchar(20) NULL,
    [segment] nvarchar(50) NULL,
    [region_code] nvarchar(10) NULL,
    [product_code] nvarchar(10) NULL,
    [quantity] int NULL,
    [sales] decimal(10,2) NULL,
    [discount] decimal(10,2) NULL,
    [profit] decimal(10,2) NULL
);
GO
CREATE TABLE [e_commerce].[product] (
    [product_code] nvarchar(10) NOT NULL,
    [product] nvarchar(255) NULL,
    [category] nvarchar(50) NULL,
    [subcategory] nvarchar(50) NULL
);
GO
CREATE TABLE [e_commerce].[region] (
    [region_code] nvarchar(10) NOT NULL,
    [city] nvarchar(50) NULL,
    [state] nvarchar(50) NULL,
    [country] nvarchar(50) NULL,
    [country_latitude] decimal(10,6) NULL,
    [country_longitude] decimal(10,6) NULL,
    [region] nvarchar(50) NULL,
    [market] nvarchar(50) NULL
);
GO

-- Primary keys, unique constraints, indexes
ALTER TABLE [e_commerce].[customer] ADD CONSTRAINT [PK_customer] PRIMARY KEY CLUSTERED ([customer_id]);
ALTER TABLE [e_commerce].[ecom_sales] ADD CONSTRAINT [PK_ecom_sales] PRIMARY KEY CLUSTERED ([row_id]);
ALTER TABLE [e_commerce].[product] ADD CONSTRAINT [PK_product] PRIMARY KEY CLUSTERED ([product_code]);
ALTER TABLE [e_commerce].[region] ADD CONSTRAINT [PK_region] PRIMARY KEY CLUSTERED ([region_code]);
GO

-- Foreign keys
GO
