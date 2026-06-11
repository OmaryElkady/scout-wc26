# Per-package fixtures. pytest auto-discovers conftest.py in each directory.

import pytest


@pytest.fixture(autouse=True)
def _restore_active_league_state():
    """Save and restore the active-league module globals around every test.

    `src.api.main._active_league` and `src.utils.football_api._WORLD_CUP_LEAGUE_ID`
    are both mutable singletons. Production code paths (e.g. POST /admin/switch-league
    fast path) mutate them synchronously, and prior tests would leak that state
    into later tests — most visibly making `test_football_api` see league_id=47
    when the test imports the constant as 10195.

    This fixture is autouse and runs around every unit test. It captures the
    values at setup, yields, then restores them at teardown.
    """
    import src.api.main as _main
    import src.utils.football_api as _fa_mod

    _orig_active = dict(_main._active_league)
    _orig_lid = _fa_mod._WORLD_CUP_LEAGUE_ID
    try:
        yield
    finally:
        _main._active_league.clear()
        _main._active_league.update(_orig_active)
        _fa_mod._WORLD_CUP_LEAGUE_ID = _orig_lid
