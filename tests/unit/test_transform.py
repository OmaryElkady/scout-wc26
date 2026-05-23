from unittest.mock import MagicMock, call, patch


def _make_mocks():
    mock_bq = MagicMock()
    mock_bq.run_query.return_value = []
    mock_config = MagicMock()
    mock_config.table.side_effect = lambda name: f"proj.ds.{name}"
    return mock_bq, mock_config


def test_run_silver_transforms_calls_both_sql_files():
    mock_bq, mock_config = _make_mocks()
    with patch("src.pipeline.transform.bq", mock_bq), patch(
        "src.pipeline.transform.config", mock_config
    ):
        from src.pipeline import transform

        transform.run_silver_transforms()

    assert mock_bq.run_query.call_count == 2
    sqls = [c.args[0] for c in mock_bq.run_query.call_args_list]
    assert any("silver_fixtures" in sql for sql in sqls)
    assert any("silver_players" in sql for sql in sqls)


def test_run_silver_transforms_references_bronze_sources():
    mock_bq, mock_config = _make_mocks()
    with patch("src.pipeline.transform.bq", mock_bq), patch(
        "src.pipeline.transform.config", mock_config
    ):
        from src.pipeline import transform

        transform.run_silver_transforms()

    sqls = [c.args[0] for c in mock_bq.run_query.call_args_list]
    assert any("bronze_fixtures" in sql for sql in sqls)
    assert any("bronze_players" in sql for sql in sqls)


def test_run_gold_transforms_calls_both_sql_files():
    mock_bq, mock_config = _make_mocks()
    with patch("src.pipeline.transform.bq", mock_bq), patch(
        "src.pipeline.transform.config", mock_config
    ):
        from src.pipeline import transform

        transform.run_gold_transforms()

    assert mock_bq.run_query.call_count == 3
    sqls = [c.args[0] for c in mock_bq.run_query.call_args_list]
    assert any("gold_player_stats" in sql for sql in sqls)
    assert any("gold_team_summary" in sql for sql in sqls)
    assert any("gold_match_results" in sql for sql in sqls)


def test_run_gold_transforms_references_silver_sources():
    mock_bq, mock_config = _make_mocks()
    with patch("src.pipeline.transform.bq", mock_bq), patch(
        "src.pipeline.transform.config", mock_config
    ):
        from src.pipeline import transform

        transform.run_gold_transforms()

    sqls = [c.args[0] for c in mock_bq.run_query.call_args_list]
    assert any("silver_players" in sql for sql in sqls)
    assert any("silver_fixtures" in sql for sql in sqls)


def test_run_all_calls_silver_before_gold():
    mock_bq, mock_config = _make_mocks()
    call_order: list[str] = []

    def track_query(sql: str):
        # Gold queries reference silver tables too — detect by the CREATE target.
        if "CREATE OR REPLACE TABLE proj.ds.gold_" in sql:
            call_order.append("gold")
        elif "CREATE OR REPLACE TABLE proj.ds.silver_" in sql:
            call_order.append("silver")
        return []

    mock_bq.run_query.side_effect = track_query

    with patch("src.pipeline.transform.bq", mock_bq), patch(
        "src.pipeline.transform.config", mock_config
    ):
        from src.pipeline import transform

        transform.run_all()

    assert mock_bq.run_query.call_count == 5
    silver_indices = [i for i, v in enumerate(call_order) if v == "silver"]
    gold_indices = [i for i, v in enumerate(call_order) if v == "gold"]
    assert silver_indices, "No silver queries ran"
    assert gold_indices, "No gold queries ran"
    assert max(silver_indices) < min(gold_indices), "Silver must run before gold"


def test_run_all_total_query_count():
    mock_bq, mock_config = _make_mocks()
    with patch("src.pipeline.transform.bq", mock_bq), patch(
        "src.pipeline.transform.config", mock_config
    ):
        from src.pipeline import transform

        transform.run_all()

    assert mock_bq.run_query.call_count == 5
