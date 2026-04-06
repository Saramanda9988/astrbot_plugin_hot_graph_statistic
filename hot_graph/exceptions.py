class HotGraphError(Exception):
    """Base exception for the plugin core."""


class UserNotRegisteredError(HotGraphError):
    """Raised when a command requires a registered user."""


class HistorySourceUnavailableError(HotGraphError):
    """Raised when no usable history source is configured."""
