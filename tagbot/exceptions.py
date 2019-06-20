class NotInstalled(Exception):
    """Indicates that the GitHub App is not installed."""

    pass


class NotInstalledForOwner(NotInstalled):
    """Indicates that the GitHub App is not installed by the owner."""

    pass


class NotInstalledForRepo(NotInstalled):
    """Indicates that the GitHub App is not installed for a repository."""

    pass


class StopPipeline(Exception):
    """Indicates that the pipeline should halt."""

    pass


class UnknownType(StopPipeline):
    """Indicates a message from GitHub of unknown type."""

    pass


class InvalidPayload(StopPipeline):
    """Indicates an invalid GitHub payload."""

    pass
