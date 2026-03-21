"""
Cod8Agent — async Claude API wrapper with retry logic, configurable timeout,
and response shape validation.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers (read from env; fall back to sensible defaults)
# ---------------------------------------------------------------------------

def _get_int_env(key: str, default: int) -> int:
    """Return an integer environment variable or a default value."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r; using default %d", key, raw, default)
        return default


def _get_float_env(key: str, default: float) -> float:
    """Return a float environment variable or a default value."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r; using default %f", key, raw, default)
        return default


COD8_CLAUDE_TIMEOUT: float = _get_float_env("COD8_CLAUDE_TIMEOUT", 30.0)
COD8_CLAUDE_MAX_RETRIES: int = _get_int_env("COD8_CLAUDE_MAX_RETRIES", 3)
COD8_CLAUDE_BACKOFF_FACTOR: float = _get_float_env("COD8_CLAUDE_BACKOFF_FACTOR", 2.0)
COD8_CLAUDE_MODEL: str = os.environ.get("COD8_CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
COD8_CLAUDE_MAX_TOKENS: int = _get_int_env("COD8_CLAUDE_MAX_TOKENS", 1024)

# Keys that every valid Claude response payload must contain.
REQUIRED_RESPONSE_KEYS: tuple[str, ...] = ("id", "content", "model", "stop_reason")

# Errors that are considered transient and safe to retry.
_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
)

# ---------------------------------------------------------------------------
# Typed error
# ---------------------------------------------------------------------------


class Cod8AgentError(Exception):
    """Raised when the Claude agent encounters an unrecoverable problem."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)!r})"


# ---------------------------------------------------------------------------
# Protocol for the underlying Claude client — enables easy mocking in tests
# ---------------------------------------------------------------------------


@runtime_checkable
class ClaudeClientProtocol(Protocol):
    """Minimal async interface expected from the Claude API client."""

    async def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, str]],
        timeout: float,
    ) -> dict[str, Any]:
        """Send a message to the Claude API and return the raw response dict."""
        ...


# ---------------------------------------------------------------------------
# Default client — wraps the real Anthropic SDK if available
# ---------------------------------------------------------------------------


class _DefaultClaudeClient:
    """
    Thin async adapter around the *synchronous* anthropic SDK.

    The SDK call is run in a thread-pool executor so it does not block the
    event loop.  If the ``anthropic`` package is not installed the client
    will raise ``ImportError`` at instantiation time.
    """

    def __init__(self) -> None:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "The 'anthropic' package is required to use Cod8Agent with the "
                "default client.  Install it with: pip install anthropic"
            ) from exc
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        self._anthropic = anthropic

    async def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, str]],
        timeout: float,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()

        def _call() -> Any:
            return self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                timeout=timeout,
            )

        raw = await loop.run_in_executor(None, _call)
        # Convert SDK response object to a plain dict so the agent can
        # work with it uniformly.
        if hasattr(raw, "model_dump"):
            return raw.model_dump()
        if hasattr(raw, "__dict__"):
            return vars(raw)
        return dict(raw)  # type: ignore[call-overload]


# ---------------------------------------------------------------------------
# Cod8Agent
# ---------------------------------------------------------------------------


class Cod8Agent:
    """
    Async Claude agent with retry logic, timeout, and response validation.

    Parameters
    ----------
    client:
        An object that satisfies ``ClaudeClientProtocol``.  Defaults to
        ``_DefaultClaudeClient`` (real Anthropic SDK).  Pass a mock here
        to unit-test without network access.
    model:
        Claude model identifier.  Defaults to ``COD8_CLAUDE_MODEL``.
    max_tokens:
        Maximum tokens in the completion.  Defaults to ``COD8_CLAUDE_MAX_TOKENS``.
    timeout:
        Per-attempt timeout in seconds.  Defaults to ``COD8_CLAUDE_TIMEOUT``.
    max_retries:
        Maximum number of retry attempts on transient errors.  Defaults to
        ``COD8_CLAUDE_MAX_RETRIES``.
    backoff_factor:
        Multiplicative backoff factor.  Wait = backoff_factor ** attempt seconds.
        Defaults to ``COD8_CLAUDE_BACKOFF_FACTOR``.
    """

    def __init__(
        self,
        *,
        client: ClaudeClientProtocol | None = None,
        model: str = COD8_CLAUDE_MODEL,
        max_tokens: int = COD8_CLAUDE_MAX_TOKENS,
        timeout: float = COD8_CLAUDE_TIMEOUT,
        max_retries: int = COD8_CLAUDE_MAX_RETRIES,
        backoff_factor: float = COD8_CLAUDE_BACKOFF_FACTOR,
    ) -> None:
        self._client: ClaudeClientProtocol = client or _DefaultClaudeClient()
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def invoke(self, prompt: str) -> dict[str, Any]:
        """
        Invoke the Claude API with *prompt* and return a validated response dict.

        Retries up to ``max_retries`` times on transient errors using
        exponential backoff.  Raises ``Cod8AgentError`` on:

        * Malformed or missing required response keys.
        * A truncated response (``stop_reason`` is not ``"end_turn"``).
        * Exhausted retries after transient failures.

        Parameters
        ----------
        prompt:
            The user-facing text to send to Claude.

        Returns
        -------
        dict
            The validated response payload from Claude.
        """
        if not prompt or not prompt.strip():
            raise Cod8AgentError("Prompt must be a non-empty string.")

        last_exc: BaseException | None = None

        for attempt in range(self._max_retries + 1):
            try:
                logger.debug(
                    "Cod8Agent.invoke attempt %d/%d model=%s",
                    attempt + 1,
                    self._max_retries + 1,
                    self._model,
                )
                response = await asyncio.wait_for(
                    self._client.create_message(
                        model=self._model,
                        max_tokens=self._max_tokens,
                        messages=[{"role": "user", "content": prompt}],
                        timeout=self._timeout,
                    ),
                    timeout=self._timeout,
                )
                self._validate_response(response)
                logger.debug("Cod8Agent.invoke succeeded on attempt %d", attempt + 1)
                return response

            except Cod8AgentError:
                # Validation errors are not retried — re-raise immediately.
                raise

            except asyncio.TimeoutError as exc:
                last_exc = exc
                logger.warning(
                    "Cod8Agent.invoke timed out on attempt %d/%d",
                    attempt + 1,
                    self._max_retries + 1,
                )

            except _TRANSIENT_EXCEPTIONS as exc:  # type: ignore[misc]
                last_exc = exc
                logger.warning(
                    "Cod8Agent.invoke transient error on attempt %d/%d: %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )

            except Exception as exc:
                # Non-transient / unexpected error — fail fast.
                raise Cod8AgentError(
                    f"Unexpected error calling Claude API: {exc}"
                ) from exc

            # Backoff before next attempt (skip sleep after last attempt).
            if attempt < self._max_retries:
                sleep_seconds = self._backoff_factor ** attempt
                logger.debug(
                    "Cod8Agent.invoke backing off %.2fs before attempt %d",
                    sleep_seconds,
                    attempt + 2,
                )
                await asyncio.sleep(sleep_seconds)

        raise Cod8AgentError(
            f"Claude API call failed after {self._max_retries + 1} attempt(s).",
            cause=last_exc,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_response(self, response: Any) -> None:
        """
        Assert that *response* is a dict with all required keys and a valid
        ``stop_reason``.

        Raises
        ------
        Cod8AgentError
            If the response is malformed or indicates a truncated completion.
        """
        if not isinstance(response, dict):
            raise Cod8AgentError(
                f"Claude response must be a dict, got {type(response).__name__!r}."
            )

        missing = [k for k in REQUIRED_RESPONSE_KEYS if k not in response]
        if missing:
            raise Cod8AgentError(
                f"Claude response is missing required key(s): {missing!r}.  "
                f"Received keys: {list(response.keys())!r}"
            )

        stop_reason = response.get("stop_reason")
        if stop_reason != "end_turn":
            raise Cod8AgentError(
                f"Claude response was truncated or incomplete: "
                f"stop_reason={stop_reason!r} (expected 'end_turn').  "
                f"Response id={response.get('id')!r}"
            )

        content = response.get("content")
        if not content:
            raise Cod8AgentError(
                "Claude response 'content' field is empty or falsy.  "
                f"Response id={response.get('id')!r}"
            )
