{#-
    Filter for incremental models: rows newer than this model's newest row, minus a lookback that
    catches a bronze batch which committed late with an earlier ingested_at. The merge on
    unique_key makes the re-read overlap harmless.
-#}
{% macro ingested_since_last_run(column='ingested_at') -%}
    {{ column }} > (
        select coalesce(max(ingested_at), '-infinity'::timestamptz)
            - interval '{{ var("incremental_lookback_minutes", 10) }} minutes'
        from {{ this }}
    )
{%- endmacro %}
