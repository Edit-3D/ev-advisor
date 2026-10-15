class AgentConfigurationError(RuntimeError):
    """Raised when required agent configuration is unavailable."""


class AgentExecutionError(RuntimeError):
    """Raised when the agent workflow cannot complete safely."""


class WorkflowCancelledError(RuntimeError):
    """Raised when a disconnected client asks the workflow to stop cooperatively."""


class WorkflowDeadlineExceeded(TimeoutError):
    """Raised before work that cannot finish inside the request time budget."""
