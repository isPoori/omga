"""
OMGA error hierarchy.

Every error raised by OMGA is an `OmgaError` (or subclass) carrying a
`hint` — a short, human-addressed remedy that the CLI can print without
dumping a stack trace. Raw `Exception`s are never allowed to reach the
top-level CLI handler unexamined.
"""

from __future__ import annotations


class OmgaError(Exception):
    """Base class for all OMGA-specific errors."""

    def __init__(self, message: str, *, hint: str = "", debug: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.debug = debug

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ConfigError(OmgaError):
    """Configuration is missing or invalid."""


class WizardInterrupted(OmgaError):
    """The user cancelled an interactive wizard (Ctrl+C)."""


class ProviderError(OmgaError):
    """A provider failed to perform a request."""


class ProviderAuthError(ProviderError):
    """The provider rejected the provided credentials."""


class NetworkError(ProviderError):
    """Connection, timeout or TLS-level failure talking to a provider."""


class ProviderBlockedError(NetworkError):
    """Geo / WAF / security-policy block (often HTTP 403 from Cloudflare)."""


class ModelNotFoundError(ProviderError):
    """The selected / requested model is not available on the provider."""


class NoApiKeyError(ConfigError):
    """A provider requires an API key but none is configured."""


class ToolError(OmgaError):
    """A tool failed while the agent was executing it."""


class ToolDeniedError(ToolError):
    """A tool action was denied (safety boundary or user rejection)."""


class CommandError(OmgaError):
    """The agent's shell command failed (non-zero exit)."""


class SafetyError(OmgaError):
    """A shell command was blocked by the safety layer."""


def hint_for(exc: BaseException) -> str:
    """Return a human hint for any exception, falling back to a generic one."""
    if isinstance(exc, OmgaError):
        return exc.hint or exc.message
    return "An unexpected error occurred. Run with OMGA_DEBUG=1 for details."
