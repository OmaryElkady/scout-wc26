import logging
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from src.utils.config import config

logger = logging.getLogger(__name__)


class BigQueryClient:
    def __init__(self) -> None:
        # Lazy: actual GCP client is created on first use, not at import time.
        self._client: bigquery.Client | None = None

    def _conn(self) -> bigquery.Client:
        if self._client is None:
            self._client = bigquery.Client(project=config.PROJECT_ID)
        return self._client

    def run_query(self, sql: str) -> list[dict[str, Any]]:
        logger.info("Running BigQuery query")
        rows = self._conn().query(sql).result()
        return [dict(row) for row in rows]

    def insert_rows(self, table_name: str, rows: list[dict[str, Any]], chunk_size: int = 500) -> None:
        if not rows:
            return
        table_id = config.table(table_name)
        logger.info("Inserting %d rows into %s (chunk_size=%d)", len(rows), table_id, chunk_size)
        # insert_rows_json does NOT raise on partial failure — always check.
        # Chunking avoids payload-size and timeout limits on large batches.
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            errors = self._conn().insert_rows_json(table_id, chunk)
            if errors:
                raise RuntimeError(
                    f"BigQuery insert_rows_json failed for {table_id} "
                    f"(chunk {i}–{i + len(chunk)}): {errors}"
                )

    def table_exists(self, table_name: str) -> bool:
        table_id = config.table(table_name)
        try:
            self._conn().get_table(table_id)
            return True
        except NotFound:
            return False


bq = BigQueryClient()
