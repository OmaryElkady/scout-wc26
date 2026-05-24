from unittest.mock import MagicMock, patch

from src.utils.schema import create_all_bronze_tables

_EXPECTED_TABLES = {"bronze_fixtures", "bronze_players", "bronze_team_squads", "bronze_top_performers"}


def _run(mock_config_table_return: str = "p.d.t") -> tuple[MagicMock, MagicMock]:
    """Run create_all_bronze_tables() with BQ and config mocked; return (mock_client, mock_config)."""
    mock_client = MagicMock()
    with patch("src.utils.schema.bq") as mock_bq, \
         patch("src.utils.schema.config") as mock_config:
        mock_bq._conn.return_value = mock_client
        mock_config.table.return_value = mock_config_table_return
        create_all_bronze_tables()
    return mock_client, mock_config


def test_creates_four_bronze_tables():
    mock_client, _ = _run()
    assert mock_client.create_table.call_count == 4


def test_exists_ok_true_on_every_call():
    mock_client, _ = _run()
    for c in mock_client.create_table.call_args_list:
        assert c.kwargs.get("exists_ok") is True


def test_uses_config_table_for_all_ids():
    _, mock_config = _run()
    assert mock_config.table.call_count == 4
    called_with = {c.args[0] for c in mock_config.table.call_args_list}
    assert called_with == _EXPECTED_TABLES
