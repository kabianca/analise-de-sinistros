{#-
  One row per claim, at the grain the source promised: claim_id is the
  merge key, so a month replayed twice lands twice on the same rows. Each
  claim points at the version of the insured and of the policy that was in
  force on the day it happened; the attributes themselves stay in the
  dimensions, and the current ones are one join away through is_current.

  A day is the grain of the attribution. Claims carry a date, so a change
  stamped anywhere on day d counts for all of day d.

  The window is the reception month of as_of. Late claims (received a
  month or two after they happened) enter with their reception month and
  are still attributed by their occurrence date: that is the whole point.
-#}
{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='claim_id',
    )
}}

with claims as (
    select *
    from {{ ref('stg_claim') }}
    where reception_date <= {{ as_of() }}
    {% if is_incremental() %}
        and reception_date >= date_trunc('month', {{ as_of() }})::date
    {% endif %}
)

select
    c.claim_id,
    i.insured_sk,
    p.policy_sk,
    c.diagnosis_code,
    to_char(c.occurrence_date, 'YYYYMMDD')::integer as occurrence_date_key,
    to_char(c.reception_date, 'YYYYMMDD')::integer as reception_date_key,
    c.occurrence_date,
    c.reception_date,
    c.benefit_group,
    c.submitted_amount,
    c.paid_amount,
    -- A measure of the event, not an attribute of the person: the legacy
    -- CSV carried "edad" on every row and it drifted with the extract.
    extract(year from age(c.occurrence_date, i.birth_date))::integer as age_at_occurrence,
    {{ as_of() }} as loaded_as_of
from claims as c
inner join {{ ref('dim_insured') }} as i
    on i.insured_id = c.insured_id
    and i.valid_from::date <= c.occurrence_date
    and (i.valid_to is null or c.occurrence_date < i.valid_to::date)
    and not i.is_deleted
inner join {{ ref('dim_policy') }} as p
    on p.policy_id = c.policy_id
    and p.valid_from::date <= c.occurrence_date
    and (p.valid_to is null or c.occurrence_date < p.valid_to::date)
    and not p.is_deleted
