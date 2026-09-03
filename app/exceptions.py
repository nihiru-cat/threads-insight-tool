"""Custom exceptions for the Threads API client and search pipeline.

All are subclasses of ThreadsToolError so callers (e.g. the Streamlit UI) can
catch one broad type without crashing the app, while still branching on the
specific cause when useful.
"""


class ThreadsToolError(Exception):
    """Base class for all application-raised errors."""


class ThreadsAPIError(ThreadsToolError):
    """Base class for errors returned by / while calling the Threads API."""


class ThreadsAuthError(ThreadsAPIError):
    """401/403 — invalid or expired access token, or missing permission."""


class ThreadsRateLimitError(ThreadsAPIError):
    """429 — rate limited by the Threads API."""


class ThreadsServerError(ThreadsAPIError):
    """5xx — transient server-side error."""


class ThreadsBadRequestError(ThreadsAPIError):
    """4xx (other than 401/403/429) — request itself was invalid."""


class ThreadsTimeoutError(ThreadsAPIError):
    """The HTTP request timed out."""


class ThreadsInvalidResponseError(ThreadsAPIError):
    """Response body was not valid JSON, or did not match the expected shape."""


class PostSaveError(ThreadsToolError):
    """A post could not be persisted to the database."""


class AIError(ThreadsToolError):
    """Base class for errors from the AI analysis provider (OpenAI/Anthropic)."""


class AIAuthError(AIError):
    """Invalid/missing API key, or account lacks access to the requested model."""


class AIRateLimitError(AIError):
    """429 — rate limited by the AI provider."""


class AIServerError(AIError):
    """5xx — transient server-side error from the AI provider."""


class AITimeoutError(AIError):
    """The request to the AI provider timed out."""


class AIInvalidResponseError(AIError):
    """The AI response was not valid JSON, or didn't match the analysis schema."""


class SimilarityBackendError(ThreadsToolError):
    """The configured similarity backend is misconfigured (e.g. forced to
    "openai_embedding" without an OPENAI_API_KEY)."""
