-- ICD-10 codes as the source spells them, from the seed. A Type 0
-- dimension: a code's meaning does not change, so it has no versions.
select
    diagnosis_code,
    description,
    chapter,
    chronic_group,
    chronic_group is not null as is_chronic
from {{ ref('cid10') }}
