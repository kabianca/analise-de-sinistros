-- The version a claim points at covered the day the claim happened. This
-- is the sentence the whole model exists to make true: a 2016 claim is
-- reported under 2016 attributes, whatever the insured looks like today.
select
    f.claim_id,
    f.occurrence_date,
    i.valid_from,
    i.valid_to
from {{ ref('fct_claim') }} as f
inner join {{ ref('dim_insured') }} as i on i.insured_sk = f.insured_sk
where
    f.occurrence_date < i.valid_from::date
    or (i.valid_to is not null and f.occurrence_date >= i.valid_to::date)
    or i.is_deleted
