import logging
from pathlib import Path

from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)

_QUERIES_DIR = Path(__file__).parent / "queries"


def load_query(filename: str) -> str:
    return (_QUERIES_DIR / filename).read_text()


def _table_map() -> dict[str, str]:
    return {
        "bronze_fixtures": config.table("bronze_fixtures"),
        "bronze_players": config.table("bronze_players"),
        "bronze_top_performers": config.table("bronze_top_performers"),
        "silver_fixtures": config.table("silver_fixtures"),
        "silver_players": config.table("silver_players"),
        "gold_player_stats": config.table("gold_player_stats"),
        "gold_team_summary": config.table("gold_team_summary"),
        "gold_match_results": config.table("gold_match_results"),
        "gold_top_performers": config.table("gold_top_performers"),
    }


def run_silver_transforms() -> None:
    tables = _table_map()
    for filename in ("silver_fixtures.sql", "silver_players.sql"):
        sql = load_query(filename).format(**tables)
        logger.info("Running silver transform: %s", filename)
        bq.run_query(sql)
        logger.info("Completed silver transform: %s", filename)


def run_gold_transforms() -> None:
    tables = _table_map()
    for filename in ("gold_player_stats.sql", "gold_team_summary.sql", "gold_match_results.sql"):
        sql = load_query(filename).format(**tables)
        logger.info("Running gold transform: %s", filename)
        bq.run_query(sql)
        logger.info("Completed gold transform: %s", filename)
    # Top performers is supplementary — non-fatal if bronze_top_performers is empty
    try:
        sql = load_query("gold_top_performers.sql").format(**tables)
        logger.info("Running gold transform: gold_top_performers.sql")
        bq.run_query(sql)
        logger.info("Completed gold transform: gold_top_performers.sql")
    except Exception as exc:
        logger.warning("gold_top_performers.sql failed (non-fatal): %s", exc)


def run_all() -> None:
    logger.info("Starting full pipeline: Bronze → Silver → Gold")
    run_silver_transforms()
    run_gold_transforms()
    logger.info("Pipeline complete")
