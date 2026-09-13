{#-
  Exactly one open version per business key: none means the key vanished
  from history, two means a re-run inserted a duplicate.
-#}
{% test one_current_per_key(model, column_name, valid_to) %}

select
    {{ column_name }} as business_key,
    count(*) filter (where {{ valid_to }} is null) as open_versions
from {{ model }}
group by 1
having count(*) filter (where {{ valid_to }} is null) <> 1

{% endtest %}
