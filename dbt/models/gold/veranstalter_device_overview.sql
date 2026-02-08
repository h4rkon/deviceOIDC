{{ config(materialized='table') }}

{% set from_ms = var('from_cdc_ts_ms', none) %}
{% set until_ms = var('until_cdc_ts_ms', none) %}
{% set veranstalter_filter = var('veranstalter_id', none) %}

with filtered as (
  select
    veranstalter_id,
    betriebsstaette_id,
    geraete_id,
    cdc_ts_ms
  from {{ ref('status_abfrage') }}
  where 1 = 1
  {% if from_ms is not none %}
    and cdc_ts_ms >= {{ from_ms }}
  {% endif %}
  {% if until_ms is not none %}
    and cdc_ts_ms <= {{ until_ms }}
  {% endif %}
  {% if veranstalter_filter is not none %}
    and veranstalter_id = '{{ veranstalter_filter }}'
  {% endif %}
)
select
  veranstalter_id,
  betriebsstaette_id,
  geraete_id,
  count(*) as query_count,
  min(cdc_ts_ms) as first_cdc_ts_ms,
  max(cdc_ts_ms) as last_cdc_ts_ms
from filtered
group by veranstalter_id, betriebsstaette_id, geraete_id
order by veranstalter_id, betriebsstaette_id, geraete_id
