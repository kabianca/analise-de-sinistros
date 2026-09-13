{#-
  History of the insured table, one row per version, built by replaying
  the extracts. The timestamp strategy trusts the source's updated_at: a
  version starts when the source says the row changed, not when the
  warehouse noticed. A key that stops appearing gets its last version
  closed and a deleted marker opened (hard_deletes: new_record), so a
  cancellation is a fact in the history, not an absence.

  The filter is inside the snapshot on purpose: a staging view that
  filtered on as_of would be compiled under one replay step and read,
  stale, by the next.
-#}
{% snapshot snap_insured %}

{{
    config(
        unique_key='insured_id',
        strategy='timestamp',
        updated_at='updated_at',
        hard_deletes='new_record',
        snapshot_meta_column_names={
            'dbt_scd_id': 'insured_sk',
            'dbt_valid_from': 'valid_from',
            'dbt_valid_to': 'valid_to',
            'dbt_updated_at': 'source_updated_at',
            'dbt_is_deleted': 'deleted_flag',
        },
    )
}}

select
    insured_id,
    sex,
    birth_date,
    marital_status,
    region,
    created_at,
    updated_at
from {{ ref('stg_insured') }}
where extract_date = {{ as_of() }}

{% endsnapshot %}
