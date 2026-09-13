{% snapshot snap_policy %}

{{
    config(
        unique_key='policy_id',
        strategy='timestamp',
        updated_at='updated_at',
        hard_deletes='new_record',
        snapshot_meta_column_names={
            'dbt_scd_id': 'policy_sk',
            'dbt_valid_from': 'valid_from',
            'dbt_valid_to': 'valid_to',
            'dbt_updated_at': 'source_updated_at',
            'dbt_is_deleted': 'deleted_flag',
        },
    )
}}

select
    policy_id,
    insured_id,
    product,
    contract_type,
    in_programme,
    programme_entry_date,
    created_at,
    updated_at
from {{ ref('stg_policy') }}
where extract_date = {{ as_of() }}

{% endsnapshot %}
