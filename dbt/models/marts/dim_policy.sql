select
    policy_sk,
    policy_id,
    insured_id,
    product,
    contract_type,
    in_programme,
    programme_entry_date,
    valid_from,
    valid_to,
    valid_to is null as is_current,
    deleted_flag = 'True' as is_deleted,
    source_updated_at,
    created_at
from {{ ref('snap_policy') }}
