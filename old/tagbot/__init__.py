import os
import sys
import traceback

from io import StringIO
from logging import (
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    Formatter,
    LogRecord,
    StreamHandler,
    getLogger,
)


class LogFormatter(Formatter):
    """A log formatter that changes its output based on where it's being run."""

    def __init__(self, env: str) -> None:
        super().__init__("%(asctime)s | %(levelname)s | %(msg)s", datefmt="%H:%M:%S")
        self._env = env

    def _fmt_actions(self, record: LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            buf = StringIO()
            cls, inst, tb = record.exc_info
            traceback.print_exception(cls, inst, tb, file=buf)
            buf.seek(0)
            message += "\n" + buf.read()
        if record.levelno == INFO:
            return message
        if record.levelno == DEBUG:
            level = "debug"
        elif record.levelno == WARNING:
            level = "warning"
        elif record.levelno == ERROR:
            level = "error"
        trans = str.maketrans({"%": "%25", "\n": "%0A", "\r": "%0D"})
        return f"::{level} ::{message.translate(trans)}"

    def _fmt_fallback(self, record: LogRecord) -> str:
        return Formatter.format(self, record)

    def format(self, record: LogRecord) -> str:
        if self._env == "actions":
            return self._fmt_actions(record)
        else:
            return self._fmt_fallback(record)


logger = getLogger("tagbot")
_ENV = "local"
if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    _ENV = "lambda"
elif os.getenv("GITHUB_ACTIONS") == "true":
    _ENV = "actions"
log_handler = StreamHandler()
logger.addHandler(log_handler)
log_handler.setFormatter(LogFormatter(_ENV))
if _ENV != "local":
    log_handler.setStream(sys.stdout)
    logger.setLevel(DEBUG)
