-- One row per version of an insured. The surrogate key is dbt's hash of
-- (business key, source updated_at): the same version hashes to the same
-- key on every replay, which an integer sequence would not promise.
select
    insured_sk,
    insured_id,
    sex,
    birth_date,
    marital_status,
    region,
    valid_from,
    valid_to,
    valid_to is null as is_current,
    deleted_flag = 'True' as is_deleted,
    source_updated_at,
    created_at
from {{ ref('snap_insured') }}
