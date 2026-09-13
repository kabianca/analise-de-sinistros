-- A cancellation is the end of a key's history: the deleted marker is the
-- last version, it is open, and nothing real follows it.
select insured_id, valid_from, valid_to
from {{ ref('dim_insured') }}
where is_deleted and (valid_to is not null or not is_current)
