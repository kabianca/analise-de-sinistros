select claim_id, submitted_amount, paid_amount
from {{ ref('fct_claim') }}
where paid_amount > submitted_amount or paid_amount < 0
