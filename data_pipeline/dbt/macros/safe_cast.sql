{#-
    Casts from payload text that return NULL instead of failing the build when a value is not
    in the expected shape. A bad source value must not stop every later transform; silver flags
    it (has_invalid_value) instead. NULL stays NULL.
-#}
{% macro safe_integer(expr) -%}
    case when ({{ expr }}) ~ '^\s*-?\d+\s*$' then ({{ expr }})::integer end
{%- endmacro %}

{% macro safe_numeric(expr) -%}
    case when ({{ expr }}) ~ '^\s*-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$' then ({{ expr }})::numeric end
{%- endmacro %}

{% macro safe_date(expr) -%}
    case when ({{ expr }}) ~ '^\s*\d{4}-\d{2}-\d{2}\s*$' then ({{ expr }})::date end
{%- endmacro %}
