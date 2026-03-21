"""
Tests for Cod8Agent — covers retry logic, exponential backoff, timeout
handling, response validation, and typed error raising.

All tests use a mock client so no real network calls are made.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.cod8_agent import (
    Cod8Agent,
    Cod8AgentError,
    REQUIRED_RESPONSE_KEYS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE: dict[str, Any] = {
    "id": "msg_abc123",
    "content": [{"type": "text", "text": "Hello!"}],
    "model": "claude-3-5-sonnet-20241022",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


def _make_agent(
    mock_client: Any,
    *,
    max_retries: int = 2,
    backoff_factor: float = 0.0,  # zero sleep for fast tests
    timeout: float = 5.0,
) -> Cod8Agent:
    return Cod8Agent(
        client=mock_client,
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_returns_valid_response() -> None:
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(return_value=dict(_VALID_RESPONSE))
    agent = _make_agent(mock_client)

    result = await agent.invoke("Hello, Claude!")

    assert result == _VALID_RESPONSE
    mock_client.create_message.assert_called_once()


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_on_transient_connection_error() -> None:
    """Agent should retry on ConnectionError and succeed on the last attempt."""
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(
        side_effect=[
            ConnectionError("network blip"),
            ConnectionError("network blip again"),
            dict(_VALID_RESPONSE),
        ]
    )
    agent = _make_agent(mock_client, max_retries=2)

    result = await agent.invoke("retry me")

    assert result["id"] == "msg_abc123"
    assert mock_client.create_message.call_count == 3


@pytest.mark.asyncio
async def test_raises_after_exhausting_retries() -> None:
    """After max_retries + 1 failed attempts a Cod8AgentError must be raised."""
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(
        side_effect=ConnectionError("always fails")
    )
    agent = _make_agent(mock_client, max_retries=2)

    with pytest.raises(Cod8AgentError, match="3 attempt"):
        await agent.invoke("will fail")

    assert mock_client.create_message.call_count == 3


@pytest.mark.asyncio
async def test_retries_on_timeout_error() -> None:
    """asyncio.TimeoutError must be treated as transient."""
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(
        side_effect=[
            asyncio.TimeoutError(),
            dict(_VALID_RESPONSE),
        ]
    )
    agent = _make_agent(mock_client, max_retries=2)

    result = await agent.invoke("timeout then ok")

    assert result["stop_reason"] == "end_turn"
    assert mock_client.create_message.call_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_unexpected_exception() -> None:
    """Non-transient exceptions (e.g. ValueError) must NOT be retried."""
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(
        side_effect=ValueError("unexpected")
    )
    agent = _make_agent(mock_client, max_retries=3)

    with pytest.raises(Cod8AgentError, match="Unexpected error"):
        await agent.invoke("fail fast")

    # Only one attempt — no retries
    assert mock_client.create_message.call_count == 1


@pytest.mark.asyncio
async def test_exponential_backoff_sleep_durations() -> None:
    """Verify asyncio.sleep is called with the correct backoff values."""
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(
        side_effect=[
            ConnectionError("fail 1"),
            ConnectionError("fail 2"),
            dict(_VALID_RESPONSE),
        ]
    )
    agent = Cod8Agent(
        client=mock_client,
        max_retries=2,
        backoff_factor=3.0,
        timeout=5.0,
    )

    sleep_calls: list[float] = []

    async def mock_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with patch("app.agents.cod8_agent.asyncio.sleep", side_effect=mock_sleep):
        await agent.invoke("backoff test")

    # attempt 0 -> sleep 3.0**0 = 1.0
    # attempt 1 -> sleep 3.0**1 = 3.0
    assert sleep_calls == [1.0, 3.0]


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_on_non_dict_response() -> None:
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(return_value="not a dict")
    agent = _make_agent(mock_client)

    with pytest.raises(Cod8AgentError, match="must be a dict"):
        await agent.invoke("bad response")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_key", list(REQUIRED_RESPONSE_KEYS))
async def test_raises_on_missing_required_key(missing_key: str) -> None:
    incomplete = {k: v for k, v in _VALID_RESPONSE.items() if k != missing_key}
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(return_value=incomplete)
    agent = _make_agent(mock_client)

    with pytest.raises(Cod8AgentError, match="missing required key"):
        await agent.invoke("missing key test")


@pytest.mark.asyncio
async def test_raises_on_truncated_response() -> None:
    truncated = {**_VALID_RESPONSE, "stop_reason": "max_tokens"}
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(return_value=truncated)
    agent = _make_agent(mock_client)

    with pytest.raises(Cod8AgentError, match="truncated or incomplete"):
        await agent.invoke("truncated")


@pytest.mark.asyncio
async def test_raises_on_empty_content() -> None:
    empty_content = {**_VALID_RESPONSE, "content": []}
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(return_value=empty_content)
    agent = _make_agent(mock_client)

    with pytest.raises(Cod8AgentError, match="'content' field is empty"):
        await agent.invoke("empty content")


@pytest.mark.asyncio
async def test_validation_error_is_not_retried() -> None:
    """Cod8AgentError from validation should propagate without retrying."""
    truncated = {**_VALID_RESPONSE, "stop_reason": "stop_sequence"}
    mock_client = AsyncMock()
    mock_client.create_message = AsyncMock(return_value=truncated)
    agent = _make_agent(mock_client, max_retries=5)

    with pytest.raises(Cod8AgentError):
        await agent.invoke("no retry on validation")

    # Must only be called once — validation errors are not retried
    assert mock_client.create_message.call_count == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_prompt_raises_immediately() -> None:
    mock_client = AsyncMock()
    agent = _make_agent(mock_client)

    with pytest.raises(Cod8AgentError, match="non-empty"):
        await agent.invoke("   ")

    mock_client.create_message.assert_not_called()


@pytest.mark.asyncio
async def test_cod8_agent_error_preserves_cause() -> None:
    mock_client = AsyncMock()
    cause = ConnectionError("root cause")
    mock_client.create_message = AsyncMock(side_effect=cause)
    agent = _make_agent(mock_client, max_retries=0)

    with pytest.raises(Cod8AgentError) as exc_info:
        await agent.invoke("cause test")

    assert exc_info.value.cause is cause
