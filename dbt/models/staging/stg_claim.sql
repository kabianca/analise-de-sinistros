-- One row per claim. The source sends some rows twice; the first arrival
-- wins, by the order the loader received them, and the count of the rest
-- is visible by comparing with raw.
with typed as (
    select
        row_no,
        cod_sinistro::integer as claim_id,
        num_afiliado::integer as insured_id,
        cod_apolice::integer as policy_id,
        fec_ocurrencia::date as occurrence_date,
        fec_recepcao::date as reception_date,
        cod_diagnostico as diagnosis_code,
        agrupbenef as benefit_group,
        gasto_presentado::numeric(12, 2) as submitted_amount,
        beneficio_pagado::numeric(12, 2) as paid_amount,
        source_file
    from {{ source('raw', 'sinistros') }}
),

ranked as (
    select
        *,
        row_number() over (partition by claim_id order by row_no) as arrival
    from typed
)

select
    claim_id,
    insured_id,
    policy_id,
    occurrence_date,
    reception_date,
    diagnosis_code,
    benefit_group,
    submitted_amount,
    paid_amount,
    source_file
from ranked
where arrival = 1
