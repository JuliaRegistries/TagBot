from typing import Callable

from .context import Context
from . import handlers


def __default(f: Callable) -> Callable:
    """Create a function that returns a "default" value."""
    from github.GitRelease import GitRelease
    from github.IssueComment import IssueComment

    result = {
        None: None,
        IssueComment: IssueComment(None, None, [], None),
        GitRelease: GitRelease(None, None, [], None),
    }[f.__annotations__["return"]]
    return lambda *args, **kwargs: result


def _local():
    """Call this function when running locally to disable side effects."""
    from .mixins import AWS, Git, GitHubAPI

    AWS.invoke = __default(AWS.invoke)
    AWS.put_item = __default(AWS.put_item)
    Git._git_push_tags = __default(Git._git_push_tags)
    GitHubAPI.create_comment = __default(GitHubAPI.create_comment)
    GitHubAPI.create_release = __default(GitHubAPI.create_release)
    GitHubAPI.append_comment = __default(GitHubAPI.append_comment)
