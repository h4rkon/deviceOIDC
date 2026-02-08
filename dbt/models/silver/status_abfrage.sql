{{ config(materialized='table') }}

with cdc as (
  select
    after.unique_identifier as unique_identifier,
    after.status_ts as status_ts,
    after.veranstalter_id as veranstalter_id,
    after.betriebsstaette_id as betriebsstaette_id,
    after.geraete_id as geraete_id,
    after.vorname as vorname,
    after.nachname as nachname,
    after.geburtsdatum as geburtsdatum,
    op as cdc_op,
    ts_ms as cdc_ts_ms
  from {{ source('bronze', 'status_abfrage') }}
  where after is not null
),
deduped as (
  select
    *,
    row_number() over (
      partition by unique_identifier
      order by cdc_ts_ms desc
    ) as rn
  from cdc
)
select
  unique_identifier,
  status_ts,
  veranstalter_id,
  betriebsstaette_id,
  geraete_id,
  vorname,
  nachname,
  geburtsdatum,
  cdc_op,
  cdc_ts_ms
from deduped
where rn = 1
