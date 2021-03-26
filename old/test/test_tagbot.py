from io import StringIO
from logging import DEBUG, StreamHandler, getLogger
from time import sleep, strftime

from tagbot import LogFormatter


stream = StringIO()
handler = StreamHandler(stream)
logger = getLogger("actions")
logger.addHandler(handler)
logger.setLevel(DEBUG)


def test_actions_logger():
    start = stream.tell()
    handler.setFormatter(LogFormatter("actions"))
    logger.debug("1")
    logger.info("2")
    logger.warning("3")
    logger.error("4")
    logger.debug("a%b\nc\rd")
    logger.info("a%b\nc\rd")
    stream.seek(start)
    assert stream.readlines() == [
        "::debug ::1\n",
        "2\n",
        "::warning ::3\n",
        "::error ::4\n",
        "::debug ::a%25b%0Ac%0Dd\n",
        "a%b\n",
        "c\rd\n",
    ]


def test_fallback_logger():
    start = stream.tell()
    handler.setFormatter(LogFormatter("other"))
    # We can't mock time, so start this test when a new second comes around.
    now = strftime("%H:%M:%S")
    while strftime("%H:%M:%S") == now:
        sleep(0.01)
    logger.debug("1")
    logger.info("2")
    logger.warning("3")
    logger.error("4")
    logger.debug("a\nb")
    now = strftime("%H:%M:%S")
    stream.seek(start)
    assert stream.readlines() == [
        f"{now} | DEBUG | 1\n",
        f"{now} | INFO | 2\n",
        f"{now} | WARNING | 3\n",
        f"{now} | ERROR | 4\n",
        f"{now} | DEBUG | a\n",
        "b\n",
    ]
