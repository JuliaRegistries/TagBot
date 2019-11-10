import os
import sys

from tempfile import gettempdir

os.environ["GITHUB_WORKSPACE"] = gettempdir()
sys.path.insert(0, "../tagbot")
