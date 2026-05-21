import pytest

from src.utils.config import Config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_REQUIRED_ENV = {
    "GOOGLE_CLOUD_PROJECT": "test-project",
    "GOOGLE_CLOUD_REGION": "us-central1",
    "BQ_DATASET": "test_dataset",
    "FIVETRAN_API_KEY": "test-fivetran-key",
    "FIVETRAN_API_SECRET": "test-fivetran-secret",
    "FIVETRAN_CONNECTOR_ID": "test-connector-id",
    "RAPIDAPI_KEY": "test-rapidapi-key",
    "RAPIDAPI_HOST": "free-api-live-football-data.p.rapidapi.com",
}


@pytest.fixture()
def full_env(monkeypatch):
    """Set all required env vars plus sensible optional defaults."""
    for k, v in _REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("API_PORT", "8000")


# ---------------------------------------------------------------------------
# Loading / attribute mapping
# ---------------------------------------------------------------------------


def test_config_maps_all_attributes(full_env):
    cfg = Config()
    assert cfg.PROJECT_ID == "test-project"
    assert cfg.REGION == "us-central1"
    assert cfg.BQ_DATASET == "test_dataset"
    assert cfg.FIVETRAN_API_KEY == "test-fivetran-key"
    assert cfg.FIVETRAN_API_SECRET == "test-fivetran-secret"
    assert cfg.FIVETRAN_CONNECTOR_ID == "test-connector-id"
    assert cfg.RAPIDAPI_KEY == "test-rapidapi-key"
    assert cfg.RAPIDAPI_HOST == "free-api-live-football-data.p.rapidapi.com"
    assert cfg.LOG_LEVEL == "INFO"
    assert cfg.API_PORT == 8000


def test_api_port_coerced_to_int(full_env, monkeypatch):
    monkeypatch.setenv("API_PORT", "9000")
    cfg = Config()
    assert cfg.API_PORT == 9000
    assert isinstance(cfg.API_PORT, int)


# ---------------------------------------------------------------------------
# Optional var defaults
# ---------------------------------------------------------------------------


def test_log_level_defaults_to_info(full_env, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    cfg = Config()
    assert cfg.LOG_LEVEL == "INFO"


def test_api_port_defaults_to_8000(full_env, monkeypatch):
    monkeypatch.delenv("API_PORT", raising=False)
    cfg = Config()
    assert cfg.API_PORT == 8000


# ---------------------------------------------------------------------------
# Missing required vars
# ---------------------------------------------------------------------------


def test_missing_single_required_var_raises(full_env, monkeypatch):
    monkeypatch.delenv("FIVETRAN_API_KEY")
    with pytest.raises(EnvironmentError, match="FIVETRAN_API_KEY"):
        Config()


def test_missing_multiple_required_vars_all_reported(full_env, monkeypatch):
    monkeypatch.delenv("FIVETRAN_API_KEY")
    monkeypatch.delenv("FIVETRAN_API_SECRET")
    with pytest.raises(EnvironmentError) as exc_info:
        Config()
    msg = str(exc_info.value)
    assert "FIVETRAN_API_KEY" in msg
    assert "FIVETRAN_API_SECRET" in msg


def test_empty_string_var_treated_as_missing(full_env, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "")
    with pytest.raises(EnvironmentError, match="RAPIDAPI_KEY"):
        Config()


# ---------------------------------------------------------------------------
# table() method
# ---------------------------------------------------------------------------


def test_table_returns_full_bq_id(full_env):
    cfg = Config()
    assert cfg.table("gold_players") == "test-project.test_dataset.gold_players"


def test_table_works_for_all_layers(full_env):
    cfg = Config()
    assert cfg.table("bronze_raw") == "test-project.test_dataset.bronze_raw"
    assert cfg.table("silver_players") == "test-project.test_dataset.silver_players"
    assert cfg.table("gold_match_stats") == "test-project.test_dataset.gold_match_stats"
