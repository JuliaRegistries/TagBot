from typing import Callable

from github.GitRelease import GitRelease
from github.IssueComment import IssueComment

from .context import Context
from . import handlers


def __zero(f: Callable) -> Callable:
    result = {
        None: None,
        IssueComment: IssueComment(None, None, [], None),
        GitRelease: GitRelease(None, None, [], None),
    }[f.__annotations__["return"]]
    return lambda *args, **kwargs: result


def _local():
    """Call this function when running locally to disable side effects."""
    from .mixins import AWS, Git, GitHubAPI

    AWS.invoke = __zero(AWS.invoke)
    AWS.put_item = __zero(AWS.put_item)
    Git._git_push_tags = __zero(Git._git_push_tags)
    GitHubAPI.create_comment = __zero(GitHubAPI.create_comment)
    GitHubAPI.create_release = __zero(GitHubAPI.create_release)
    GitHubAPI.append_comment = __zero(GitHubAPI.append_comment)
