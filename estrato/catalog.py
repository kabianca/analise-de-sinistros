"""Reference values the generator draws from.

The diagnosis codes keep the source system's spelling from the legacy CSV
(`I10X`, `E119`: ICD-10 without the dot, `X` as filler), because the
generator imitates that system. The same list is checked in as
dbt/seeds/cid10.csv, which is where the warehouse reads descriptions from;
a test holds the two copies together.
"""

# (code, description, chapter, chronic group or None)
CID10 = [
    ("I10X", "Hipertensao essencial (primaria)", "IX", "HTA"),
    ("I119", "Doenca cardiaca hipertensiva sem insuficiencia cardiaca", "IX", "HTA"),
    ("I159", "Hipertensao secundaria nao especificada", "IX", "HTA"),
    ("E119", "Diabetes mellitus tipo 2 sem complicacoes", "IV", "DM"),
    ("E116", "Diabetes mellitus tipo 2 com outras complicacoes", "IV", "DM"),
    ("E109", "Diabetes mellitus tipo 1 sem complicacoes", "IV", "DM"),
    ("E149", "Diabetes mellitus nao especificado sem complicacoes", "IV", "DM"),
    ("J069", "Infeccao aguda das vias aereas superiores nao especificada", "X", None),
    ("J459", "Asma nao especificada", "X", None),
    ("M545", "Dor lombar baixa", "XIII", None),
    ("M791", "Mialgia", "XIII", None),
    ("K297", "Gastrite nao especificada", "XI", None),
    ("K802", "Calculose da vesicula biliar sem colecistite", "XI", None),
    ("N390", "Infeccao do trato urinario de localizacao nao especificada", "XIV", None),
    ("Z000", "Exame medico geral", "XXI", None),
    ("R51X", "Cefaleia", "XVIII", None),
    ("A09X", "Diarreia e gastroenterite de origem infecciosa presumivel", "I", None),
    ("H524", "Presbiopia", "VII", None),
    ("L309", "Dermatite nao especificada", "XII", None),
    ("I209", "Angina pectoris nao especificada", "IX", None),
    ("S525", "Fratura da extremidade distal do radio", "XIX", None),
]

CHRONIC_CODES = {g: [c for c, _, _, grp in CID10 if grp == g] for g in ("HTA", "DM")}
GENERAL_CODES = [c for c, _, _, grp in CID10 if grp is None]

# Benefit groups as the source spells them; the first is what the legacy
# notebook filtered on to isolate the prevention programme.
BENEFIT_PROGRAMME = "PROGRAMAS CRONICOS"
BENEFIT_GENERAL = ["AMBULATORIO", "HOSPITALARIO", "FARMACIA"]

# Contract types. REGULAR is everyone outside the programme; the programme
# ones carry the disease and, with SP ("sem protocolo"), whether the insured
# is exempt from the medication protocol. The legacy CSV had a few more,
# too rare to matter here.
CONTRACT_REGULAR = "PACIENTE MES REGULAR"
CONTRACT_PAY_PER_SERVICE = "PAGO POR SERVICIO"
CONTRACT_PROGRAMME = {
    "HTA": ["PACIENTE MES HTA", "PACIENTE MES HTA SP"],
    "DM": ["PACIENTE MES DIABETES", "PACIENTE MES DIABETES SP"],
}

PRODUCTS = ["EPS", "AMC", "AMI"]
SEXES = ["M", "F"]
# C casado, S solteiro, V viuvo, D divorciado, U uniao estavel. None is the
# 5 % of missing values the legacy CSV had; a later correction from None to
# a value is a change like any other, and the model must keep both.
MARITAL = ["C", "S", "V", "D", "U", None]
# L capital (Lisboa), P provincia, N nao informado.
REGIONS = ["L", "P", "N"]

# The source's file layouts: what the generator writes and the loader reads.
INSURED_COLUMNS = [
    "num_afiliado",
    "sexo",
    "data_nascimento",
    "estado_civil",
    "ind_capital_provincia",
    "created_at",
    "updated_at",
]
POLICY_COLUMNS = [
    "cod_apolice",
    "num_afiliado",
    "desc_producto_agrupado",
    "desc_tipo_contrat",
    "flag_programa",
    "fecha_ingreso",
    "created_at",
    "updated_at",
]
CLAIM_COLUMNS = [
    "cod_sinistro",
    "num_afiliado",
    "cod_apolice",
    "fec_ocurrencia",
    "fec_recepcao",
    "cod_diagnostico",
    "agrupbenef",
    "gasto_presentado",
    "beneficio_pagado",
]
