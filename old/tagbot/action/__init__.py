TAGBOT_WEB = "https://julia-tagbot.com"


class Abort(Exception):
    pass


class InvalidProject(Abort):
    def __init__(self, message: str) -> None:
        self.message = message
