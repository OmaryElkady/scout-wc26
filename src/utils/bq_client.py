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
        """Streaming insert via insert_rows_json. Kept for backwards compatibility,
        but new Bronze writes should use replace_rows() instead — streaming-inserted
        rows can't be DELETE'd for up to 90 minutes (streaming buffer), which breaks
        the idempotent per-key write pattern that prevents Bronze bloat.
        """
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

    def delete_rows(self, table_name: str, where_sql: str) -> int:
        """Delete rows from table_name matching where_sql. Returns affected row count.

        DELETE requires that the target rows are NOT in the streaming buffer
        (~90 min after streaming insert). Bronze writers should use load jobs
        (via replace_rows) so this constraint never fires.
        """
        table_id = config.table(table_name)
        sql = f"DELETE FROM `{table_id}` WHERE {where_sql}"
        logger.info("DELETE on %s WHERE %s", table_id, where_sql)
        job = self._conn().query(sql)
        job.result()
        return int(getattr(job, "num_dml_affected_rows", 0) or 0)

    def replace_rows(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
        where_sql: str | None = None,
    ) -> None:
        """Idempotent upsert: optionally DELETE matching rows, then append via load job.

        Use this for Bronze writes instead of insert_rows so each refresh
        replaces the prior copy of (e.g. a team's squad, a league's fixtures)
        instead of stacking another duplicate set on top.

        Load jobs are used (not streaming) so the freshly-loaded rows can be
        deleted on the next call — streaming inserts sit in a buffer for up to
        90 minutes and block DELETE.

        Args
        ----
        table_name : bare table name (e.g. "bronze_fixtures")
        rows : list of dicts; keys must match the table schema
        where_sql : optional SQL fragment for the DELETE step. If None, the
            function just appends (no replacement). Pass an empty-string-safe
            value like "1=1" to clear the entire table.
        """
        if not rows and where_sql is None:
            return

        if where_sql is not None:
            try:
                self.delete_rows(table_name, where_sql)
            except Exception as exc:
                # First-run case: table may exist but the column referenced in
                # where_sql may not (e.g. new league_id column on legacy schema).
                # Log and continue — the load below still writes the new data.
                logger.warning(
                    "replace_rows: DELETE failed on %s (continuing with append): %s",
                    table_name,
                    exc,
                )

        if not rows:
            return

        table_id = config.table(table_name)
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            # Don't auto-detect — trust the existing table schema.
            schema_update_options=[],
        )
        logger.info("Load-appending %d rows to %s", len(rows), table_id)
        job = self._conn().load_table_from_json(rows, table_id, job_config=job_config)
        job.result()

    def table_exists(self, table_name: str) -> bool:
        table_id = config.table(table_name)
        try:
            self._conn().get_table(table_id)
            return True
        except NotFound:
            return False


bq = BigQueryClient()
