{{ config(
  materialized='incremental',
  incremental_strategy='merge',
  unique_key='player_id',
  views_enabled=false
) }}

with cdc as (
  select
    after.id as player_id,
    after.vorname as vorname,
    after.nachname as nachname,
    after.geburtsdatum as geburtsdatum,
    op as cdc_op,
    ts_ms as cdc_ts_ms
  from {{ source('bronze', 'player') }}
  where after is not null
  {% if is_incremental() %}
    and ts_ms > (select coalesce(max(cdc_ts_ms), 0) from {{ this }})
  {% endif %}
),
deduped as (
  select
    *,
    row_number() over (
      partition by player_id
      order by cdc_ts_ms desc
    ) as rn
  from cdc
)
select
  player_id,
  vorname,
  nachname,
  geburtsdatum,
  cdc_op,
  cdc_ts_ms
from deduped
where rn = 1
