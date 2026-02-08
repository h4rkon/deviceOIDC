SELECT
  veranstalter_id,
  betriebsstaette_id,
  COUNT(*) AS anzahl_status_queries
FROM dataplatform.status_abfrage
GROUP BY
  veranstalter_id,
  betriebsstaette_id;
