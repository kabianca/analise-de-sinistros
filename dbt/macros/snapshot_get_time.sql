{#-
  When a key disappears from the source, dbt closes its version and opens
  the deleted marker at "now". In a replay, "now" is the wall clock of the
  machine running the replay, years after the fact. Overriding the adapter's
  macro makes the deletion effective at the first instant after the extract
  that no longer lists the key: the end of the as_of day. Without a replay
  variable, it is the wall clock again, as dbt intends.
-#}
{% macro postgres__snapshot_get_time() -%}
    {%- if var('as_of') -%}
        ('{{ var("as_of") }}'::date + 1)::timestamp
    {%- else -%}
        {{ current_timestamp() }}::timestamp without time zone
    {%- endif -%}
{%- endmacro %}
