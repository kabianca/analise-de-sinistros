-- Nothing vanishes and nothing is counted twice: every staged claim
-- received by as_of is in the fact or in quarantine, never both, never
-- neither.
with staged as (
    select claim_id from {{ ref('stg_claim') }} where reception_date <= {{ as_of() }}
),

placed as (
    select claim_id, 'fact' as place from {{ ref('fct_claim') }}
    union all
    select claim_id, 'quarantine' as place from {{ ref('quarantine_claim') }}
),

counted as (
    select
        s.claim_id,
        count(p.claim_id) as places
    from staged as s
    left join placed as p on p.claim_id = s.claim_id
    group by s.claim_id
)

select * from counted where places <> 1
