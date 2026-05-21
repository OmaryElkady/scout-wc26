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
# insert_rows
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
