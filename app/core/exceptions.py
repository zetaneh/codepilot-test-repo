"""Custom exception classes for the Todo API."""


class AppException(Exception):
    """Base exception class for application-level errors."""

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(self.message)


class RateLimitExceededException(AppException):
    """Raised when a client exceeds the allowed request rate.

    Attributes:
        retry_after: Number of seconds the client should wait before retrying.
    """

    def __init__(self, retry_after: int, message: str = "Rate limit exceeded") -> None:
        self.retry_after = retry_after
        super().__init__(message)
