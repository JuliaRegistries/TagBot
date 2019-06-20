class NotInstalled(Exception):
    """Indicates that the GitHub App is not installed."""

    pass


class NotInstalledForOrg(NotInstalled):
    """Indicates that the GitHub App is not installed for an organization."""

    pass


class NotInstalledForRepo(NotInstalled):
    """Indicates that the GitHub App is not installed for a repository."""

    pass


class UnknownType(Exception):
    """Indicates a message from GitHub of unknown type."""

    pass


class InvalidPayload(Exception):
    """Indicates an invalid GitHub payload."""

    pass
