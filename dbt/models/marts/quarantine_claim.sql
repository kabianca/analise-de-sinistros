{#-
  Every staged claim the fact could not attribute, with the reason. A row
  that cannot be placed in history is a finding, not noise: it is either a
  bad reference in the feed or a cancellation nobody told the claims
  system about, and both are someone's job. Rebuilt in full on every step,
  so the fact and this table always partition the staged claims.
-#}

with claims as (
    select *
    from {{ ref('stg_claim') }}
    where reception_date <= {{ as_of() }}
),

known_insured as (
    select distinct insured_id from {{ ref('dim_insured') }}
),

-- The version, deleted marker included, covering the occurrence day.
insured_version as (
    select
        c.claim_id,
        i.insured_sk,
        i.is_deleted
    from claims as c
    inner join {{ ref('dim_insured') }} as i
        on i.insured_id = c.insured_id
        and i.valid_from::date <= c.occurrence_date
        and (i.valid_to is null or c.occurrence_date < i.valid_to::date)
),

policy_version as (
    select
        c.claim_id,
        p.policy_sk
    from claims as c
    inner join {{ ref('dim_policy') }} as p
        on p.policy_id = c.policy_id
        and p.valid_from::date <= c.occurrence_date
        and (p.valid_to is null or c.occurrence_date < p.valid_to::date)
        and not p.is_deleted
)

select
    c.claim_id,
    c.insured_id,
    c.policy_id,
    c.occurrence_date,
    c.reception_date,
    c.diagnosis_code,
    c.benefit_group,
    c.submitted_amount,
    c.paid_amount,
    c.source_file,
    case
        when k.insured_id is null then 'unknown_insured'
        when iv.is_deleted then 'insured_cancelled'
        when iv.insured_sk is null then 'no_version_at_occurrence'
        when pv.policy_sk is null then 'no_policy_version_at_occurrence'
    end as reason,
    {{ as_of() }} as quarantined_as_of
from claims as c
left join known_insured as k on k.insured_id = c.insured_id
left join insured_version as iv on iv.claim_id = c.claim_id
left join policy_version as pv on pv.claim_id = c.claim_id
where
    k.insured_id is null
    or iv.insured_sk is null
    or iv.is_deleted
    or pv.policy_sk is null
