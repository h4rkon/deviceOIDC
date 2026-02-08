{{ config(
  materialized='incremental',
  incremental_strategy='merge',
  unique_key='assignment_id',
  views_enabled=false
) }}

with cdc as (
  select
    after.id as assignment_id,
    after.geraet_id as geraete_id,
    after.veranstalter_id as veranstalter_id,
    after.betriebsstaette_id as betriebsstaette_id,
    after.valid_from as valid_from,
    after.valid_to as valid_to,
    op as cdc_op,
    ts_ms as cdc_ts_ms
  from {{ source('bronze', 'device_assignment') }}
  where after is not null
  {% if is_incremental() %}
    and ts_ms > (select coalesce(max(cdc_ts_ms), 0) from {{ this }})
  {% endif %}
),
deduped as (
  select
    *,
    row_number() over (
      partition by assignment_id
      order by cdc_ts_ms desc
    ) as rn
  from cdc
)
select
  assignment_id,
  geraete_id,
  veranstalter_id,
  betriebsstaette_id,
  valid_from,
  valid_to,
  cdc_op,
  cdc_ts_ms
from deduped
where rn = 1
