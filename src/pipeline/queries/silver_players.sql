CREATE OR REPLACE TABLE {silver_players} AS
SELECT
  player_id,
  team_id,
  team_name,
  name,
  CASE
    WHEN UPPER(position) IN ('GOALKEEPER', 'GK') THEN 'GK'
    WHEN UPPER(position) IN (
      'DEFENDER', 'DEF', 'CENTRE-BACK', 'CENTER-BACK',
      'LEFT BACK', 'RIGHT BACK', 'CB', 'LB', 'RB',
      'LEFT WING-BACK', 'RIGHT WING-BACK'
    ) THEN 'DEF'
    WHEN UPPER(position) IN (
      'MIDFIELDER', 'MID', 'CENTRAL MIDFIELD', 'LEFT MIDFIELD',
      'RIGHT MIDFIELD', 'ATTACKING MIDFIELD', 'DEFENSIVE MIDFIELD',
      'CM', 'CAM', 'CDM', 'LM', 'RM'
    ) THEN 'MID'
    WHEN UPPER(position) IN (
      'FORWARD', 'FWD', 'ATTACKER', 'CENTRE-FORWARD', 'CENTER-FORWARD',
      'LEFT WING', 'RIGHT WING', 'STRIKER', 'ST', 'LW', 'RW', 'CF'
    ) THEN 'FWD'
    ELSE 'UNKNOWN'
  END AS position,
  nationality,
  age,
  jersey_number,
  source,
  ingested_at
FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY player_id, team_id ORDER BY ingested_at DESC) AS rn
  FROM {bronze_players}
)
WHERE rn = 1
