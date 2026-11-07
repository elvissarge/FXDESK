"""Project-wide exception types."""


class FxDeskError(Exception):
    """Base error for fxdesk."""


class ConfigError(FxDeskError):
    """Invalid or missing configuration."""


class DataError(FxDeskError):
    """Raised when market data cannot be loaded."""


class ProviderError(DataError):
    """A specific data provider failed."""


class BrokerError(FxDeskError):
    """A broker operation failed."""


class RiskError(FxDeskError):
    """A trade violates the configured risk limits."""
