{% macro band_mid(level, country, department) -%}
{%- set b = var('pay_bands') -%}
(case {{ level }}{% for k, v in b['mid_de'].items() %} when '{{ k }}' then {{ v }}{% endfor %} end
 * case {{ country }}{% for k, v in b['country_factor'].items() %} when '{{ k }}' then {{ v }}{% endfor %} else 1.0 end
 * case {{ department }}{% for k, v in b['family_premium'].items() %} when '{{ k }}' then {{ v }}{% endfor %} else 1.0 end)
{%- endmacro %}
