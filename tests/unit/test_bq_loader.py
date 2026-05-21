from datetime import datetime
from unittest.mock import call, patch

import pytest

from src.ingestion.bq_loader import (
    write_bronze_fixtures,
    write_bronze_players,
    write_bronze_standings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_insert(fn, rows):
    """Call fn(rows) with bq.insert_rows mocked; return the rows passed to it."""
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        fn(rows)
        assert mock_bq.insert_rows.called
        _table, inserted = mock_bq.insert_rows.call_args[0]
        return _table, inserted


# ---------------------------------------------------------------------------
# write_bronze_players
# ---------------------------------------------------------------------------


def test_write_bronze_players_calls_insert_rows():
    table, _ = _capture_insert(write_bronze_players, [{"player_id": "1"}])
    assert table == "bronze_players"


def test_write_bronze_players_adds_ingested_at():
    _, rows = _capture_insert(write_bronze_players, [{"player_id": "1"}])
    assert "ingested_at" in rows[0]
    datetime.fromisoformat(rows[0]["ingested_at"])  # raises if not valid ISO


def test_write_bronze_players_adds_source():
    _, rows = _capture_insert(write_bronze_players, [{"player_id": "1"}])
    assert rows[0]["source"] == "free-api-live-football-data"


def test_write_bronze_players_preserves_original_fields():
    _, rows = _capture_insert(write_bronze_players, [{"player_id": "42", "name": "Mbappe"}])
    assert rows[0]["player_id"] == "42"
    assert rows[0]["name"] == "Mbappe"


def test_write_bronze_players_does_not_mutate_input():
    original = [{"player_id": "1"}]
    with patch("src.ingestion.bq_loader.bq"):
        write_bronze_players(original)
    assert original == [{"player_id": "1"}]  # unchanged


def test_write_bronze_players_skips_on_empty_input():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_players([])
        mock_bq.insert_rows.assert_not_called()


def test_write_bronze_players_stamps_all_rows():
    input_rows = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    _, rows = _capture_insert(write_bronze_players, input_rows)
    assert len(rows) == 3
    for row in rows:
        assert "ingested_at" in row
        assert "source" in row


def test_write_bronze_players_all_rows_share_same_ingested_at():
    input_rows = [{"id": "1"}, {"id": "2"}]
    _, rows = _capture_insert(write_bronze_players, input_rows)
    assert rows[0]["ingested_at"] == rows[1]["ingested_at"]


# ---------------------------------------------------------------------------
# write_bronze_fixtures
# ---------------------------------------------------------------------------


def test_write_bronze_fixtures_targets_correct_table():
    table, _ = _capture_insert(write_bronze_fixtures, [{"fixture_id": "10"}])
    assert table == "bronze_fixtures"


def test_write_bronze_fixtures_adds_metadata():
    _, rows = _capture_insert(write_bronze_fixtures, [{"fixture_id": "10"}])
    assert "ingested_at" in rows[0]
    assert rows[0]["source"] == "free-api-live-football-data"


def test_write_bronze_fixtures_skips_on_empty_input():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_fixtures([])
        mock_bq.insert_rows.assert_not_called()


# ---------------------------------------------------------------------------
# write_bronze_standings
# ---------------------------------------------------------------------------


def test_write_bronze_standings_targets_correct_table():
    table, _ = _capture_insert(write_bronze_standings, [{"team": "Brazil"}])
    assert table == "bronze_standings"


def test_write_bronze_standings_adds_metadata():
    _, rows = _capture_insert(write_bronze_standings, [{"team": "Brazil"}])
    assert "ingested_at" in rows[0]
    assert rows[0]["source"] == "free-api-live-football-data"


def test_write_bronze_standings_skips_on_empty_input():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_standings([])
        mock_bq.insert_rows.assert_not_called()
