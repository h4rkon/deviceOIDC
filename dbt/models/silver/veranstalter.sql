{{ config(
  materialized='incremental',
  incremental_strategy='merge',
  unique_key='veranstalter_id',
  views_enabled=false
) }}

with cdc as (
  select
    after.id as veranstalter_id,
    after.name as name,
    after.region as region,
    op as cdc_op,
    ts_ms as cdc_ts_ms
  from {{ source('bronze', 'veranstalter') }}
  where after is not null
  {% if is_incremental() %}
    and ts_ms > (select coalesce(max(cdc_ts_ms), 0) from {{ this }})
  {% endif %}
),
deduped as (
  select
    *,
    row_number() over (
      partition by veranstalter_id
      order by cdc_ts_ms desc
    ) as rn
  from cdc
)
select
  veranstalter_id,
  name,
  region,
  cdc_op,
  cdc_ts_ms
from deduped
where rn = 1
