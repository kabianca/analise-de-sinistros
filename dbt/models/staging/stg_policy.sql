select
    extract_date,
    cod_apolice::integer as policy_id,
    num_afiliado::integer as insured_id,
    desc_producto_agrupado as product,
    desc_tipo_contrat as contract_type,
    flag_programa::integer = 1 as in_programme,
    fecha_ingreso::date as programme_entry_date,
    created_at::timestamp as created_at,
    updated_at::timestamp as updated_at,
    source_file
from {{ source('raw', 'apolices_extract') }}
