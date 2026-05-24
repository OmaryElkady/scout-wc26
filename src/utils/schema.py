import logging

from google.cloud import bigquery

from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)

# fmt: off
_BRONZE_SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    "bronze_fixtures": [
        bigquery.SchemaField("fixture_id",      "STRING"),
        bigquery.SchemaField("home_team_id",    "STRING"),
        bigquery.SchemaField("home_team_name",  "STRING"),
        bigquery.SchemaField("away_team_id",    "STRING"),
        bigquery.SchemaField("away_team_name",  "STRING"),
        bigquery.SchemaField("match_date",      "STRING"),
        bigquery.SchemaField("status",          "STRING"),
        bigquery.SchemaField("home_score",      "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("away_score",      "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("league_id",       "STRING"),
        bigquery.SchemaField("season",          "INTEGER"),
        bigquery.SchemaField("raw_json",        "STRING"),
        bigquery.SchemaField("ingested_at",     "TIMESTAMP"),
        bigquery.SchemaField("source",          "STRING"),
    ],
    "bronze_players": [
        bigquery.SchemaField("player_id",       "STRING"),
        bigquery.SchemaField("team_id",         "STRING"),
        bigquery.SchemaField("team_name",       "STRING"),
        bigquery.SchemaField("name",            "STRING"),
        bigquery.SchemaField("position",        "STRING"),
        bigquery.SchemaField("nationality",     "STRING"),
        bigquery.SchemaField("age",             "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("jersey_number",   "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("raw_json",        "STRING"),
        bigquery.SchemaField("ingested_at",     "TIMESTAMP"),
        bigquery.SchemaField("source",          "STRING"),
    ],
    "bronze_team_squads": [
        bigquery.SchemaField("team_id",         "STRING"),
        bigquery.SchemaField("team_name",       "STRING"),
        bigquery.SchemaField("player_id",       "STRING"),
        bigquery.SchemaField("player_name",     "STRING"),
        bigquery.SchemaField("position",        "STRING"),
        bigquery.SchemaField("raw_json",        "STRING"),
        bigquery.SchemaField("ingested_at",     "TIMESTAMP"),
        bigquery.SchemaField("source",          "STRING"),
    ],
    "bronze_top_performers": [
        bigquery.SchemaField("player_id",       "STRING"),
        bigquery.SchemaField("player_name",     "STRING"),
        bigquery.SchemaField("team_id",         "STRING"),
        bigquery.SchemaField("team_name",       "STRING"),
        bigquery.SchemaField("goals",           "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("assists",         "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("rating",          "FLOAT",   mode="NULLABLE"),
        bigquery.SchemaField("stat_type",       "STRING"),
        bigquery.SchemaField("ingested_at",     "TIMESTAMP"),
        bigquery.SchemaField("source",          "STRING"),
    ],
}
# fmt: on


def create_all_bronze_tables() -> None:
    """Create all Bronze tables if they do not already exist.

    Safe to call on every run — exists_ok=True means no error if already present.
    """
    client = bq._conn()
    for table_name, schema in _BRONZE_SCHEMAS.items():
        table_id = config.table(table_name)
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table, exists_ok=True)
        logger.info("Bronze table ready: %s", table_id)


# fmt: off
_SILVER_SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    "silver_fixtures": [
        bigquery.SchemaField("fixture_id",      "STRING"),
        bigquery.SchemaField("home_team_id",    "STRING"),
        bigquery.SchemaField("home_team_name",  "STRING"),
        bigquery.SchemaField("away_team_id",    "STRING"),
        bigquery.SchemaField("away_team_name",  "STRING"),
        bigquery.SchemaField("match_date",      "DATE"),
        bigquery.SchemaField("status",          "STRING"),
        bigquery.SchemaField("home_score",      "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("away_score",      "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("league_id",       "STRING"),
        bigquery.SchemaField("season",          "INTEGER"),
        bigquery.SchemaField("source",          "STRING"),
        bigquery.SchemaField("ingested_at",     "TIMESTAMP"),
        bigquery.SchemaField("is_completed",    "BOOL"),
    ],
    "silver_players": [
        bigquery.SchemaField("player_id",       "STRING"),
        bigquery.SchemaField("team_id",         "STRING"),
        bigquery.SchemaField("team_name",       "STRING"),
        bigquery.SchemaField("name",            "STRING"),
        bigquery.SchemaField("position",        "STRING"),
        bigquery.SchemaField("nationality",     "STRING"),
        bigquery.SchemaField("age",             "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("jersey_number",   "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("source",          "STRING"),
        bigquery.SchemaField("ingested_at",     "TIMESTAMP"),
    ],
}

_GOLD_SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    "gold_player_stats": [
        bigquery.SchemaField("player_id",       "STRING"),
        bigquery.SchemaField("name",            "STRING"),
        bigquery.SchemaField("team_id",         "STRING"),
        bigquery.SchemaField("team_name",       "STRING"),
        bigquery.SchemaField("position",        "STRING"),
        bigquery.SchemaField("nationality",     "STRING"),
        bigquery.SchemaField("age",             "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("jersey_number",   "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("league_id",       "STRING",  mode="NULLABLE"),
    ],
    "gold_team_summary": [
        bigquery.SchemaField("team_id",         "STRING"),
        bigquery.SchemaField("team_name",       "STRING"),
        bigquery.SchemaField("matches_played",  "INTEGER"),
        bigquery.SchemaField("wins",            "INTEGER"),
        bigquery.SchemaField("draws",           "INTEGER"),
        bigquery.SchemaField("losses",          "INTEGER"),
        bigquery.SchemaField("goals_for",       "INTEGER"),
        bigquery.SchemaField("goals_against",   "INTEGER"),
        bigquery.SchemaField("goal_difference", "INTEGER"),
        bigquery.SchemaField("points",          "INTEGER"),
    ],
    "gold_match_results": [
        bigquery.SchemaField("fixture_id",      "STRING"),
        bigquery.SchemaField("home_team_name",  "STRING"),
        bigquery.SchemaField("away_team_name",  "STRING"),
        bigquery.SchemaField("home_score",      "INTEGER"),
        bigquery.SchemaField("away_score",      "INTEGER"),
        bigquery.SchemaField("match_date",      "DATE"),
        bigquery.SchemaField("winner",          "STRING"),
        bigquery.SchemaField("goal_difference", "INTEGER"),
        bigquery.SchemaField("total_goals",     "INTEGER"),
    ],
    "gold_top_performers": [
        bigquery.SchemaField("player_id",       "STRING"),
        bigquery.SchemaField("player_name",     "STRING"),
        bigquery.SchemaField("team_name",       "STRING"),
        bigquery.SchemaField("goals",           "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("assists",         "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("rating",          "FLOAT",   mode="NULLABLE"),
        bigquery.SchemaField("stat_type",       "STRING"),
        bigquery.SchemaField("rank",            "INTEGER"),
    ],
}
# fmt: on


def create_all_silver_tables() -> None:
    client = bq._conn()
    for table_name, schema in _SILVER_SCHEMAS.items():
        table_id = config.table(table_name)
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table, exists_ok=True)
        logger.info("Silver table ready: %s", table_id)


def create_all_gold_tables() -> None:
    client = bq._conn()
    for table_name, schema in _GOLD_SCHEMAS.items():
        table_id = config.table(table_name)
        table = bigquery.Table(table_id, schema=schema)
        client.create_table(table, exists_ok=True)
        logger.info("Gold table ready: %s", table_id)


def create_all_tables() -> None:
    create_all_bronze_tables()
    create_all_silver_tables()
    create_all_gold_tables()
