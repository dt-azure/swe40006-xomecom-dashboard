{#-
    Models land in the schema their folder names (silver, gold) exactly, not dbt's default
    "<target_schema>_<custom>". The dashboard contract names gold.* directly; keep this macro.
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
