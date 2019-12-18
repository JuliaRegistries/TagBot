from . import repo


class Changelog:
    """A Changelog produces release notes for a single release."""

    def __init__(self, repo: "repo.Repo", template: str):
        self.__repo = repo
        self.__template = template

    def get(self, version: str) -> str:
        """Get the changelog for a specific version."""
        pass
