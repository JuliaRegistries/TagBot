"""Wrapper for GitLab to provide a small subset of PyGithub-like
functionality used by this project.

This module intentionally implements only the pieces of API that `Repo`
currently expects (get_repo, repo.default_branch, get_pulls, get_contents,
get_git_blob, create_pull). The wrapper delegates to `python-gitlab` when
available and raises informative errors otherwise.
"""

from typing import Any, Dict, Iterable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    import gitlab as _gitlab

import importlib

gitlab: Any = None
try:
    gitlab = importlib.import_module("gitlab")
except Exception:  # pragma: no cover - optional runtime dependency
    gitlab = None


class UnknownObjectException(Exception):
    pass


class GitlabException(Exception):
    pass


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
    def head(self) -> Any:
        class H:
            def __init__(self, ref: str) -> None:
                self.ref = ref

        return H(getattr(self._mr, "source_branch", ""))


class _Contents:
    def __init__(self, sha: str, content_b64: str):
        self.sha = sha
        self._b64 = content_b64

    @property
    def decoded_content(self) -> bytes:
        from base64 import b64decode

        return b64decode(self._b64)


class ProjectWrapper:
    def __init__(self, project: Any):
        self._project = project
        self._file_cache: Dict[str, str] = {}

    @property
    def default_branch(self) -> str:
        return str(self._project.attributes.get("default_branch") or "")

    @property
    def owner(self) -> Any:
        class Owner:
            def __init__(self, login: str) -> None:
                self.login = login

        ns = self._project.attributes.get("namespace") or {}
        name = ns.get("path") or ns.get("name") or ""
        return Owner(name)

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
            # GitLab accepts 'opened', 'closed', 'merged', 'locked'
            if state == "closed":
                params["state"] = "closed"
            else:
                params["state"] = state
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

    def get_releases(self) -> List[Any]:
        # Return a list of release-like objects with tag_name and created_at
        try:
            rels = self._project.releases.list(all=True)
        except Exception:
            return []

        class R:
            def __init__(self, r: Any) -> None:
                self.tag_name = getattr(r, "tag_name", getattr(r, "name", ""))
                self.created_at = getattr(r, "created_at", None)
                # prefer explicit url, fall back to assets_url
                self.html_url = getattr(r, "url", None) or getattr(
                    r, "assets_url", None
                )

        return [R(r) for r in rels]

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
                # GitLab states: opened, closed
                params["state"] = state
            if since:
                params["updated_after"] = since
            its = self._project.issues.list(all=True, **params)
        except Exception:
            its = []
        for i in its:

            class IssueLike:
                def __init__(self, i: Any) -> None:
                    self.closed_at = getattr(i, "closed_at", None)
                    self.labels = [
                        type("L", (), {"name": label})
                        for label in getattr(i, "labels", [])
                    ]
                    self.pull_request = False
                    self.user = type(
                        "U", (), {"login": getattr(i, "author", {}).get("username", "")}
                    )
                    self.body = getattr(i, "description", "")
                    self.number = getattr(i, "iid", None)
                    self.title = getattr(i, "title", "")
                    self.html_url = getattr(i, "web_url", "")

            issues.append(IssueLike(i))

        # Also include merged merge requests as pull_request-like items
        try:
            mrs = self._project.mergerequests.list(state="merged", all=True)
        except Exception:
            mrs = []
        for m in mrs:

            class IssueAsPR:
                def __init__(self, m: Any) -> None:
                    self.pull_request = True
                    self._mr = m

                def as_pull_request(self) -> Any:
                    class PRObj:
                        def __init__(self, mr: Any) -> None:
                            self.merged = True
                            self.merged_at = getattr(mr, "merged_at", None)
                            self.user = type(
                                "U",
                                (),
                                {
                                    "login": getattr(mr, "author", {}).get(
                                        "username", ""
                                    )
                                },
                            )
                            self.body = getattr(mr, "description", "")
                            self.number = getattr(mr, "iid", None)
                            self.title = getattr(mr, "title", "")
                            self.html_url = getattr(mr, "web_url", "")

                    return PRObj(self._mr)

            issues.append(IssueAsPR(m))
        return issues

    def get_commit(self, sha: str) -> Any:
        # Wrap gitlab commit to provide .commit.author.date
        try:
            c = self._project.commits.get(sha)
        except Exception as e:
            raise UnknownObjectException(str(e))

        class AuthorObj:
            def __init__(self, date: Any) -> None:
                self.date = date

        class CommitObj:
            def __init__(self, c: Any) -> None:
                # python-gitlab commit object may have committed_date or created_at
                d = (
                    getattr(c, "committed_date", None)
                    or getattr(c, "created_at", None)
                    or getattr(c, "committer_date", None)
                )
                # leave as string or datetime depending on gitlab library
                self.commit = type("X", (), {"author": AuthorObj(d)})
                self.sha = getattr(c, "id", getattr(c, "sha", None))

        return CommitObj(c)

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
                from base64 import b64encode

                content_b64 = b64encode(raw.encode("utf8")).decode("ascii")
            except Exception:
                raise UnknownObjectException("Could not fetch file contents")
        fake_sha = f"gl-{path}-{self.default_branch}"
        self._file_cache[fake_sha] = content_b64
        return _Contents(fake_sha, content_b64)

    def get_git_blob(self, sha: str) -> Any:
        # Return an object with .content that is base64-encoded
        if sha not in self._file_cache:
            raise UnknownObjectException("Blob not found")

        class B:
            def __init__(self, content: str) -> None:
                self.content = content

        return B(self._file_cache[sha])

    def get_contents_list(self, path: str) -> List[_Contents]:
        # Helper not used but present for compatibility
        return [self.get_contents(path)]

    def get_commits(
        self,
        sha: Optional[str] = None,
        since: Optional[Any] = None,
        until: Optional[Any] = None,
    ) -> Iterable[Any]:
        # Return iterable of commit-like objects with .commit.tree.sha and .sha
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

            class C:
                def __init__(self, c: Any) -> None:
                    self.sha = getattr(c, "id", getattr(c, "sha", None))
                    tree_sha = getattr(c, "tree_id", None)
                    tree_obj = type("T", (), {"sha": tree_sha})
                    self.commit = type("Z", (), {"tree": tree_obj})

            yield C(c)

    def get_branches(self) -> List[Any]:
        try:
            brs = self._project.branches.list(all=True)
        except Exception:
            brs = []

        out: List[Any] = []
        for b in brs:

            class BObj:
                def __init__(self, b: Any) -> None:
                    self.name = getattr(b, "name", "")
                    commit_sha = getattr(b, "commit", {}).get("id", None)
                    self.commit = type("C", (), {"sha": commit_sha})

            out.append(BObj(b))
        return out

    def get_git_ref(self, ref: str) -> Any:
        # support tags/<tag> and branches
        if ref.startswith("tags/"):
            tag = ref.split("/", 1)[1]
            try:
                t = self._project.tags.get(tag)
                commit_info = getattr(t, "commit", {})
                sha = commit_info.get("id", None) or commit_info.get("sha", None)
            except Exception:
                raise UnknownObjectException("Ref not found")
            obj = type("O", (), {"type": "tag", "sha": sha})
            return type("R", (), {"object": obj})
        # fallback: branch
        try:
            b = self._project.branches.get(ref)
            sha = getattr(b, "commit", {}).get("id", None)
        except Exception:
            raise UnknownObjectException("Ref not found")
        obj = type("O", (), {"type": "commit", "sha": sha})
        return type("R", (), {"object": obj})

    def get_git_tag(self, sha: str) -> Any:
        # Best-effort: return an object with .object.sha -> provided sha
        obj = type("O", (), {"sha": sha})
        return type("T", (), {"object": obj})

    def get_branch(self, name: str) -> Any:
        try:
            b = self._project.branches.get(name)
        except Exception:
            raise UnknownObjectException("Branch not found")
        commit_obj = type("C", (), {"sha": getattr(b, "commit", {}).get("id", None)})
        return type("B", (), {"commit": commit_obj})

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
        try:
            data = {"name": name, "tag_name": tag, "description": body}
            if target_commitish:
                data["ref"] = target_commitish
            rel = self._project.releases.create(data)
            return rel
        except Exception as e:
            raise GitlabException(str(e))


class GitlabClient:
    def __init__(self, token: str, base_url: str):
        if gitlab is None:
            raise RuntimeError("python-gitlab is required for GitLab support")
        # python-gitlab expects the url without trailing '/api/v4'
        url = base_url.rstrip("/")
        self._gl = gitlab.Gitlab(url, private_token=token)

    def get_repo(self, name: str, lazy: bool = True) -> ProjectWrapper:
        try:
            project = self._gl.projects.get(name)
        except Exception as e:
            raise UnknownObjectException(str(e))
        return ProjectWrapper(project)
