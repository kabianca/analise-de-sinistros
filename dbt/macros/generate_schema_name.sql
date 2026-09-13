{#-
  dbt's default prefixes a custom schema with the target schema
  (marts_staging, marts_snapshots). Four flat schemas -- raw, staging,
  snapshots, marts -- read better in psql and in the README, and there is
  one target, so the prefix protects nothing.
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
