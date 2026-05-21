CREATE OR REPLACE TABLE {gold_player_stats} AS
SELECT
  p.player_id,
  p.name,
  p.team_id,
  p.team_name,
  p.position,
  p.nationality,
  p.age,
  p.jersey_number,
  t.league_id
FROM {silver_players} p
LEFT JOIN (
  SELECT home_team_id AS team_id, league_id FROM {silver_fixtures}
  UNION DISTINCT
  SELECT away_team_id AS team_id, league_id FROM {silver_fixtures}
) t ON p.team_id = t.team_id
