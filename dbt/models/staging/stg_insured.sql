-- Every extract of the insured table, typed and renamed. No filter: the
-- snapshot picks the extract it is replaying, so a view built under one
-- as_of is never stale under the next.
select
    extract_date,
    num_afiliado::integer as insured_id,
    sexo as sex,
    data_nascimento::date as birth_date,
    estado_civil as marital_status,
    ind_capital_provincia as region,
    created_at::timestamp as created_at,
    updated_at::timestamp as updated_at,
    source_file
from {{ source('raw', 'segurados_extract') }}
