{{ config(
  materialized='incremental',
  incremental_strategy='merge',
  unique_key='geraete_id',
  views_enabled=false
) }}

with cdc as (
  select
    after.id as geraete_id,
    after.serial as serial,
    after.model as model,
    op as cdc_op,
    ts_ms as cdc_ts_ms
  from {{ source('bronze', 'geraet') }}
  where after is not null
  {% if is_incremental() %}
    and ts_ms > (select coalesce(max(cdc_ts_ms), 0) from {{ this }})
  {% endif %}
),
deduped as (
  select
    *,
    row_number() over (
      partition by geraete_id
      order by cdc_ts_ms desc
    ) as rn
  from cdc
)
select
  geraete_id,
  serial,
  model,
  cdc_op,
  cdc_ts_ms
from deduped
where rn = 1
