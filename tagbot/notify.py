from .github_api import GitHubAPI


class Handler(GitHubAPI):
    def __init__(self, evt):
        super().__init__()


def handler(evt, _ctx):
    pass
