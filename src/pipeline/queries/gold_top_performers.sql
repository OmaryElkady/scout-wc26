-- One row per player per stat_type. Bronze can contain multiple snapshots
-- of the same player across refreshes (e.g. once as "Manchester City" via a
-- club-league sync with 27 goals, once as "Norway" via a national-team sync
-- with 16). Pick the snapshot with the HIGHEST stat value per (player_id,
-- stat_type) — never two rows for one player, and never the lower tally.
CREATE OR REPLACE TABLE {gold_top_performers} AS
WITH best AS (
  SELECT
    player_id,
    player_name,
    team_name,
    goals,
    assists,
    rating,
    stat_type,
    ingested_at
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (
        PARTITION BY player_id, stat_type
        -- Rank by the relevant stat first (NULLs LAST so a populated row wins
        -- over an empty one), then by ingested_at as a deterministic tiebreak.
        ORDER BY
          CASE stat_type
            WHEN 'goals'   THEN CAST(goals   AS FLOAT64)
            WHEN 'assists' THEN CAST(assists AS FLOAT64)
            WHEN 'rating'  THEN rating
          END DESC NULLS LAST,
          ingested_at DESC
      ) AS _rn
    FROM `{bronze_top_performers}`
  )
  WHERE _rn = 1
),
goals_ranked AS (
  SELECT
    player_id,
    player_name,
    team_name,
    goals,
    CAST(NULL AS INT64) AS assists,
    CAST(NULL AS FLOAT64) AS rating,
    'goals' AS stat_type,
    ROW_NUMBER() OVER (ORDER BY goals DESC) AS rank
  FROM best
  WHERE stat_type = 'goals' AND goals IS NOT NULL
),
assists_ranked AS (
  SELECT
    player_id,
    player_name,
    team_name,
    CAST(NULL AS INT64) AS goals,
    assists,
    CAST(NULL AS FLOAT64) AS rating,
    'assists' AS stat_type,
    ROW_NUMBER() OVER (ORDER BY assists DESC) AS rank
  FROM best
  WHERE stat_type = 'assists' AND assists IS NOT NULL
),
rated_ranked AS (
  SELECT
    player_id,
    player_name,
    team_name,
    CAST(NULL AS INT64) AS goals,
    CAST(NULL AS INT64) AS assists,
    rating,
    'rating' AS stat_type,
    ROW_NUMBER() OVER (ORDER BY rating DESC) AS rank
  FROM best
  WHERE stat_type = 'rating' AND rating IS NOT NULL
)
SELECT * FROM goals_ranked
UNION ALL SELECT * FROM assists_ranked
UNION ALL SELECT * FROM rated_ranked
