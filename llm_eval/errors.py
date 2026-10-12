class ProviderError(Exception):
    """Base class for provider failures."""


class TransientProviderError(ProviderError):
    """An error safe to retry (429, timeout, or temporary 5xx)."""


class PermanentProviderError(ProviderError):
    """An error that should fail a case immediately."""


class ProviderConfigurationError(PermanentProviderError):
    """The adapter is missing safe-to-configure runtime settings."""
