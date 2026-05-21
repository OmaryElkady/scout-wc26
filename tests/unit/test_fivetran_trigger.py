from unittest.mock import MagicMock, call, patch

import pytest

from src.ingestion.fivetran_trigger import poll_sync_status, trigger_sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = body
    resp.text = str(body)
    return resp


def _state_response(sync_state: str) -> MagicMock:
    return _ok_response({"data": {"status": {"sync_state": sync_state}}})


def _error_response(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = "error"
    return resp


# ---------------------------------------------------------------------------
# trigger_sync
# ---------------------------------------------------------------------------


def test_trigger_sync_posts_to_correct_url():
    trigger_resp = MagicMock(status_code=200)
    trigger_resp.json.return_value = {"message": "Sync has been triggered"}
    with patch("src.ingestion.fivetran_trigger.requests.post", return_value=trigger_resp) as mock_post:
        trigger_sync()

    url = mock_post.call_args[0][0]
    assert "/v1/connectors/" in url
    assert "/sync" in url


def test_trigger_sync_uses_basic_auth():
    trigger_resp = MagicMock(status_code=200)
    trigger_resp.json.return_value = {}
    with patch("src.ingestion.fivetran_trigger.requests.post", return_value=trigger_resp) as mock_post:
        trigger_sync()

    kwargs = mock_post.call_args[1]
    assert "auth" in kwargs
    api_key, api_secret = kwargs["auth"]
    assert api_key  # non-empty
    assert api_secret  # non-empty


def test_trigger_sync_accepts_201():
    trigger_resp = MagicMock(status_code=201)
    trigger_resp.json.return_value = {}
    with patch("src.ingestion.fivetran_trigger.requests.post", return_value=trigger_resp):
        trigger_sync()  # should not raise


def test_trigger_sync_raises_on_4xx():
    with patch("src.ingestion.fivetran_trigger.requests.post", return_value=_error_response(403)):
        with pytest.raises(RuntimeError, match="HTTP 403"):
            trigger_sync()


def test_trigger_sync_raises_on_5xx():
    with patch("src.ingestion.fivetran_trigger.requests.post", return_value=_error_response(500)):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            trigger_sync()


# ---------------------------------------------------------------------------
# poll_sync_status — terminal success states
# ---------------------------------------------------------------------------


def test_poll_returns_on_scheduled():
    with patch("src.ingestion.fivetran_trigger.requests.get", return_value=_state_response("scheduled")), \
         patch("src.ingestion.fivetran_trigger.time.sleep"):
        poll_sync_status(timeout_seconds=60)  # should not raise


def test_poll_returns_on_rescheduled():
    with patch("src.ingestion.fivetran_trigger.requests.get", return_value=_state_response("rescheduled")), \
         patch("src.ingestion.fivetran_trigger.time.sleep"):
        poll_sync_status(timeout_seconds=60)  # should not raise


# ---------------------------------------------------------------------------
# poll_sync_status — terminal failure states
# ---------------------------------------------------------------------------


def test_poll_raises_on_broken():
    with patch("src.ingestion.fivetran_trigger.requests.get", return_value=_state_response("broken")), \
         patch("src.ingestion.fivetran_trigger.time.sleep"):
        with pytest.raises(RuntimeError, match="broken"):
            poll_sync_status(timeout_seconds=60)


def test_poll_raises_on_paused():
    with patch("src.ingestion.fivetran_trigger.requests.get", return_value=_state_response("paused")), \
         patch("src.ingestion.fivetran_trigger.time.sleep"):
        with pytest.raises(RuntimeError, match="paused"):
            poll_sync_status(timeout_seconds=60)


# ---------------------------------------------------------------------------
# poll_sync_status — timeout
# ---------------------------------------------------------------------------


def test_poll_raises_timeout_when_always_syncing():
    with patch("src.ingestion.fivetran_trigger.requests.get", return_value=_state_response("syncing")), \
         patch("src.ingestion.fivetran_trigger.time.sleep"):
        with pytest.raises(TimeoutError):
            poll_sync_status(timeout_seconds=-1)  # deadline already past


# ---------------------------------------------------------------------------
# poll_sync_status — polling behaviour
# ---------------------------------------------------------------------------


def test_poll_keeps_looping_while_syncing_then_succeeds():
    responses = [
        _state_response("syncing"),
        _state_response("syncing"),
        _state_response("scheduled"),
    ]
    with patch("src.ingestion.fivetran_trigger.requests.get", side_effect=responses) as mock_get, \
         patch("src.ingestion.fivetran_trigger.time.sleep") as mock_sleep:
        poll_sync_status(timeout_seconds=300)

    assert mock_get.call_count == 3
    assert mock_sleep.call_count == 2  # slept after each "syncing" response


def test_poll_raises_on_http_error_during_polling():
    with patch("src.ingestion.fivetran_trigger.requests.get", return_value=_error_response(502)), \
         patch("src.ingestion.fivetran_trigger.time.sleep"):
        with pytest.raises(RuntimeError, match="HTTP 502"):
            poll_sync_status(timeout_seconds=60)


def test_poll_uses_basic_auth_on_status_check():
    with patch("src.ingestion.fivetran_trigger.requests.get", return_value=_state_response("scheduled")) as mock_get, \
         patch("src.ingestion.fivetran_trigger.time.sleep"):
        poll_sync_status(timeout_seconds=60)

    kwargs = mock_get.call_args[1]
    assert "auth" in kwargs
    api_key, api_secret = kwargs["auth"]
    assert api_key
    assert api_secret
