CREATE OR REPLACE TABLE {silver_fixtures} AS
SELECT
  fixture_id,
  home_team_id,
  home_team_name,
  away_team_id,
  away_team_name,
  CAST(match_date AS DATE) AS match_date,
  status,
  home_score,
  away_score,
  league_id,
  season,
  source,
  ingested_at,
  LOWER(status) = 'finished' AS is_completed
FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY fixture_id ORDER BY ingested_at DESC) AS rn
  FROM {bronze_fixtures}
)
WHERE rn = 1
