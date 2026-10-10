{#- Use the target schema as-is (gld / ci_gld) instead of dbt's default <target>_<custom> concat. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ target.schema }}
{%- endmacro %}
