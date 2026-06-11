from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import NotFound

from src.utils.bq_client import BigQueryClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_with_mock() -> tuple[BigQueryClient, MagicMock]:
    """Return a BigQueryClient with a pre-injected MagicMock GCP client."""
    client = BigQueryClient()
    mock_gcp = MagicMock()
    client._client = mock_gcp
    return client, mock_gcp


# ---------------------------------------------------------------------------
# run_query
# ---------------------------------------------------------------------------


def test_run_query_returns_list_of_dicts():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.query.return_value.result.return_value = [
        {"player_id": "1", "name": "Mbappe"},
        {"player_id": "2", "name": "Vinicius"},
    ]

    result = bq.run_query("SELECT * FROM gold_players LIMIT 2")

    assert result == [
        {"player_id": "1", "name": "Mbappe"},
        {"player_id": "2", "name": "Vinicius"},
    ]


def test_run_query_empty_result_returns_empty_list():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.query.return_value.result.return_value = []

    result = bq.run_query("SELECT * FROM gold_players WHERE 1=0")

    assert result == []


def test_run_query_calls_gcp_client_with_sql():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.query.return_value.result.return_value = []
    sql = "SELECT player_id FROM gold_players"

    bq.run_query(sql)

    mock_gcp.query.assert_called_once_with(sql)


# ---------------------------------------------------------------------------
# insert_rows (legacy streaming path — still used by tests and some callers)
# ---------------------------------------------------------------------------


def test_insert_rows_succeeds_when_no_errors():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.insert_rows_json.return_value = []  # empty list = success

    bq.insert_rows("bronze_raw", [{"col": "val"}])  # should not raise


def test_insert_rows_raises_on_partial_failure():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.insert_rows_json.return_value = [
        {"index": 0, "errors": [{"reason": "invalid", "message": "bad row"}]}
    ]

    with pytest.raises(RuntimeError, match="insert_rows_json failed"):
        bq.insert_rows("bronze_raw", [{"col": "bad_val"}])


def test_insert_rows_skips_api_call_for_empty_list():
    bq, mock_gcp = _client_with_mock()

    bq.insert_rows("bronze_raw", [])

    mock_gcp.insert_rows_json.assert_not_called()


def test_insert_rows_passes_full_table_id_to_gcp(monkeypatch):
    """Table ID must be the fully-qualified project.dataset.table string."""
    bq, mock_gcp = _client_with_mock()
    mock_gcp.insert_rows_json.return_value = []

    from src.utils import config as config_module

    monkeypatch.setattr(config_module.config, "PROJECT_ID", "my-project")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "my_dataset")

    bq.insert_rows("gold_players", [{"id": "1"}])

    mock_gcp.insert_rows_json.assert_called_once_with(
        "my-project.my_dataset.gold_players", [{"id": "1"}]
    )


# ---------------------------------------------------------------------------
# delete_rows
# ---------------------------------------------------------------------------


def test_delete_rows_runs_dml_query(monkeypatch):
    bq, mock_gcp = _client_with_mock()
    job = MagicMock()
    job.num_dml_affected_rows = 7
    mock_gcp.query.return_value = job

    from src.utils import config as config_module

    monkeypatch.setattr(config_module.config, "PROJECT_ID", "p")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "d")

    affected = bq.delete_rows("bronze_fixtures", "league_id = '42'")

    mock_gcp.query.assert_called_once_with(
        "DELETE FROM `p.d.bronze_fixtures` WHERE league_id = '42'"
    )
    assert affected == 7


def test_delete_rows_returns_zero_when_num_affected_missing():
    bq, mock_gcp = _client_with_mock()
    job = MagicMock()
    job.num_dml_affected_rows = None
    mock_gcp.query.return_value = job

    affected = bq.delete_rows("bronze_fixtures", "1=1")

    assert affected == 0


# ---------------------------------------------------------------------------
# replace_rows
# ---------------------------------------------------------------------------


def test_replace_rows_deletes_then_loads_when_where_supplied():
    bq, mock_gcp = _client_with_mock()
    # delete_rows path
    del_job = MagicMock()
    del_job.num_dml_affected_rows = 0
    mock_gcp.query.return_value = del_job
    # load_table_from_json path
    load_job = MagicMock()
    mock_gcp.load_table_from_json.return_value = load_job

    bq.replace_rows("bronze_fixtures", [{"x": 1}], where_sql="league_id = '42'")

    # Both DELETE and LOAD must have been invoked
    assert mock_gcp.query.called, "DELETE step must run when where_sql is supplied"
    assert mock_gcp.load_table_from_json.called, "Load step must run after DELETE"


def test_replace_rows_skips_delete_when_where_is_none():
    bq, mock_gcp = _client_with_mock()
    load_job = MagicMock()
    mock_gcp.load_table_from_json.return_value = load_job

    bq.replace_rows("bronze_fixtures", [{"x": 1}], where_sql=None)

    mock_gcp.query.assert_not_called()
    assert mock_gcp.load_table_from_json.called


def test_replace_rows_skips_load_for_empty_rows_with_where():
    """where_sql with empty rows still runs the DELETE (so the table is cleared)
    but does not call the load API."""
    bq, mock_gcp = _client_with_mock()
    del_job = MagicMock()
    del_job.num_dml_affected_rows = 0
    mock_gcp.query.return_value = del_job

    bq.replace_rows("bronze_fixtures", [], where_sql="1=1")

    mock_gcp.query.assert_called_once()
    mock_gcp.load_table_from_json.assert_not_called()


def test_replace_rows_skips_everything_when_empty_rows_and_no_where():
    bq, mock_gcp = _client_with_mock()

    bq.replace_rows("bronze_fixtures", [], where_sql=None)

    mock_gcp.query.assert_not_called()
    mock_gcp.load_table_from_json.assert_not_called()


def test_replace_rows_continues_when_delete_fails():
    """First-run case: DELETE may fail on a fresh table; load must still run."""
    bq, mock_gcp = _client_with_mock()
    mock_gcp.query.side_effect = RuntimeError("column not found")
    load_job = MagicMock()
    mock_gcp.load_table_from_json.return_value = load_job

    bq.replace_rows("bronze_fixtures", [{"x": 1}], where_sql="league_id = '42'")

    assert mock_gcp.load_table_from_json.called


# ---------------------------------------------------------------------------
# table_exists
# ---------------------------------------------------------------------------


def test_table_exists_returns_true_when_found():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.get_table.return_value = MagicMock()  # found — no exception

    assert bq.table_exists("gold_players") is True


def test_table_exists_returns_false_on_not_found():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.get_table.side_effect = NotFound("table not found")

    assert bq.table_exists("gold_players") is False


def test_table_exists_lets_unexpected_exceptions_bubble():
    bq, mock_gcp = _client_with_mock()
    mock_gcp.get_table.side_effect = PermissionError("no access")

    with pytest.raises(PermissionError):
        bq.table_exists("gold_players")


# ---------------------------------------------------------------------------
# Lazy client initialisation
# ---------------------------------------------------------------------------


def test_gcp_client_not_created_at_instantiation(monkeypatch):
    """BigQueryClient() must not call bigquery.Client() until first use."""
    from unittest.mock import patch

    with patch("src.utils.bq_client.bigquery.Client") as mock_constructor:
        _ = BigQueryClient()
        mock_constructor.assert_not_called()
