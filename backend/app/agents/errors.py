class AgentConfigurationError(RuntimeError):
    """Raised when required agent configuration is unavailable."""


class AgentExecutionError(RuntimeError):
    """Raised when the agent workflow cannot complete safely."""
