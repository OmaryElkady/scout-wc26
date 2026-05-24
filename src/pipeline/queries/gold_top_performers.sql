CREATE OR REPLACE TABLE {gold_top_performers} AS
WITH goals_ranked AS (
  SELECT
    player_id,
    player_name,
    team_name,
    MAX(goals) AS goals,
    CAST(NULL AS INT64) AS assists,
    CAST(NULL AS FLOAT64) AS rating,
    'goals' AS stat_type,
    ROW_NUMBER() OVER (ORDER BY MAX(goals) DESC) AS rank
  FROM `{bronze_top_performers}`
  WHERE stat_type = 'goals' AND goals IS NOT NULL
  GROUP BY player_id, player_name, team_name
),
assists_ranked AS (
  SELECT
    player_id,
    player_name,
    team_name,
    CAST(NULL AS INT64) AS goals,
    MAX(assists) AS assists,
    CAST(NULL AS FLOAT64) AS rating,
    'assists' AS stat_type,
    ROW_NUMBER() OVER (ORDER BY MAX(assists) DESC) AS rank
  FROM `{bronze_top_performers}`
  WHERE stat_type = 'assists' AND assists IS NOT NULL
  GROUP BY player_id, player_name, team_name
),
rated_ranked AS (
  SELECT
    player_id,
    player_name,
    team_name,
    CAST(NULL AS INT64) AS goals,
    CAST(NULL AS INT64) AS assists,
    MAX(rating) AS rating,
    'rating' AS stat_type,
    ROW_NUMBER() OVER (ORDER BY MAX(rating) DESC) AS rank
  FROM `{bronze_top_performers}`
  WHERE stat_type = 'rating' AND rating IS NOT NULL
  GROUP BY player_id, player_name, team_name
)
SELECT * FROM goals_ranked
UNION ALL SELECT * FROM assists_ranked
UNION ALL SELECT * FROM rated_ranked
