{% macro landing(name) -%}
read_parquet('{{ var("landing") }}/{{ name }}.parquet')
{%- endmacro %}
