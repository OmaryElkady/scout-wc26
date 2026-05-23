CREATE OR REPLACE TABLE {gold_match_results} AS
SELECT
  fixture_id,
  home_team_name,
  away_team_name,
  home_score,
  away_score,
  match_date,
  CASE WHEN home_score > away_score THEN home_team_name
       WHEN away_score > home_score THEN away_team_name
       ELSE 'Draw' END AS winner,
  ABS(home_score - away_score) AS goal_difference,
  home_score + away_score AS total_goals
FROM `{silver_fixtures}`
WHERE is_completed = TRUE
AND home_score IS NOT NULL
AND away_score IS NOT NULL
