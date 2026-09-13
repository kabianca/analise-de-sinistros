{#-
  The extract date a run is replaying. Set on the command line
  (--vars '{"as_of": "2017-03-31"}') it pins the snapshot to that extract
  and the fact to claims received by that day. Left unset, it is the latest
  extract in raw, so an ad-hoc `dbt build` does the obvious thing.
-#}
{% macro as_of() -%}
    {%- if var('as_of') -%}
        '{{ var("as_of") }}'::date
    {%- else -%}
        (select max(extract_date) from {{ source('raw', 'segurados_extract') }})
    {%- endif -%}
{%- endmacro %}
