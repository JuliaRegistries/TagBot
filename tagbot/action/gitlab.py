"""Wrapper for GitLab to provide a small subset of PyGithub-like
functionality used by this project.

This module intentionally implements only the pieces of API that `Repo`
currently expects (get_repo, repo.default_branch, get_pulls, get_contents,
get_git_blob, create_pull). The wrapper delegates to `python-gitlab` when
available and raises informative errors otherwise.
"""
from typing import Any, Dict, List, Optional

try:
    import gitlab
    from gitlab.exceptions import GitlabGetError, GitlabAuthenticationError
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
    def merged_at(self):
        return getattr(self._mr, "merged_at", None)

    @property
    def closed_at(self):
        return getattr(self._mr, "closed_at", None)

    @property
    def merged(self):
        return getattr(self._mr, "merged_at", None) is not None

    @property
    def head(self):
        class H:
            def __init__(self, ref: str):
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
        return self._project.attributes.get("default_branch")

    @property
    def owner(self) -> Any:
        class Owner:
            def __init__(self, login: str):
                self.login = login

        ns = self._project.attributes.get("namespace") or {}
        name = ns.get("path") or ns.get("name") or ""
        return Owner(name)

    def get_pulls(self, head: Optional[str] = None, state: Optional[str] = None) -> List[_PR]:
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

    def get_releases(self):
        # Return a list of release-like objects with tag_name and created_at
        try:
            rels = self._project.releases.list(all=True)
        except Exception:
            return []
        class R:
            def __init__(self, r):
                self.tag_name = getattr(r, "tag_name", getattr(r, "name", ""))
                self.created_at = getattr(r, "created_at", None)
                self.html_url = getattr(r, "url", None) or getattr(r, "assets_url", None)

        return [R(r) for r in rels]

    def get_issues(self, state: Optional[str] = None, since: Optional[Any] = None):
        # Return issues and merged merge-requests as issue-like objects so
        # the rest of the code (which expects GitHub's issue/PR mixing)
        # can operate on them.
        issues = []
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
                def __init__(self, i):
                    self.closed_at = getattr(i, "closed_at", None)
                    self.labels = [type("L", (), {"name": l}) for l in getattr(i, "labels", [])]
                    self.pull_request = False
                    self.user = type("U", (), {"login": getattr(i, "author", {}).get("username", "")})
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
                def __init__(self, m):
                    self.pull_request = True
                    self._mr = m

                def as_pull_request(self):
                    class PRObj:
                        def __init__(self, mr):
                            self.merged = True
                            self.merged_at = getattr(mr, "merged_at", None)
                            self.user = type("U", (), {"login": getattr(mr, "author", {}).get("username", "")})
                            self.body = getattr(mr, "description", "")
                            self.number = getattr(mr, "iid", None)
                            self.title = getattr(mr, "title", "")
                            self.html_url = getattr(mr, "web_url", "")

                    return PRObj(self._mr)

            issues.append(IssueAsPR(m))
        return issues

    def get_commit(self, sha: str):
        # Wrap gitlab commit to provide .commit.author.date
        try:
            c = self._project.commits.get(sha)
        except Exception as e:
            raise UnknownObjectException(str(e))

        class AuthorObj:
            def __init__(self, date):
                self.date = date

        class CommitObj:
            def __init__(self, c):
                # python-gitlab commit object may have committed_date or created_at
                d = getattr(c, "committed_date", None) or getattr(c, "created_at", None) or getattr(c, "committer_date", None)
                # leave as string or datetime depending on gitlab library
                self.commit = type("X", (), {"author": AuthorObj(d)})

        return CommitObj(c)

    def get_contents(self, path: str):
        # Try to fetch file contents at default branch. Store in cache keyed by a fake sha.
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

    def get_git_blob(self, sha: str):
        # Return an object with .content that is base64-encoded
        if sha not in self._file_cache:
            raise UnknownObjectException("Blob not found")
        class B:
            def __init__(self, content):
                self.content = content

        return B(self._file_cache[sha])

    def get_contents_list(self, path: str):
        # Helper not used but present for compatibility
        return [self.get_contents(path)]

    def create_pull(self, title: str, body: str, head: str, base: str):
        # Create a merge request
        try:
            mr = self._project.mergerequests.create({
                "title": title,
                "source_branch": head,
                "target_branch": base,
                "description": body,
            })
            return mr
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
