"""Wrapper for GitLab to provide a small subset of PyGithub-like
functionality used by this project.

This module intentionally implements only the pieces of API that `Repo`
currently expects (get_repo, repo.default_branch, get_pulls, get_contents,
get_git_blob, create_pull). The wrapper delegates to `python-gitlab` when
available and raises informative errors otherwise.
"""

from typing import Any, Dict, Iterable, List, Optional

import importlib
import logging
import os
from base64 import b64decode, b64encode

gitlab: Any = None
try:
    gitlab = importlib.import_module("gitlab")
except Exception:  # pragma: no cover - optional runtime dependency
    gitlab = None


class UnknownObjectException(Exception):
    pass


class GitlabException(Exception):
    pass


class _HeadRef:
    """Wrapper for PR head reference."""

    def __init__(self, ref: str) -> None:
        self.ref = ref


class _Owner:
    """Wrapper for repository owner."""

    def __init__(self, login: str) -> None:
        self.login = login


class _Label:
    """Wrapper for issue/PR label."""

    def __init__(self, name: str) -> None:
        self.name = name


class _User:
    """Wrapper for user."""

    def __init__(self, login: str) -> None:
        self.login = login


class _AuthorDate:
    """Wrapper for commit author with date."""

    def __init__(self, date: Any) -> None:
        self.date = date


class _CommitTree:
    """Wrapper for commit tree."""

    def __init__(self, sha: Optional[str]) -> None:
        self.sha = sha


class _CommitInner:
    """Wrapper for inner commit object with tree."""

    def __init__(self, tree: _CommitTree) -> None:
        self.tree = tree


class _CommitAuthorWrapper:
    """Wrapper for commit with author."""

    def __init__(self, author: _AuthorDate) -> None:
        self.author = author


class _BranchCommit:
    """Wrapper for branch commit."""

    def __init__(self, sha: Optional[str]) -> None:
        self.sha = sha


class _RefObject:
    """Wrapper for git ref object."""

    def __init__(self, type_: str, sha: Optional[str]) -> None:
        self.type = type_
        self.sha = sha


class _GitRef:
    """Wrapper for git reference."""

    def __init__(self, obj: _RefObject) -> None:
        self.object = obj


class _TagObject:
    """Wrapper for tag object."""

    def __init__(self, sha: Optional[str]) -> None:
        self.sha = sha


class _GitTag:
    """Wrapper for git tag."""

    def __init__(self, obj: _TagObject) -> None:
        self.object = obj


class _Branch:
    """Wrapper for branch."""

    def __init__(self, commit: _BranchCommit) -> None:
        self.commit = commit


class _Blob:
    """Wrapper for git blob."""

    def __init__(self, content: str) -> None:
        self.content = content


class _ReleaseWrapper:
    """Wrapper for GitLab release."""

    def __init__(self, r: Any) -> None:
        self.tag_name = getattr(r, "tag_name", getattr(r, "name", ""))
        self.created_at = getattr(r, "created_at", None)
        self.html_url = getattr(r, "url", None) or getattr(r, "assets_url", None)


class _IssueLike:
    """Wrapper to make GitLab issue look like GitHub issue."""

    def __init__(self, i: Any) -> None:
        self.closed_at = getattr(i, "closed_at", None)
        self.labels = [_Label(label) for label in getattr(i, "labels", [])]
        self.pull_request = False
        self.user = _User(getattr(i, "author", {}).get("username", ""))
        self.body = getattr(i, "description", "")
        self.number = getattr(i, "iid", None)
        self.title = getattr(i, "title", "")
        self.html_url = getattr(i, "web_url", "")


class _PRFromMR:
    """Wrapper for merge request as pull request."""

    def __init__(self, mr: Any) -> None:
        self.merged = True
        self.merged_at = getattr(mr, "merged_at", None)
        self.user = _User(getattr(mr, "author", {}).get("username", ""))
        self.body = getattr(mr, "description", "")
        self.number = getattr(mr, "iid", None)
        self.title = getattr(mr, "title", "")
        self.html_url = getattr(mr, "web_url", "")
        self.labels = [_Label(label) for label in getattr(mr, "labels", [])]


class _IssueAsPR:
    """Wrapper to make GitLab MR look like GitHub issue with PR."""

    def __init__(self, m: Any) -> None:
        self.pull_request = True
        self._mr = m
        self.labels = [_Label(label) for label in getattr(m, "labels", [])]

    def as_pull_request(self) -> _PRFromMR:
        return _PRFromMR(self._mr)


class _CommitWrapper:
    """Wrapper for GitLab commit."""

    def __init__(self, c: Any) -> None:
        d = (
            getattr(c, "committed_date", None)
            or getattr(c, "created_at", None)
            or getattr(c, "committer_date", None)
        )
        self.commit = _CommitAuthorWrapper(_AuthorDate(d))
        self.sha = getattr(c, "id", getattr(c, "sha", None))


class _CommitWithTree:
    """Wrapper for commit with tree SHA."""

    def __init__(self, c: Any) -> None:
        self.sha = getattr(c, "id", getattr(c, "sha", None))
        tree_sha = getattr(c, "tree_id", None)
        self.commit = _CommitInner(_CommitTree(tree_sha))


class _BranchWrapper:
    """Wrapper for GitLab branch."""

    def __init__(self, b: Any) -> None:
        self.name = getattr(b, "name", "")
        commit_sha = getattr(b, "commit", {}).get("id", None)
        self.commit = _BranchCommit(commit_sha)


class _PR:
    def __init__(self, mr: Any):
        # mr is a python-gitlab MergeRequest object
        self._mr = mr

    @property
    def merged_at(self) -> Any:
        return getattr(self._mr, "merged_at", None)

    @property
    def closed_at(self) -> Any:
        return getattr(self._mr, "closed_at", None)

    @property
    def merged(self) -> bool:
        return getattr(self._mr, "merged_at", None) is not None

    @property
    def head(self) -> _HeadRef:
        return _HeadRef(getattr(self._mr, "source_branch", ""))


class _Contents:
    def __init__(self, sha: str, content_b64: str):
        self.sha = sha
        self._b64 = content_b64

    @property
    def decoded_content(self) -> bytes:
        return b64decode(self._b64)


class ProjectWrapper:
    def __init__(self, project: Any):
        self._project = project
        self._file_cache: Dict[str, str] = {}

    @property
    def default_branch(self) -> str:
        return str(self._project.attributes.get("default_branch") or "")

    @property
    def owner(self) -> _Owner:
        ns = self._project.attributes.get("namespace") or {}
        name = ns.get("path") or ns.get("name") or ""
        return _Owner(name)

    @property
    def full_name(self) -> str:
        # map to GitLab's path_with_namespace
        return getattr(self._project, "path_with_namespace", "")

    @property
    def private(self) -> bool:
        visibility = getattr(self._project, "visibility", "")
        return visibility != "public"

    @property
    def ssh_url(self) -> str:
        return getattr(self._project, "ssh_url_to_repo", "")

    def get_pulls(
        self, head: Optional[str] = None, state: Optional[str] = None
    ) -> List[_PR]:
        # Map PyGithub-style get_pulls to GitLab merge requests
        params: Dict[str, Any] = {}
        if state is not None:
            # Map PyGithub states to GitLab states
            if state == "closed":
                params["state"] = "closed"
            elif state == "open":
                params["state"] = "opened"
            # For "all" or None, do not set state param
        if head:
            # head in PyGithub sometimes is "owner:branch".
            branch = head.split(":", 1)[-1]
            params["source_branch"] = branch
        mrs = self._project.mergerequests.list(all=True, **params)
        return [_PR(m) for m in mrs]

    @property
    def html_url(self) -> str:
        # Map to GitLab's web URL
        return getattr(self._project, "web_url", "")

    def get_releases(self) -> List[_ReleaseWrapper]:
        try:
            rels = self._project.releases.list(all=True)
        except Exception:
            return []
        return [_ReleaseWrapper(r) for r in rels]

    def get_issues(
        self, state: Optional[str] = None, since: Optional[Any] = None
    ) -> List[Any]:
        # Return issues and merged merge-requests as issue-like objects so
        # the rest of the code (which expects GitHub's issue/PR mixing)
        # can operate on them.
        issues: List[Any] = []
        try:
            params: Dict[str, Any] = {}
            if state:
                # Map GitHub states to GitLab states:
                # GitHub: "open", "closed", "all"
                # GitLab: "opened", "closed" (omit for all)
                if state == "open":
                    params["state"] = "opened"
                elif state == "closed":
                    params["state"] = "closed"
                # For "all" or other values, don't set state param
            if since:
                params["updated_after"] = since
            its = self._project.issues.list(all=True, **params)
        except Exception:
            its = []

        for i in its:
            issues.append(_IssueLike(i))

        # Also include merged merge requests as pull_request-like items
        try:
            mr_params: Dict[str, Any] = {"state": "merged"}
            if since:
                mr_params["updated_after"] = since
            mrs = self._project.mergerequests.list(all=True, **mr_params)
        except Exception:
            mrs = []

        for m in mrs:
            issues.append(_IssueAsPR(m))
        return issues

    def get_commit(self, sha: str) -> _CommitWrapper:
        try:
            c = self._project.commits.get(sha)
        except Exception as e:
            raise UnknownObjectException(str(e))
        return _CommitWrapper(c)

    def get_contents(self, path: str) -> _Contents:
        try:
            f = self._project.files.get(file_path=path, ref=self.default_branch)
        except Exception as e:
            raise UnknownObjectException(str(e))
        # python-gitlab returns base64 encoded content in attribute 'content'
        content_b64 = getattr(f, "content", None)
        if content_b64 is None:
            # Try to fetch raw content
            try:
                raw = self._project.files.raw(file_path=path, ref=self.default_branch)
                if isinstance(raw, bytes):
                    content_b64 = b64encode(raw).decode("ascii")
                else:
                    content_b64 = b64encode(raw.encode("utf8")).decode("ascii")
            except Exception:
                raise UnknownObjectException("Could not fetch file contents")
        fake_sha = f"gl-{path}-{self.default_branch}"
        self._file_cache[fake_sha] = content_b64
        return _Contents(fake_sha, content_b64)

    def get_git_blob(self, sha: str) -> _Blob:
        if sha not in self._file_cache:
            raise UnknownObjectException("Blob not found")
        return _Blob(self._file_cache[sha])

    def get_contents_list(self, path: str) -> List[_Contents]:
        # Helper not used but present for compatibility
        return [self.get_contents(path)]

    def get_commits(
        self,
        sha: Optional[str] = None,
        since: Optional[Any] = None,
        until: Optional[Any] = None,
    ) -> Iterable[_CommitWithTree]:
        try:
            params: Dict[str, Any] = {}
            if sha:
                params["ref_name"] = sha
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            commits = self._project.commits.list(all=True, **params)
        except Exception:
            commits = []

        for c in commits:
            yield _CommitWithTree(c)

    def get_branches(self) -> List[_BranchWrapper]:
        try:
            brs = self._project.branches.list(all=True)
        except Exception:
            brs = []
        return [_BranchWrapper(b) for b in brs]

    def get_git_ref(self, ref: str) -> _GitRef:
        if ref.startswith("tags/"):
            tag = ref.split("/", 1)[1]
            try:
                t = self._project.tags.get(tag)
                commit_info = getattr(t, "commit", {})
                sha = commit_info.get("id", None) or commit_info.get("sha", None)
            except Exception:
                raise UnknownObjectException("Ref not found")
            return _GitRef(_RefObject("tag", sha))
        # fallback: branch
        try:
            b = self._project.branches.get(ref)
            sha = getattr(b, "commit", {}).get("id", None)
        except Exception:
            raise UnknownObjectException("Ref not found")
        return _GitRef(_RefObject("commit", sha))

    def get_git_tag(self, sha: str) -> _GitTag:
        return _GitTag(_TagObject(sha))

    def get_branch(self, name: str) -> _Branch:
        try:
            b = self._project.branches.get(name)
        except Exception:
            raise UnknownObjectException("Branch not found")
        return _Branch(_BranchCommit(getattr(b, "commit", {}).get("id", None)))

    def create_pull(self, title: str, body: str, head: str, base: str) -> Any:
        # Create a merge request
        try:
            mr = self._project.mergerequests.create(
                {
                    "title": title,
                    "source_branch": head,
                    "target_branch": base,
                    "description": body,
                }
            )
            return mr
        except Exception as e:
            raise GitlabException(str(e))

    def create_git_release(
        self,
        tag: str,
        name: str,
        body: str,
        target_commitish: Optional[str] = None,
        draft: bool = False,
    ) -> Any:
        # Map GitHub create_git_release to GitLab release creation
        # Note: GitLab does not support "draft" releases the same way
        # GitHub does. To avoid silently publishing a release when the
        # caller expects a draft, explicitly error out if `draft=True`.
        if draft:
            raise GitlabException("Draft releases are not supported in GitLab")
        try:
            data = {"name": name, "tag_name": tag, "description": body}
            if target_commitish:
                data["ref"] = target_commitish
            rel = self._project.releases.create(data)
            return rel
        except Exception as e:
            raise GitlabException(str(e))

    def create_repository_dispatch(
        self, event_type: str, payload: Any = None
    ) -> None:
        # GitLab does not have an equivalent to GitHub's repository_dispatch.
        # Log a warning and no-op to avoid breaking the caller.
        logging.getLogger(__name__).warning(
            "create_repository_dispatch is not supported on GitLab; skipping"
        )


class GitlabClient:
    def __init__(self, token: str, base_url: str):
        if gitlab is None:
            raise RuntimeError("python-gitlab is required for GitLab support")
        # python-gitlab expects the url without trailing '/api/v4'
        url = base_url.rstrip("/")

        ca_file = os.getenv("GITLAB_CA_BUNDLE") or os.getenv("GITLAB_CA_FILE")
        ssl_verify_env = os.getenv("GITLAB_SSL_VERIFY")
        ssl_verify: Any = None
        if ssl_verify_env is not None:
            v = ssl_verify_env.strip().lower()
            if v in ("0", "false", "no", "n"):
                ssl_verify = False
            elif v in ("1", "true", "yes", "y"):
                ssl_verify = True
            else:
                # Allow a path string to be passed through to the library.
                ssl_verify = ssl_verify_env

        kwargs: Dict[str, Any] = {}
        if ssl_verify is not None:
            kwargs["ssl_verify"] = ssl_verify
        if ca_file:
            kwargs["ca_file"] = ca_file

        self._gl = gitlab.Gitlab(url, private_token=token, **kwargs)

    def get_repo(self, name: str, lazy: bool = True) -> ProjectWrapper:
        try:
            project = self._gl.projects.get(name)
        except Exception as e:
            raise UnknownObjectException(str(e))
        return ProjectWrapper(project)
