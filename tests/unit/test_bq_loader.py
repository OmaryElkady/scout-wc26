from datetime import datetime
from unittest.mock import call, patch

import pytest

from src.ingestion.bq_loader import (
    write_bronze_fixtures,
    write_bronze_players,
    write_bronze_standings,
    write_bronze_top_performers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_insert(fn, rows):
    """Call fn(rows) with bq.insert_rows mocked; return the rows passed to it."""
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        fn(rows)
        assert mock_bq.replace_rows.called, "Bronze writers must use replace_rows for idempotent inserts"
        # replace_rows(table, rows, where_sql=...) — positional args[0:2]
        args = mock_bq.replace_rows.call_args[0]
        _table = args[0]
        inserted = args[1]
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
        mock_bq.replace_rows.assert_not_called()


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


def _capture_fixtures(rows, league_id=None):
    """Call write_bronze_fixtures with optional league_id; return (table, rows)."""
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        if league_id is None:
            write_bronze_fixtures(rows)
        else:
            write_bronze_fixtures(rows, league_id=league_id)
        assert mock_bq.replace_rows.called
        args = mock_bq.replace_rows.call_args[0]
        _table = args[0]
        inserted = args[1]
        return _table, inserted


def test_write_bronze_fixtures_targets_correct_table():
    table, _ = _capture_fixtures([{"fixture_id": "10"}])
    assert table == "bronze_fixtures"


def test_write_bronze_fixtures_adds_metadata():
    _, rows = _capture_fixtures([{"fixture_id": "10"}])
    assert "ingested_at" in rows[0]
    assert rows[0]["source"] == "free-api-live-football-data"


def test_write_bronze_fixtures_skips_on_empty_input():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_fixtures([])
        mock_bq.replace_rows.assert_not_called()


def test_write_bronze_fixtures_uses_explicit_league_id():
    """Caller-supplied league_id wins over module-level _WORLD_CUP_LEAGUE_ID."""
    _, rows = _capture_fixtures([{"id": "fx-1", "home": {"id": 5}, "away": {"id": 6}}], league_id=42)
    assert rows[0]["league_id"] == "42"


def test_write_bronze_fixtures_does_not_re_tag_with_active_league():
    """Regression: switching the active league must NOT re-tag fixtures from
    a previous league when the caller passes an explicit league_id.

    Reproduces the PSG-vs-Arsenal-shows-WORLD-CUP-2026 bug: if you fetched
    UCL fixtures (league 42) and the active league is later swapped to 77,
    re-writing those fixtures with league_id=42 (their real origin) must
    keep them tagged 42 — not pick up the new active league.
    """
    import src.ingestion.bq_loader as loader_mod

    # Simulate: active league has been swapped to World Cup 2026 (77),
    # but we're writing UCL fixtures we fetched earlier under league 42.
    with patch.object(loader_mod, "_WORLD_CUP_LEAGUE_ID", 77):
        _, rows = _capture_fixtures(
            [
                {"id": "fx-psg-ars", "home": {"id": 85, "name": "PSG"},
                 "away": {"id": 42, "name": "Arsenal"}}
            ],
            league_id=42,
        )
    assert rows[0]["league_id"] == "42", (
        "Fixture must keep its real league_id (42=UCL), not pick up the "
        "current active league (77=WC2026)."
    )


def test_write_bronze_fixtures_falls_back_to_active_league_when_unspecified():
    """Backwards-compat: callers that don't pass league_id get the module global."""
    import src.ingestion.bq_loader as loader_mod

    with patch.object(loader_mod, "_WORLD_CUP_LEAGUE_ID", 10195):
        _, rows = _capture_fixtures([{"id": "fx-x", "home": {}, "away": {}}])
    assert rows[0]["league_id"] == "10195"


def test_write_bronze_fixtures_tags_all_rows_with_same_league_id():
    """All fixtures in a single batch share the supplied league_id."""
    _, rows = _capture_fixtures(
        [{"id": "fx-a"}, {"id": "fx-b"}, {"id": "fx-c"}],
        league_id=140,
    )
    assert [r["league_id"] for r in rows] == ["140", "140", "140"]


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
        mock_bq.replace_rows.assert_not_called()


# ---------------------------------------------------------------------------
# write_bronze_top_performers
# ---------------------------------------------------------------------------

_SAMPLE_SCORER = {"id": 10, "name": "Ronaldo", "teamId": 5, "teamName": "Portugal", "goals": 12}
_SAMPLE_ASSISTER = {"id": 20, "name": "Mbappe", "teamId": 3, "teamName": "France", "assists": 7}
_SAMPLE_RATED = {"id": 30, "name": "Bellingham", "teamId": 7, "teamName": "England", "rating": 8.73}


def test_write_bronze_top_performers_targets_correct_table():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([_SAMPLE_SCORER], [], [])
        table = mock_bq.replace_rows.call_args[0][0]
    assert table == "bronze_top_performers"


def test_write_bronze_top_performers_adds_ingested_at():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([_SAMPLE_SCORER], [], [])
        # replace_rows(table, rows, where_sql=...) — args[0]=table, args[1]=rows
        rows = mock_bq.replace_rows.call_args[0][1]
    assert "ingested_at" in rows[0]
    datetime.fromisoformat(rows[0]["ingested_at"])


def test_write_bronze_top_performers_adds_source():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([_SAMPLE_SCORER], [], [])
        # replace_rows(table, rows, where_sql=...) — args[0]=table, args[1]=rows
        rows = mock_bq.replace_rows.call_args[0][1]
    assert rows[0]["source"] == "free-api-live-football-data"


def test_write_bronze_top_performers_maps_scorer_fields():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([_SAMPLE_SCORER], [], [])
        # replace_rows(table, rows, where_sql=...) — args[0]=table, args[1]=rows
        rows = mock_bq.replace_rows.call_args[0][1]
    row = rows[0]
    assert row["player_id"] == "10"
    assert row["player_name"] == "Ronaldo"
    assert row["team_id"] == "5"
    assert row["team_name"] == "Portugal"
    assert row["goals"] == 12
    assert row["assists"] is None
    assert row["rating"] is None
    assert row["stat_type"] == "goals"


def test_write_bronze_top_performers_maps_assister_fields():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([], [_SAMPLE_ASSISTER], [])
        # replace_rows(table, rows, where_sql=...) — args[0]=table, args[1]=rows
        rows = mock_bq.replace_rows.call_args[0][1]
    row = rows[0]
    assert row["player_id"] == "20"
    assert row["assists"] == 7
    assert row["goals"] is None
    assert row["stat_type"] == "assists"


def test_write_bronze_top_performers_maps_rated_fields():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([], [], [_SAMPLE_RATED])
        # replace_rows(table, rows, where_sql=...) — args[0]=table, args[1]=rows
        rows = mock_bq.replace_rows.call_args[0][1]
    row = rows[0]
    assert row["player_id"] == "30"
    assert row["rating"] == 8.73
    assert row["goals"] is None
    assert row["assists"] is None
    assert row["stat_type"] == "rating"


def test_write_bronze_top_performers_merges_all_three_lists():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([_SAMPLE_SCORER], [_SAMPLE_ASSISTER], [_SAMPLE_RATED])
        # replace_rows(table, rows, where_sql=...) — args[0]=table, args[1]=rows
        rows = mock_bq.replace_rows.call_args[0][1]
    assert len(rows) == 3
    stat_types = {r["stat_type"] for r in rows}
    assert stat_types == {"goals", "assists", "rating"}


def test_write_bronze_top_performers_skips_on_all_empty():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([], [], [])
        mock_bq.replace_rows.assert_not_called()


def test_write_bronze_top_performers_all_rows_share_ingested_at():
    with patch("src.ingestion.bq_loader.bq") as mock_bq:
        write_bronze_top_performers([_SAMPLE_SCORER], [_SAMPLE_ASSISTER], [_SAMPLE_RATED])
        # replace_rows(table, rows, where_sql=...) — args[0]=table, args[1]=rows
        rows = mock_bq.replace_rows.call_args[0][1]
    timestamps = {r["ingested_at"] for r in rows}
    assert len(timestamps) == 1  # all share the same timestamp
