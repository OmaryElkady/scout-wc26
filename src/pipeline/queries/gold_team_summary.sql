CREATE OR REPLACE TABLE {gold_team_summary} AS
WITH completed AS (
  SELECT * FROM {silver_fixtures}
  WHERE is_completed = TRUE
),
home_stats AS (
  SELECT
    home_team_id AS team_id,
    home_team_name AS team_name,
    league_id,
    COUNT(*) AS matches_played,
    COUNTIF(home_score > away_score) AS wins,
    COUNTIF(home_score = away_score) AS draws,
    COUNTIF(home_score < away_score) AS losses,
    SUM(home_score) AS goals_for,
    SUM(away_score) AS goals_against
  FROM completed
  GROUP BY home_team_id, home_team_name, league_id
),
away_stats AS (
  SELECT
    away_team_id AS team_id,
    away_team_name AS team_name,
    league_id,
    COUNT(*) AS matches_played,
    COUNTIF(away_score > home_score) AS wins,
    COUNTIF(away_score = home_score) AS draws,
    COUNTIF(away_score < home_score) AS losses,
    SUM(away_score) AS goals_for,
    SUM(home_score) AS goals_against
  FROM completed
  GROUP BY away_team_id, away_team_name, league_id
),
combined AS (
  SELECT * FROM home_stats
  UNION ALL
  SELECT * FROM away_stats
)
SELECT
  team_id,
  MAX(team_name) AS team_name,
  league_id,
  SUM(matches_played) AS matches_played,
  SUM(wins) AS wins,
  SUM(draws) AS draws,
  SUM(losses) AS losses,
  SUM(goals_for) AS goals_for,
  SUM(goals_against) AS goals_against,
  SUM(goals_for) - SUM(goals_against) AS goal_difference,
  SUM(wins) * 3 + SUM(draws) AS points
FROM combined
GROUP BY team_id, league_id
