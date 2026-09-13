{#-
  A Type 2 dimension is a partition of time per key: versions ordered by
  valid_from must touch (no gap) and not cross (no overlap), and only the
  last one may be open. One test for both dimensions; a row comes back for
  every version that breaks the chain.
-#}
{% test scd2_contiguous(model, column_name, valid_from, valid_to) %}

with ordered as (
    select
        {{ column_name }} as business_key,
        {{ valid_from }} as valid_from,
        {{ valid_to }} as valid_to,
        lead({{ valid_from }}) over (partition by {{ column_name }} order by {{ valid_from }}) as next_valid_from
    from {{ model }}
)

select *
from ordered
where
    -- a closed version must end exactly where the next one starts
    (next_valid_from is not null and valid_to is distinct from next_valid_from)
    -- the last version must be open
    or (next_valid_from is null and valid_to is not null)
    -- and no version may be empty or inverted
    or (valid_to is not null and valid_to <= valid_from)

{% endtest %}
