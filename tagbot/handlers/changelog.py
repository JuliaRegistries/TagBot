from .. import Context
from ..mixins import AWS


class Handler(AWS):
    """Generates a release changelog."""
    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self) -> None:
        changelog = self.get_changelog(self.ctx.id)
        if not changelog:
            changelog = self.generate_changelog()


def handler(body: dict, _ctx=None) -> None:
    Handler(body).do()
