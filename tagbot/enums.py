from collections import namedtuple
from enum import Enum, auto


class Status(Enum):
    FINISHED = auto()


Stages = namedtuple("Stages", ["prepare", "tag", "changelog", "release", "notify"])
stages = Stages("prepare", "tag", "changelog", "release", "notify")
