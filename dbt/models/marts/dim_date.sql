-- A calendar wide enough for the history and a year either side.
with days as (
    select generate_series('2015-01-01'::date, '2019-12-31'::date, interval '1 day')::date as full_date
)

select
    to_char(full_date, 'YYYYMMDD')::integer as date_key,
    full_date,
    extract(year from full_date)::integer as year,
    extract(quarter from full_date)::integer as quarter,
    extract(month from full_date)::integer as month,
    to_char(full_date, 'YYYY-MM') as year_month,
    extract(isodow from full_date)::integer as iso_day_of_week,
    extract(isodow from full_date) >= 6 as is_weekend
from days
