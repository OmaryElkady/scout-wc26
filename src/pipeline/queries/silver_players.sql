CREATE OR REPLACE TABLE {silver_players} AS
SELECT
  player_id,
  team_id,
  team_name,
  name,
  -- The API returns abbreviations, often as comma-separated multi-role strings
  -- (e.g. "CDM,CM" or "CB,LB"). Extract the first (primary) token and map it.
  CASE TRIM(SPLIT(UPPER(COALESCE(position, '')), ',')[SAFE_OFFSET(0)])
    -- Goalkeeper
    WHEN 'GK'          THEN 'GK'
    WHEN 'GOALKEEPER'  THEN 'GK'
    -- Defenders
    WHEN 'CB'          THEN 'DEF'
    WHEN 'RB'          THEN 'DEF'
    WHEN 'LB'          THEN 'DEF'
    WHEN 'RWB'         THEN 'DEF'
    WHEN 'LWB'         THEN 'DEF'
    WHEN 'DEF'         THEN 'DEF'
    WHEN 'DEFENDER'    THEN 'DEF'
    WHEN 'CENTRE-BACK' THEN 'DEF'
    WHEN 'CENTER-BACK' THEN 'DEF'
    -- Midfielders
    WHEN 'CM'          THEN 'MID'
    WHEN 'CDM'         THEN 'MID'
    WHEN 'CAM'         THEN 'MID'
    WHEN 'LM'          THEN 'MID'
    WHEN 'RM'          THEN 'MID'
    WHEN 'DM'          THEN 'MID'
    WHEN 'AM'          THEN 'MID'
    WHEN 'MID'         THEN 'MID'
    WHEN 'MIDFIELDER'  THEN 'MID'
    -- Forwards
    WHEN 'ST'          THEN 'FWD'
    WHEN 'LW'          THEN 'FWD'
    WHEN 'RW'          THEN 'FWD'
    WHEN 'CF'          THEN 'FWD'
    WHEN 'SS'          THEN 'FWD'
    WHEN 'FW'          THEN 'FWD'
    WHEN 'FWD'         THEN 'FWD'
    WHEN 'FORWARD'     THEN 'FWD'
    WHEN 'ATTACKER'    THEN 'FWD'
    WHEN 'STRIKER'     THEN 'FWD'
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
